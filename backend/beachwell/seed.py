"""Synthetic data for development, the demo and the Campus Radar.

Everything here is SAMPLE data, generated so the prototype can run and be evaluated
without any real student records:
  * a course catalog with realistic deadline patterns (CECS 458 uses the real
    Fall 2026 term-project dates from the syllabus),
  * a synthetic cohort of students for the Campus Radar,
  * one demo student ("Vy") with classes, check-ins and a few logged hours,
  * a campus event catalog. Organisers and venues are real CSULB programs, but
    the dates and times are invented: replace them with real listings before use.
"""
from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from . import db, ical, semester
from .agents import deadline
from .agents.events import PAST_TERMS
from .config import BACKEND_DIR, get_settings

COLLEGES = {
    "Engineering": ["CECS 458", "CECS 429", "CECS 491A", "EE 381", "ME 373", "CE 335"],
    "Natural Sciences & Math": ["BIOL 211", "CHEM 220A", "MATH 380", "PHYS 151", "MATH 247"],
    "Business": ["FIN 300", "MKTG 300", "ACCT 201", "IS 301", "MGMT 425"],
    "Liberal Arts": ["PSY 100", "HIST 172", "SOC 335", "POSC 100", "COMM 130"],
    "Health & Human Services": ["KIN 301", "NUTR 132", "HHS 200", "NRSG 300", "SW 340"],
    "The Arts": ["ART 130", "MUS 190", "DESN 131", "THEA 122", "FEA 101"],
}
GE_COURSES = ["ENGL 317", "PHIL 352", "GEOG 140", "HIST 172"]
COLLEGE_WEIGHTS = {"Engineering": 0.2, "Natural Sciences & Math": 0.17, "Business": 0.19, "Liberal Arts": 0.18,
                   "Health & Human Services": 0.16, "The Arts": 0.10}
BREAK_WEEK = 14   # Thanksgiving week in this placeholder calendar: no deadlines
FINALS_WEEK = 17


@dataclass
class Item:
    week: int
    weekday: int
    hour: float
    title: str
    description: str = ""


def _template(course: str) -> str:
    prefix = course.split()[0]
    return {
        "CECS": "engineering", "EE": "engineering", "ME": "engineering", "CE": "engineering",
        "BIOL": "lab", "CHEM": "lab", "PHYS": "lab", "MATH": "math",
        "FIN": "business", "MKTG": "business", "ACCT": "business", "IS": "business", "MGMT": "business",
        "COMM": "business", "KIN": "health", "NUTR": "health", "HHS": "health", "NRSG": "health", "SW": "health",
        "ART": "arts", "MUS": "arts", "DESN": "arts", "THEA": "arts", "FEA": "arts",
    }.get(prefix, "writing")


def _w(week: int) -> int:
    return week + 1 if week == BREAK_WEEK else week


def course_items(course: str) -> list[Item]:
    """Deterministic deadline pattern for a course (same for every enrolled student)."""
    if course == "CECS 458":
        return _cecs458()
    rng = random.Random(course)
    kind = _template(course)
    mid1, mid2 = rng.choice([7, 8, 9]), rng.choice([11, 12, 13])
    shift = rng.choice([-1, 0, 1])
    items: list[Item] = []
    weekly_day = rng.choice([0, 2, 4])
    if kind == "engineering":
        for k, wk in enumerate(range(2, 16), 1):
            if wk != BREAK_WEEK:
                items.append(Item(wk, weekly_day, 23.98, f"Homework {k}", "Problem set, 5 problems"))
        items += [Item(_w(5 + shift), 4, 23.98, "Project Proposal", "2-3 pages"),
                  Item(_w(9 + shift), 4, 23.98, "Project Milestone 2", "Working prototype and 4 page report"),
                  Item(mid1, 2, 10.0, "Midterm Exam"),
                  Item(16, 1, 23.98, "Final Project Report", "10-12 pages, 200 points"),
                  Item(16, 3, 14.0, "Final Presentation")]
    elif kind == "lab":
        for k, wk in enumerate(range(2, 17), 1):
            if wk != BREAK_WEEK:
                items.append(Item(wk, 4, 9.0, f"Quiz {k}"))
        for k, wk in enumerate(range(3, 16, 2), 1):
            items.append(Item(_w(wk), weekly_day, 23.98, f"Lab Report {k}", "Lab write-up"))
        items += [Item(mid1, 1, 11.0, "Midterm Exam 1"), Item(mid2, 1, 11.0, "Midterm Exam 2"),
                  Item(FINALS_WEEK, 2, 8.0, "Final Exam")]
    elif kind == "math":
        for k, wk in enumerate(range(2, 17), 1):
            if wk != BREAK_WEEK:
                items.append(Item(wk, weekly_day, 23.98, f"Homework {k}", "Problem set"))
        items += [Item(mid1 - 1, 3, 10.0, "Midterm Exam 1"), Item(mid2, 3, 10.0, "Midterm Exam 2"),
                  Item(FINALS_WEEK, 1, 10.0, "Final Exam")]
    elif kind == "business":
        for k, wk in enumerate(range(3, 16, 2), 1):
            items.append(Item(_w(wk), weekly_day, 23.98, f"Case Study {k}", "2 pages"))
        items += [Item(mid1, 3, 12.0, "Midterm Exam"),
                  Item(_w(11 + shift), 2, 23.98, "Group Project Report", "8 pages"),
                  Item(_w(12 + shift), 3, 12.0, "Group Presentation"),
                  Item(FINALS_WEEK, 3, 10.0, "Final Exam")]
    elif kind == "health":
        for k, wk in enumerate(range(2, 17), 1):
            if wk != BREAK_WEEK:
                items.append(Item(wk, 6, 23.98, f"Discussion Post {k}"))
        items += [Item(mid1, 2, 13.0, "Exam 1"), Item(_w(10 + shift), 4, 23.98, "Research Paper", "6-8 pages"),
                  Item(mid2, 2, 13.0, "Exam 2"), Item(FINALS_WEEK, 2, 13.0, "Final Exam")]
    elif kind == "arts":
        for k, wk in enumerate(range(3, 16, 3), 1):
            items.append(Item(_w(wk), weekly_day, 23.98, f"Studio Critique {k}", "Reflection, 1 page"))
        items += [Item(_w(9 + shift), 1, 23.98, "Midterm Project"),
                  Item(16, 3, 23.98, "Final Portfolio Project", "Portfolio and artist statement")]
    else:  # writing / GE
        for k, wk in enumerate(range(2, 17), 1):
            if wk != BREAK_WEEK:
                items.append(Item(wk, 3, 23.98, f"Reading Response {k}"))
        items += [Item(_w(5 + shift), 4, 23.98, "Essay 1", "4-5 pages"),
                  Item(_w(9 + shift), 4, 23.98, "Essay 2", "6-8 pages"),
                  Item(_w(13 + shift), 4, 23.98, "Research Paper Draft", "8 pages"),
                  Item(16, 4, 23.98, "Final Research Paper", "10-12 pages")]
    return items


def _cecs458() -> list[Item]:
    # Real CECS 458/558 Fall 2026 term-project deadlines (Fridays 11:59 pm), plus sample weekly labs.
    items = [Item(5, 4, 23.98, "Phase 0: Team Formation", "Register team in Canvas Groups"),
             Item(8, 4, 23.98, "Phase 1: Ideation, Market Validation & Feasibility Report", "Maximum 4 pages"),
             Item(13, 4, 23.98, "Phase 2: Prototype Progress Report", "Prototype, GitHub documentation, 2 page report"),
             Item(16, 4, 23.98, "Phase 3: Pitch Video and Final Report", "10 minute video and 8 page final report")]
    for k, wk in enumerate(range(2, 16), 1):
        if wk != BREAK_WEEK:
            items.append(Item(wk, 0, 23.98, f"Hands-on Lab {k}"))
    items.append(Item(10, 2, 14.0, "Midterm Exam"))
    return items


def item_due(it: Item) -> datetime:
    d = semester.week_start(it.week) + timedelta(days=it.weekday)
    return ical.local_dt(d, it.hour) if it.hour < 23.9 else datetime.combine(d, time(23, 59), ical.LOCAL_TZ)


def course_ics(courses: list[str]) -> str:
    """A Canvas-style feed for a list of courses (used by the demo and tests)."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//BeachWell sample//Canvas-style feed//EN"]
    for course in courses:
        for k, it in enumerate(course_items(course)):
            due = item_due(it)
            stamp = due.astimezone(ical.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            lines += ["BEGIN:VEVENT", f"UID:event-assignment-{course.replace(' ', '')}-{k}",
                      f"DTSTART:{stamp}", f"DTEND:{stamp}",
                      f"SUMMARY:{it.title} [{course} Sec 01 Fall 2026]"]
            if it.description:
                lines.append(f"DESCRIPTION:{it.description}")
            lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ------------------------------------------------------------------ events

EVENTS_CSV = BACKEND_DIR / "data" / "events_catalog.csv"
_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _hours(hhmm: str) -> float:
    h, m = hhmm.strip().split(":")
    return int(h) + int(m) / 60


def load_catalog(path=None) -> list[tuple]:
    """Read data/events_catalog.csv (one row per recurring program).

    Columns: series_id, title, organizer, description, tags (;-separated), location,
    days (Mon;Wed), start and end (HH:MM, 24-hour), weeks ("regular" or 8;9;16),
    source_url, is_real_program. Edit the CSV, then run scripts/seed.py --reset.
    """
    rows = []
    with open(path or EVENTS_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r.get("series_id", "").strip():
                continue
            weeks = r["weeks"].strip()
            rows.append((r["series_id"].strip(), r["title"].strip(), r["organizer"].strip(), r["description"].strip(),
                         ",".join(t.strip() for t in r["tags"].split(";") if t.strip()), r["location"].strip(),
                         [_DAYS.index(d.strip()[:3].title()) for d in r["days"].split(";") if d.strip()],
                         _hours(r["start"]), _hours(r["end"]),
                         "regular" if weeks == "regular" else [int(w) for w in weeks.split(";") if w.strip()],
                         r.get("source_url", "").strip()))
    return rows


REGULAR_WEEKS = [w for w in range(2, 17) if w != BREAK_WEEK]
POSTED_THROUGH_WEEK = 12  # Fall 2026 events after this week are "not posted yet" -> projected as expected


def build_events() -> list[dict]:
    cur_start = semester.semester_start()
    terms = {**{k: v - timedelta(days=v.weekday()) for k, v in PAST_TERMS.items()}, "Fall 2026": cur_start}
    out = []
    for term, start in terms.items():
        for series, title, org, desc, tags, loc, days, h0, h1, weeks, src in load_catalog():
            for wk in (REGULAR_WEEKS if weeks == "regular" else weeks):
                if term == "Fall 2026" and wk > POSTED_THROUGH_WEEK:
                    continue
                for wd in days:
                    d = start + timedelta(days=7 * (wk - 1) + wd)
                    out.append({
                        "id": f"{series}-{d.isoformat()}", "title": title, "organizer": org, "description": desc,
                        "tags": tags, "start": ical.local_dt(d, h0).isoformat(), "end": ical.local_dt(d, h1).isoformat(),
                        "location": loc, "series": series, "source_url": src, "is_sample": 1,
                    })
    return out


# ------------------------------------------------------------------ people

DEMO_COURSES = ["CECS 458", "CECS 429", "MATH 380", "ENGL 317", "PHIL 352"]
DEMO_CLASSES = [
    ("CECS 458", 0, 14.0, 15.25), ("CECS 458", 2, 14.0, 15.25),
    ("CECS 429", 1, 9.5, 10.75), ("CECS 429", 3, 9.5, 10.75),
    ("MATH 380", 0, 10.0, 10.83), ("MATH 380", 2, 10.0, 10.83), ("MATH 380", 4, 10.0, 10.83),
    ("ENGL 317", 1, 12.5, 13.75), ("ENGL 317", 3, 12.5, 13.75),
    ("PHIL 352", 2, 17.5, 18.75),
]
DEMO_INTERESTS = ("I like yoga, being outdoors and drawing. I love dogs. Big crowds drain me, "
                  "I'd rather do something quiet. I want to make a few friends outside my major.")
# How much longer (x) the demo student really takes per type, for the pace model.
DEMO_PACE = {"essay": 1.5, "reading": 1.3, "homework": 1.15, "lab": 1.0, "quiz": 0.8, "project": 1.3, "admin": 1.0}


def seed(reset: bool = False, cohort_size: int = 420, seed_value: int = 7, use_llm: bool = False) -> dict:
    from . import service

    rng = random.Random(seed_value)
    s = get_settings()
    if reset and s.db_path.exists():
        s.db_path.unlink()
    with db.session() as c:
        if db.one(c.execute("SELECT COUNT(*) AS n FROM users"))["n"] and not reset:
            return {"skipped": True}
        evs = build_events()
        c.executemany("INSERT OR REPLACE INTO events (id, title, organizer, description, tags, start, end, location, "
                      "series, source_url, is_sample) VALUES (:id, :title, :organizer, :description, :tags, :start, "
                      ":end, :location, :series, :source_url, :is_sample)", evs)

        # ---- synthetic cohort (for the Campus Radar)
        estimates: dict[tuple[str, str], deadline.Estimate] = {}
        task_rows = []
        colleges = list(COLLEGE_WEIGHTS)
        for n in range(cohort_size):
            college = rng.choices(colleges, weights=[COLLEGE_WEIGHTS[x] for x in colleges])[0]
            courses = rng.sample(COLLEGES[college], k=min(3, len(COLLEGES[college])))
            courses += rng.sample([g for g in GE_COURSES if g not in courses], k=rng.choice([1, 2]))
            cap = round(min(36, max(14, rng.gauss(25, 4.5))), 1)
            uid = c.execute("INSERT INTO users (name, college, weekly_capacity, radar_opt_in, is_synthetic) "
                            "VALUES (?, ?, ?, ?, 1)", (f"Synthetic {n + 1}", college, cap,
                                                       int(rng.random() < 0.9))).lastrowid
            for course in courses:
                for k, it in enumerate(course_items(course)):
                    key = (course, it.title)
                    if key not in estimates:
                        estimates[key] = deadline.estimate_rules(it.title, it.description)
                    e = estimates[key]
                    task_rows.append((uid, f"{course}-{k}", it.title, course, item_due(it).isoformat(),
                                      it.description, e.type, int(e.major), e.hours, "rules"))
        c.executemany("INSERT INTO tasks (user_id, uid, title, course, due, description, type, major, base_hours, "
                      "est_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", task_rows)

        # ---- demo student
        demo = service.create_user("Vy", DEMO_INTERESTS, "Engineering", 25, True, conn=c)
        service.import_ics(demo["id"], course_ics(DEMO_COURSES), conn=c, use_llm=use_llm)
        c.executemany("INSERT INTO classes (user_id, course, weekday, start_hour, end_hour) VALUES (?, ?, ?, ?, ?)",
                      [(demo["id"], *row) for row in DEMO_CLASSES])
        today = s.today()
        done = db.rows(c.execute("SELECT id, type, base_hours, due FROM tasks WHERE user_id = ? AND due < ?",
                                 (demo["id"], today.isoformat())))
        for t in done:
            actual = None
            if t["type"] in ("essay", "project", "exam") or rng.random() < 0.7:
                actual = round(t["base_hours"] * DEMO_PACE.get(t["type"], 1.0) * rng.uniform(0.85, 1.15) * 4) / 4
                actual = max(0.25, actual)
            c.execute("UPDATE tasks SET done = 1, actual_hours = ? WHERE id = ?", (actual, t["id"]))
        sleep = [7.6, 7.3, 7.4, 7.0, 6.4, 5.8, 5.4]
        stress = [2, 2, 3, 3, 3, 4, 4]
        for i, (sl, st) in enumerate(zip(sleep, stress)):
            d = today - timedelta(days=len(sleep) - 1 - i)
            c.execute("INSERT OR REPLACE INTO checkins (user_id, day, sleep_hours, stress) VALUES (?, ?, ?, ?)",
                      (demo["id"], d.isoformat(), sl, st))
    service._radar_cache.clear()
    return {"skipped": False, "demo_user_id": demo["id"], "cohort": cohort_size, "events": len(evs),
            "synthetic_tasks": len(task_rows)}
