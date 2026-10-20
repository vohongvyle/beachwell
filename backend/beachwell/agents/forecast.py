"""Workload Agent: turns deadlines and check-ins into a weekly Workload Score (0-100).

The load index is transparent on purpose, so every label can be explained:

  1. Each open task's hours are spread over its work window (LEAD_DAYS before the
     due date, or from today if that window has already started).
  2. For each week:
       load      = hours of work that week / the student's weekly study capacity
       density   = most major deadlines (exam, project, essay, presentation) due within any 4 days,
                   (in a what-if or plan, each is weighted by how much of its work is still left
                   compared with the usual schedule, so starting early really lowers the pressure)
       due       = hours of the assignments that come due that week / capacity (deadline pressure,
                   weighted the same way)
       wellbeing = recent sleep below the student's own average, and recent stress (current week only)
     each scaled to 0..1: s_load=(load-0.4)/0.9, s_density=(weighted majors-1)/2, s_due=(due-0.4)/1.0
  3. score = 100 * (0.40*s_load + 0.30*s_density + 0.30*s_due)
     with a check-in that week: 100 * (0.36*s_load + 0.27*s_density + 0.27*s_due + 0.10*s_well)
     Light < 25 <= Moderate < 42 <= Heavy < 58 <= Overload

The weights and thresholds were tuned on synthetic semesters (see eval/). The LLM is not
used to compute the score; online it only rewrites the reasons in friendlier words.

What-if: `extra_lead` starts chosen tasks N days earlier; `plan_days` replaces the
default spreading with the hours the Planner actually scheduled.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from statistics import mean

from .. import semester
from .deadline import LEAD_DAYS

LEVELS = [(25, "Light"), (42, "Moderate"), (58, "Heavy"), (101, "Overload")]


def level_for(score: float) -> str:
    for cutoff, name in LEVELS:
        if score < cutoff:
            return name
    return "Overload"


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _due_date(task: dict) -> date:
    if "_due" in task:
        return task["_due_date"]
    due = task["due"]
    if isinstance(due, str):
        due = datetime.fromisoformat(due)
    return due.date() if isinstance(due, datetime) else due


def _due_dt(task: dict) -> datetime:
    if "_due" in task:
        return task["_due"]
    due = task["due"]
    return datetime.fromisoformat(due) if isinstance(due, str) else due


def work_days(task: dict, today: date, extra_lead: int = 0) -> list[date]:
    """Days on which the default schedule works on a task."""
    due_dt = _due_dt(task)
    due_day = due_dt.date()
    last = due_day if due_dt.hour >= 17 else due_day - timedelta(days=1)
    lead = LEAD_DAYS.get(task["type"], 3) + max(0, extra_lead)
    first = max(today, due_day - timedelta(days=lead))
    if last < first:
        last = first if due_day >= today else first - timedelta(days=1)
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def spread_hours(tasks: list[dict], today: date, extra_lead: dict[int, int] | None = None,
                 plan_days: dict[int, dict[date, float]] | None = None) -> dict[int, dict[date, float]]:
    """task id -> {day: hours}. Only open tasks due today or later."""
    extra_lead = extra_lead or {}
    out: dict[int, dict[date, float]] = {}
    for t in tasks:
        if t.get("done") or _due_date(t) < today or t["hours"] <= 0:
            continue
        if plan_days and t["id"] in plan_days:
            out[t["id"]] = dict(plan_days[t["id"]])
            continue
        days = work_days(t, today, extra_lead.get(t["id"], 0))
        if not days:
            continue
        share = t["hours"] / len(days)
        out[t["id"]] = {d: share for d in days}
    return out


def _prep(task: dict) -> dict:
    """Parse the due date once (the forecast runs hundreds of times for the Campus Radar)."""
    if "_due" in task:
        return task
    due = _due_dt(task)
    return {**task, "_due": due, "_due_date": due.date()}


@dataclass
class WeekForecast:
    week: int
    label: str
    start: str
    end: str
    level: str
    score: float
    hours: float
    capacity: float
    major_deadlines: list[dict]
    deadlines: int
    max_majors_4d: int
    reasons: list[str] = field(default_factory=list)
    top_tasks: list[dict] = field(default_factory=list)
    wellbeing: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _wellbeing(checkins: list[dict], today: date) -> dict | None:
    """Recent (last 3 days) sleep vs the student's own average, and recent stress."""
    if not checkins:
        return None
    by_day = sorted(checkins, key=lambda c: c["day"])
    recent = [c for c in by_day if date.fromisoformat(c["day"]) > today - timedelta(days=3)]
    if not recent:
        return None
    baseline = mean(c["sleep_hours"] for c in by_day) if len(by_day) >= 4 else 7.0
    sleep_recent = mean(c["sleep_hours"] for c in recent)
    stress_recent = mean(c["stress"] for c in recent)
    return {
        "sleep_recent": round(sleep_recent, 1),
        "sleep_baseline": round(baseline, 1),
        "sleep_deficit": round(max(0.0, baseline - sleep_recent), 1),
        "stress_recent": round(stress_recent, 1),
    }


def forecast(tasks: list[dict], today: date, capacity: float = 20.0, checkins: list[dict] | None = None,
             weeks: int = 7, extra_lead: dict[int, int] | None = None,
             plan_days: dict[int, dict[date, float]] | None = None) -> list[WeekForecast]:
    """tasks: dicts with id, title, course, due, type, major, hours (effective), done."""
    capacity = max(capacity, 1.0)
    tasks = [_prep(t) for t in tasks]
    default_per_task = spread_hours(tasks, today)
    per_task = spread_hours(tasks, today, extra_lead, plan_days) if (extra_lead or plan_days) else default_per_task
    by_id = {t["id"]: t for t in tasks}
    first_week = max(1, semester.week_of(today))
    well = _wellbeing(checkins or [], today)
    open_majors = [t for t in tasks if t.get("major") and not t.get("done") and _due_date(t) >= today]

    results = []
    for wk in range(first_week, first_week + weeks):
        start, end = semester.week_range(wk)
        hours_by_task: dict[int, float] = defaultdict(float)
        for tid, days in per_task.items():
            for d, h in days.items():
                if start <= d <= end:
                    hours_by_task[tid] += h
        hours = sum(hours_by_task.values())
        due_in_week = [t for t in tasks if start <= t["_due_date"] <= end and not t.get("done")]
        majors_in_week = [t for t in due_in_week if t.get("major")]

        def left(days: dict | None) -> float:
            total = sum(days.values()) if days else 0.0
            return sum(h for d, h in days.items() if d >= start) / total if total else 0.0

        def remaining(t: dict) -> float:
            """1.0 on the usual schedule; lower when a what-if or the plan gets work done before this week."""
            if per_task is default_per_task:
                return 1.0
            usual = left(default_per_task.get(t["id"]))
            return min(1.0, left(per_task.get(t["id"])) / usual) if usual else 1.0

        max4, weighted4 = 0, 0.0
        if majors_in_week:
            weights = [(t["_due_date"], remaining(t)) for t in open_majors]
            for offset in range(-3, 7):
                d0 = start + timedelta(days=offset)
                d1 = d0 + timedelta(days=3)
                window = [(d, w) for d, w in weights if d0 <= d <= d1]
                if any(start <= d <= end for d, _ in window):
                    max4 = max(max4, len(window))
                    weighted4 = max(weighted4, sum(w for _, w in window))
        due_hours = sum(t["hours"] * remaining(t) for t in due_in_week)
        load = hours / capacity
        s_load = _clamp((load - 0.4) / 0.9)
        s_density = _clamp((weighted4 - 1) / 2)
        s_due = _clamp((due_hours / capacity - 0.4) / 1.0)
        wk_well = well if (well and start <= today <= end) else None
        reasons: list[tuple[float, str]] = []
        if wk_well:
            s_well = 0.5 * _clamp(wk_well["sleep_deficit"] / 2.5) + 0.5 * _clamp((wk_well["stress_recent"] - 2) / 3)
            score = 100 * (0.36 * s_load + 0.27 * s_density + 0.27 * s_due + 0.10 * s_well)
            if wk_well["sleep_deficit"] >= 0.5:
                reasons.append((0.10 * s_well + 0.01, f"sleep down {wk_well['sleep_deficit']:g} h from your average"))
            if wk_well["stress_recent"] >= 3.5:
                reasons.append((0.05, f"recent stress around {wk_well['stress_recent']:g}/5"))
        else:
            score = 100 * (0.40 * s_load + 0.30 * s_density + 0.30 * s_due)
        if hours >= 1:
            reasons.append((0.4 * s_load + 0.001, f"about {round(hours)} h of work vs ~{round(capacity)} h you usually have"))
        if max4 >= 2:
            reasons.append((0.3 * s_density + 0.002, f"{max4} major deadlines within 4 days"))
        if s_due > 0.3:
            reasons.append((0.3 * s_due, f"about {round(due_hours)} h of assignments come due"))
        elif len(due_in_week) >= 5:
            reasons.append((0.003, f"{len(due_in_week)} smaller deadlines, but none are big"))
        if not reasons:
            reasons.append((0, "a light week"))

        top = sorted(hours_by_task.items(), key=lambda kv: -kv[1])[:4]
        results.append(WeekForecast(
            week=wk,
            label=semester.week_label(wk),
            start=start.isoformat(),
            end=end.isoformat(),
            level=level_for(score),
            score=round(score, 1),
            hours=round(hours, 1),
            capacity=round(capacity, 1),
            major_deadlines=[{"id": t["id"], "title": t["title"], "course": t["course"],
                              "due": t["_due"].isoformat()} for t in sorted(majors_in_week, key=_due_date)],
            deadlines=len(due_in_week),
            max_majors_4d=max4,
            reasons=[r for _, r in sorted(reasons, key=lambda x: -x[0])][:3],
            top_tasks=[{"id": tid, "title": by_id[tid]["title"], "course": by_id[tid]["course"],
                        "hours": round(h, 1)} for tid, h in top],
            wellbeing=wk_well,
        ))
    return results


def headline(weeks: list[WeekForecast]) -> str:
    """One sentence for the top of the screen."""
    overloads = [w for w in weeks if w.level == "Overload"]
    if overloads:
        w = overloads[0]
        return f"Week {w.week} ({w.label}) is an overload week: {w.reasons[0]}."
    heavies = [w for w in weeks if w.level == "Heavy"]
    if heavies:
        return f"Week {heavies[0].week} ({heavies[0].label}) will be heavy. Starting early keeps it manageable."
    return "Your workload looks manageable for the next few weeks. A good time to get ahead."
