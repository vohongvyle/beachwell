"""Planner Agent: spreads study time out of overload weeks, with breaks and habit tips.

Scheduling is deterministic so the hard rules can be guaranteed and tested:
  * never during a class (with a 15-minute buffer), never after the due time,
  * study blocks of at most 90 minutes with a 15-minute break between blocks,
  * at most `daily_cap` hours of planned study per day,
  * earliest-deadline-first; within a task's window, each next block goes to the
    least-loaded day, so work naturally moves into earlier, lighter weeks.
Tasks are allowed to start up to twice their usual lead time early. The LLM never
places blocks; online it only personalises the wording of the habit tips.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from .. import llm
from ..ical import local_dt
from .deadline import LEAD_DAYS

BLOCK_MAX = 1.5
BLOCK_MIN = 0.5
BREAK = 0.25
CLASS_BUFFER = 0.25
DAY_WINDOW = {"weekday": (9.0, 22.0), "weekend": (10.0, 20.0)}
PROTECTED = [(12.0, 13.0), (18.0, 19.0)]  # lunch and dinner stay free: room for meals and events


@dataclass
class Block:
    task_id: int
    title: str
    course: str
    day: str
    start_hour: float
    end_hour: float

    @property
    def hours(self) -> float:
        return self.end_hour - self.start_hour

    def to_dict(self) -> dict:
        d = asdict(self)
        d["hours"] = round(self.hours, 2)
        return d


def _busy_intervals(classes: list[dict], d: date) -> list[tuple[float, float]]:
    return sorted((c["start_hour"] - CLASS_BUFFER, c["end_hour"] + CLASS_BUFFER)
                  for c in classes if c["weekday"] == d.weekday())


def _free_intervals(d: date, busy: list[tuple[float, float]]) -> list[tuple[float, float]]:
    lo, hi = DAY_WINDOW["weekend" if d.weekday() >= 5 else "weekday"]
    free, cursor = [], lo
    for b0, b1 in sorted(busy):
        if b0 > cursor:
            free.append((cursor, min(b0, hi)))
        cursor = max(cursor, b1)
    if cursor < hi:
        free.append((cursor, hi))
    return [(a, b) for a, b in free if b - a >= BLOCK_MIN]


def _due_dt(task: dict) -> datetime:
    due = task["due"]
    return datetime.fromisoformat(due) if isinstance(due, str) else due


def plan(tasks: list[dict], classes: list[dict], today: date, daily_cap: float = 4.0,
         extra_lead: dict[int, int] | None = None, weekly_capacity: float | None = None) -> dict:
    """Return {"blocks": [...], "unscheduled": [...], "days": {task_id: {date: hours}}}."""
    extra_lead = extra_lead or {}
    open_tasks = [t for t in tasks if not t.get("done") and _due_dt(t).date() >= today and t["hours"] > 0]
    open_tasks.sort(key=_due_dt)
    blocks_by_day: dict[date, list[Block]] = defaultdict(list)
    load: dict[date, float] = defaultdict(float)
    week_load: dict[int, float] = defaultdict(float)
    weekly_capacity = weekly_capacity or daily_cap * 5

    def cost(d: date) -> tuple:
        """Prefer lightly loaded days in lightly loaded weeks; avoid pushing a week past capacity."""
        wk = d.isocalendar()[1]
        over = week_load[wk] >= weekly_capacity
        return (over, load[d] + 0.5 * week_load[wk] / 7, d)
    unscheduled = []
    leftovers: dict[int, tuple[date, float]] = {}

    def place(task: dict, d: date, want: float, latest_end: float | None) -> float:
        """Place up to `want` hours of one block on day d. Returns hours placed."""
        busy = _busy_intervals(classes, d) + PROTECTED + [(b.start_hour - BREAK, b.end_hour + BREAK) for b in blocks_by_day[d]]
        for a, b in _free_intervals(d, busy):
            if latest_end is not None:
                b = min(b, latest_end)
            length = math.floor(min(want, BLOCK_MAX, b - a, daily_cap - load[d]) * 4 + 1e-9) / 4  # quarter hours
            if length >= BLOCK_MIN - 1e-9 or (length >= 0.25 and length >= want - 1e-9):
                blk = Block(task["id"], task["title"], task["course"], d.isoformat(), a, a + length)
                blocks_by_day[d].append(blk)
                load[d] += length
                week_load[d.isocalendar()[1]] += length
                return length
        return 0.0

    for t in open_tasks:
        due = _due_dt(t)
        lead = 2 * LEAD_DAYS.get(t["type"], 3) + extra_lead.get(t["id"], 0)
        first = max(today, due.date() - timedelta(days=lead))
        days = [first + timedelta(days=i) for i in range((due.date() - first).days + 1)]
        remaining = round(t["hours"] * 4) / 4 or 0.25
        stalled = 0
        while remaining > 1e-6 and stalled < len(days):
            # least-loaded day first; ties go to the earlier day
            candidates = sorted(days, key=cost)
            placed_any = False
            for d in candidates:
                if load[d] >= daily_cap - 1e-9:
                    continue
                latest = due.hour + due.minute / 60 - 0.25 if d == due.date() else None
                got = place(t, d, remaining, latest)
                if got > 0:
                    remaining = round(remaining - got, 2)
                    placed_any = True
                    break
            stalled = 0 if placed_any else stalled + len(days)
        if remaining > 1e-6:
            unscheduled.append({"task_id": t["id"], "title": t["title"], "course": t["course"],
                                "hours_left": round(remaining, 2)})
            leftovers[t["id"]] = (due.date(), remaining)

    blocks = sorted((b for bl in blocks_by_day.values() for b in bl), key=lambda b: (b.day, b.start_hour))
    days_by_task: dict[int, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    for b in blocks:
        days_by_task[b.task_id][date.fromisoformat(b.day)] += b.hours
    # Hours that did not fit still exist: count them on the due day so the forecast stays honest.
    for tid, (d, h) in leftovers.items():
        days_by_task[tid][d] += h
    return {"blocks": [b.to_dict() for b in blocks], "unscheduled": unscheduled,
            "days": {k: dict(v) for k, v in days_by_task.items()}}


def check_constraints(plan_out: dict, tasks: list[dict], classes: list[dict], daily_cap: float) -> list[str]:
    """Return a list of rule violations (empty means the plan is valid). Used by tests and eval."""
    problems = []
    by_id = {t["id"]: t for t in tasks}
    per_day: dict[str, list[dict]] = defaultdict(list)
    for b in plan_out["blocks"]:
        per_day[b["day"]].append(b)
        d = date.fromisoformat(b["day"])
        for c0, c1 in _busy_intervals(classes, d):
            if b["start_hour"] < c1 - CLASS_BUFFER and b["end_hour"] > c0 + CLASS_BUFFER:
                problems.append(f"block overlaps class on {b['day']}")
        due = _due_dt(by_id[b["task_id"]])
        if local_dt(d, b["end_hour"]) > due:
            problems.append(f"block for '{b['title']}' ends after its due time")
        if b["end_hour"] - b["start_hour"] > BLOCK_MAX + 1e-9:
            problems.append("block longer than 90 minutes")
    for day, bl in per_day.items():
        if sum(b["end_hour"] - b["start_hour"] for b in bl) > daily_cap + 1e-6:
            problems.append(f"over daily cap on {day}")
        bl = sorted(bl, key=lambda b: b["start_hour"])
        for x, y in zip(bl, bl[1:]):
            if y["start_hour"] < x["end_hour"] + BREAK - 1e-9:
                problems.append(f"blocks without a break on {day}")
    return problems


# ------------------------------------------------------------------- habits

HABITS = [
    # (id, condition key, text). Plain, general wellbeing habits; never medical advice.
    ("sleep-window", "sleep", "Protect a 7-hour sleep window this week: set a hard stop for studying at 11 pm."),
    ("walk-break", "long_days", "Take a 15-minute walk between study blocks on your longest days."),
    ("hardest-first", "overload", "Start each day with the hardest task while your energy is highest."),
    ("focus-blocks", "overload", "Work in 50-minute focus blocks with your phone in another room, then a 10-minute break."),
    ("breathing", "stress", "Before a big study block, try two minutes of slow breathing to settle in."),
    ("real-meals", "overload", "Plan two real meals on your heaviest day. ASI Beach Pantry offers free food to CSULB students."),
    ("talk-it-out", "stress", "If stress keeps building, CAPS runs workshops and groups, and you can book a counselor."),
    ("say-no", "heavy", "Keep extras light this week: it's fine to say no to optional commitments."),
]


def habits_for(week: dict, wellbeing: dict | None, blocks_in_week: list[dict]) -> list[dict]:
    """Pick one or two habits for a Heavy or Overload week."""
    if week["level"] not in ("Heavy", "Overload"):
        return []
    per_day = defaultdict(float)
    for b in blocks_in_week:
        per_day[b["day"]] += b["hours"]
    conds = {"heavy": True, "overload": week["level"] == "Overload", "long_days": any(h >= 3 for h in per_day.values())}
    if wellbeing:
        conds["sleep"] = wellbeing.get("sleep_deficit", 0) >= 0.5
        conds["stress"] = wellbeing.get("stress_recent", 0) >= 3.5
    picked = [{"id": hid, "text": text} for hid, cond, text in HABITS if conds.get(cond)]
    order = ["sleep-window", "talk-it-out", "walk-break", "hardest-first", "focus-blocks", "real-meals", "breathing", "say-no"]
    picked.sort(key=lambda h: order.index(h["id"]))
    return picked[:2]


def personalise_habits(habits: list[dict], interests: str) -> list[dict]:
    """Online only: let Gemini reword tips to fit the student's interests. Keeps meaning and ids."""
    if not habits or llm.mode() == "offline":
        return habits
    prompt = ("Rewrite each wellbeing tip in one short, warm sentence for a college student whose interests are: "
              f"{interests or 'not given'}. Keep the same advice, add no medical claims, keep any named campus "
              "service. Return a JSON list of strings, same order.\nTips:\n" + "\n".join(h["text"] for h in habits))
    out = llm.generate_json(prompt, name="planner.habits")
    if isinstance(out, list) and len(out) == len(habits) and all(isinstance(x, str) for x in out):
        return [{"id": h["id"], "text": x[:220]} for h, x in zip(habits, out)]
    return habits
