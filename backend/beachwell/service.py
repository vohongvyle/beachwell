"""Glue between storage and agents. The API routes call only these functions."""
from __future__ import annotations

import ipaddress
import os
import socket
import time
from datetime import date, datetime
from urllib.parse import urlparse

import requests

from . import db, ical, llm
from .agents import deadline, events as events_agent, forecast as fc, pace, planner, radar, safety
from .config import get_settings

FEED_HOST_SUFFIXES = (".instructure.com",)  # Canvas cloud; add your own host in ALLOWED_FEED_HOSTS


class NotFound(Exception):
    pass


class BadRequest(Exception):
    pass


# ------------------------------------------------------------------ users

def create_user(name: str, interests: str = "", college: str = "Undeclared", weekly_capacity: float = 25,
                radar_opt_in: bool = True, is_synthetic: bool = False, conn=None) -> dict:
    name = (name or "").strip()[:60] or "Student"
    with _maybe(conn) as c:
        cur = c.execute(
            "INSERT INTO users (name, interests, college, weekly_capacity, radar_opt_in, is_synthetic) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, (interests or "")[:600], college, float(weekly_capacity), int(radar_opt_in), int(is_synthetic)),
        )
        return get_user(cur.lastrowid, conn=c)


def get_user(user_id: int, conn=None) -> dict:
    with _maybe(conn) as c:
        u = db.one(c.execute("SELECT * FROM users WHERE id = ?", (user_id,)))
    if not u:
        raise NotFound(f"user {user_id} not found")
    return u


def update_user(user_id: int, **fields) -> dict:
    allowed = {"name", "interests", "college", "weekly_capacity", "radar_opt_in"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if sets:
        with db.session() as c:
            c.execute(f"UPDATE users SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", (*sets.values(), user_id))
    _radar_cache.clear()
    return get_user(user_id)


def delete_user(user_id: int) -> None:
    with db.session() as c:
        c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    _radar_cache.clear()


# ------------------------------------------------------------------ deadlines

def _check_feed_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise BadRequest("The Canvas feed link must start with https://")
    host = parsed.hostname.lower()
    extra = tuple(h.strip().lower() for h in os.environ.get("ALLOWED_FEED_HOSTS", "").split(",") if h.strip())
    if not (host.endswith(FEED_HOST_SUFFIXES) or host in extra):
        raise BadRequest("Paste the Calendar Feed link from Canvas (it ends in .ics on an instructure.com address).")
    try:  # refuse hosts that resolve to private addresses (SSRF guard)
        for info in socket.getaddrinfo(host, 443):
            if ipaddress.ip_address(info[4][0]).is_private:
                raise BadRequest("That address is not allowed.")
    except socket.gaierror as exc:
        raise BadRequest("Could not reach that address.") from exc


def fetch_feed(url: str) -> str:
    if not get_settings().allow_feed_fetch:
        raise BadRequest("Fetching feeds is turned off on this server; upload the .ics file instead.")
    _check_feed_url(url.strip())
    resp = requests.get(url.strip(), timeout=20, allow_redirects=False)
    if resp.status_code != 200 or "BEGIN:VCALENDAR" not in resp.text[:2000]:
        raise BadRequest("That link did not return a calendar feed.")
    return resp.text


def import_ics(user_id: int, text: str, conn=None, use_llm: bool = True) -> dict:
    """Parse a Canvas feed, estimate new items, and upsert them. The feed URL itself is never stored."""
    items = ical.parse_ics(text)
    if not items:
        raise BadRequest("No calendar items found in that feed.")
    with _maybe(conn) as c:
        existing = {r["uid"] for r in db.rows(c.execute("SELECT uid FROM tasks WHERE user_id = ?", (user_id,)))}
        new = [i for i in items if i.uid not in existing]
        payload = [{"title": i.title, "course": i.course, "description": i.description} for i in new]
        ests = deadline.estimate_batch(payload) if use_llm else [deadline.estimate_rules(p["title"], p["description"]) for p in payload]
        c.executemany(
            "INSERT INTO tasks (user_id, uid, title, course, due, description, type, major, base_hours, est_source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(user_id, i.uid, i.title, i.course, i.due.isoformat(), i.description, e.type, int(e.major), e.hours, e.source)
             for i, e in zip(new, ests)],
        )
        for i in items:
            if i.uid in existing:  # due dates move; keep the student's own edits
                c.execute("UPDATE tasks SET due = ?, title = ?, course = ? WHERE user_id = ? AND uid = ?",
                          (i.due.isoformat(), i.title, i.course, user_id, i.uid))
    _radar_cache.clear()
    return {"items": len(items), "added": len(new), "updated": len(items) - len(new),
            "estimator": ests[0].source if new else None}


def list_tasks(user_id: int, conn=None) -> list[dict]:
    with _maybe(conn) as c:
        tasks = db.rows(c.execute("SELECT * FROM tasks WHERE user_id = ? ORDER BY due", (user_id,)))
    model = pace_model(tasks)
    for t in tasks:
        t["hours"] = pace.effective_hours(t, model)
        t["done"] = bool(t["done"])
        t["major"] = bool(t["major"])
    return tasks


def update_task(task_id: int, user_id: int, **fields) -> dict:
    allowed = {"user_hours", "actual_hours", "done"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if "done" in sets:
        sets["done"] = int(bool(sets["done"]))
    for k in ("user_hours", "actual_hours"):
        if k in sets and sets[k] is not None and not (0 < float(sets[k]) <= 80):
            raise BadRequest(f"{k} must be between 0 and 80 hours")
    with db.session() as c:
        if not db.one(c.execute("SELECT id FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))):
            raise NotFound("task not found")
        if sets:
            c.execute(f"UPDATE tasks SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", (*sets.values(), task_id))
    _radar_cache.clear()
    return next(t for t in list_tasks(user_id) if t["id"] == task_id)


def pace_model(tasks: list[dict]) -> pace.PaceModel:
    history = [(t["type"], t["base_hours"], t["actual_hours"]) for t in tasks if t.get("actual_hours")]
    return pace.fit(history)


# ------------------------------------------------------------------ classes and check-ins

def set_classes(user_id: int, classes: list[dict]) -> list[dict]:
    clean = []
    for cl in classes:
        wd, s, e = int(cl["weekday"]), float(cl["start_hour"]), float(cl["end_hour"])
        if not (0 <= wd <= 6 and 0 <= s < e <= 24):
            raise BadRequest("Class times must be within one day, start before end")
        clean.append((user_id, str(cl.get("course", "Class"))[:40], wd, s, e))
    with db.session() as c:
        c.execute("DELETE FROM classes WHERE user_id = ?", (user_id,))
        c.executemany("INSERT INTO classes (user_id, course, weekday, start_hour, end_hour) VALUES (?, ?, ?, ?, ?)", clean)
    return get_classes(user_id)


def get_classes(user_id: int, conn=None) -> list[dict]:
    with _maybe(conn) as c:
        return db.rows(c.execute("SELECT course, weekday, start_hour, end_hour FROM classes WHERE user_id = ? "
                                 "ORDER BY weekday, start_hour", (user_id,)))


def add_checkin(user_id: int, sleep_hours: float, stress: int, note: str = "", day: str | None = None) -> dict:
    if not (0 <= float(sleep_hours) <= 16) or not (1 <= int(stress) <= 5):
        raise BadRequest("Sleep must be 0-16 hours and stress 1-5")
    result = safety.check(note)  # the note is checked, then discarded
    day = day or get_settings().today().isoformat()
    with db.session() as c:
        c.execute("INSERT INTO checkins (user_id, day, sleep_hours, stress, flagged) VALUES (?, ?, ?, ?, ?) "
                  "ON CONFLICT(user_id, day) DO UPDATE SET sleep_hours = excluded.sleep_hours, "
                  "stress = excluded.stress, flagged = excluded.flagged",
                  (user_id, day, float(sleep_hours), int(stress), int(result["level"] == "crisis")))
    return {"saved": True, "day": day, "safety": result}


def get_checkins(user_id: int, limit: int = 30, conn=None) -> list[dict]:
    with _maybe(conn) as c:
        return db.rows(c.execute("SELECT day, sleep_hours, stress FROM checkins WHERE user_id = ? "
                                 "ORDER BY day DESC LIMIT ?", (user_id, limit)))[::-1]


# ------------------------------------------------------------------ forecast, plan, events

def _daily_cap(user: dict) -> float:
    return max(2.0, min(6.0, round(user["weekly_capacity"] / 5, 1)))


def user_forecast(user_id: int, weeks: int = 7, extra_lead: dict[int, int] | None = None,
                  use_plan: bool = False) -> dict:
    user = get_user(user_id)
    tasks = list_tasks(user_id)
    today = get_settings().today()
    plan_days = None
    if use_plan:
        plan_days = planner.plan(tasks, get_classes(user_id), today, _daily_cap(user), extra_lead, user["weekly_capacity"])["days"]
    weeks_out = fc.forecast(tasks, today, user["weekly_capacity"], get_checkins(user_id), weeks, extra_lead, plan_days)
    model = pace_model(tasks)
    return {
        "today": today.isoformat(),
        "headline": fc.headline(weeks_out),
        "weeks": [w.to_dict() for w in weeks_out],
        "pace": {"notes": model.describe(), "logged": model.n},
        "mode": llm.mode(),
        "what_if": {"extra_lead": extra_lead or {}, "use_plan": use_plan},
    }


def user_plan(user_id: int, weeks: int = 7) -> dict:
    user = get_user(user_id)
    tasks = list_tasks(user_id)
    today = get_settings().today()
    classes = get_classes(user_id)
    p = planner.plan(tasks, classes, today, _daily_cap(user), weekly_capacity=user["weekly_capacity"])
    before = fc.forecast(tasks, today, user["weekly_capacity"], get_checkins(user_id), weeks)
    after = fc.forecast(tasks, today, user["weekly_capacity"], get_checkins(user_id), weeks, plan_days=p["days"])
    habit_weeks = []
    for w_before, w_after in zip(before, after):
        wb = w_before.to_dict()
        blocks = [b for b in p["blocks"] if wb["start"] <= b["day"] <= wb["end"]]
        habits = planner.habits_for(wb, wb.get("wellbeing"), blocks)
        habit_weeks.append({"week": wb["week"], "label": wb["label"], "start": wb["start"], "end": wb["end"],
                            "before": w_before.level,
                            "after": w_after.level, "hours_before": w_before.hours, "hours_after": w_after.hours,
                            "habits": planner.personalise_habits(habits, user["interests"])})
    horizon_end = before[-1].end if before else today.isoformat()
    return {
        "daily_cap": _daily_cap(user),
        "blocks": [b for b in p["blocks"] if b["day"] <= horizon_end],
        "unscheduled": p["unscheduled"],
        "weeks": habit_weeks,
        "violations": planner.check_constraints(p, tasks, classes, _daily_cap(user)),
    }


def plan_ics(user_id: int) -> str:
    plan_out = user_plan(user_id, weeks=10)
    evs = [{"uid": f"u{user_id}-t{b['task_id']}-{b['day']}-{b['start_hour']}",
            "title": f"Study: {b['title']} ({b['course']})",
            "start": ical.local_dt(datetime.fromisoformat(b["day"]).date(), b["start_hour"]),
            "end": ical.local_dt(datetime.fromisoformat(b["day"]).date(), b["end_hour"]),
            "description": "Planned by BeachWell. Take a 15-minute break after this block."}
           for b in plan_out["blocks"]]
    return ical.write_ics(evs)


def all_events(conn=None) -> list[dict]:
    with _maybe(conn) as c:
        return db.rows(c.execute("SELECT * FROM events ORDER BY start"))


def user_events(user_id: int, weeks: int = 7) -> dict:
    user = get_user(user_id)
    f = user_forecast(user_id, weeks)
    p = planner.plan(list_tasks(user_id), get_classes(user_id), get_settings().today(), _daily_cap(user),
                     weekly_capacity=user["weekly_capacity"])
    recs = events_agent.recommend(user["interests"], f["weeks"], all_events(), get_classes(user_id), p["blocks"],
                                  get_settings().today())
    return {"weeks": recs, "mode": llm.mode()}


# ------------------------------------------------------------------ radar

_radar_cache: dict[str, tuple[float, dict]] = {}


def campus_radar() -> dict:
    hit = _radar_cache.get("radar")
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    s = get_settings()
    with db.session() as c:
        users = db.rows(c.execute("SELECT id, college, weekly_capacity, radar_opt_in FROM users"))
        tasks = db.rows(c.execute("SELECT t.* FROM tasks t JOIN users u ON u.id = t.user_id WHERE u.radar_opt_in = 1"))
    by_user: dict[int, list[dict]] = {}
    for t in tasks:
        t["hours"] = t["user_hours"] if t["user_hours"] is not None else t["base_hours"]
        t["done"], t["major"] = False, bool(t["major"])  # whole-term view
        by_user.setdefault(t["user_id"], []).append(t)
    out = radar.campus_radar(users, by_user, s.today(), s.radar_min_group, weeks=s.semester_weeks)
    _radar_cache["radar"] = (time.time(), out)
    return out


# ------------------------------------------------------------------ helpers

class _maybe:
    """Use the caller's connection if given, else open a short session."""

    def __init__(self, conn):
        self.conn = conn
        self._ctx = None

    def __enter__(self):
        if self.conn is not None:
            return self.conn
        self._ctx = db.session()
        return self._ctx.__enter__()

    def __exit__(self, *exc):
        if self._ctx is not None:
            return self._ctx.__exit__(*exc)
        return False


def today() -> date:
    return get_settings().today()
