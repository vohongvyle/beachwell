"""Campus Stress Radar: anonymized, aggregated forecasts for ASI, CAPS and instructors.

Privacy rules, enforced here rather than in the UI:
  * only students who opted in are counted,
  * no group (college or course) smaller than RADAR_MIN_GROUP is ever returned,
  * only shares and counts leave this module, never a student id or a task of one student.

Outputs:
  * heatmap   - share of students in a Heavy or Overload week, per college and week of term,
  * alerts    - upcoming college-weeks where many students face an Overload week (for ASI/CAPS timing),
  * collisions - course deadlines that land in a week when most enrolled students already
                 face a heavy week, with a what-if: that share if the deadline moved a week.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from .. import semester
from .forecast import forecast

HEAVY = ("Heavy", "Overload")


def _term_forecasts(tasks: list[dict], capacity: float, weeks: int) -> dict[int, dict]:
    """Whole-term view: forecast from the first day of term so every deadline counts."""
    start = semester.week_start(1)
    return {w.week: {"level": w.level, "score": w.score, "majors": len(w.major_deadlines)}
            for w in forecast(tasks, start, capacity, None, weeks)}


def campus_radar(users: list[dict], tasks_by_user: dict[int, list[dict]], today: date, min_group: int = 10,
                 weeks: int = 17, collision_limit: int = 6) -> dict:
    cohort = [u for u in users if u.get("radar_opt_in", 1)]
    per_user = {u["id"]: _term_forecasts(tasks_by_user.get(u["id"], []), u["weekly_capacity"], weeks) for u in cohort}
    current = max(1, semester.week_of(today))
    week_list = [{"week": w, "label": semester.week_label(w)} for w in range(1, weeks + 1)]

    # ---- heatmap by college
    by_college: dict[str, list[int]] = defaultdict(list)
    for u in cohort:
        by_college[u["college"]].append(u["id"])
    rows, suppressed = [], 0
    for college, ids in sorted(by_college.items()):
        if len(ids) < min_group:
            suppressed += 1
            continue
        cells = []
        for w in range(1, weeks + 1):
            levels = [per_user[i][w]["level"] for i in ids]
            cells.append({"week": w,
                          "overload": round(levels.count("Overload") / len(ids), 2),
                          "heavy": round(sum(lv in HEAVY for lv in levels) / len(ids), 2)})
        rows.append({"group": college, "n": len(ids), "cells": cells})
    all_ids = [u["id"] for u in cohort]
    campus_cells = []
    if len(all_ids) >= min_group:
        for w in range(1, weeks + 1):
            levels = [per_user[i][w]["level"] for i in all_ids]
            campus_cells.append({"week": w, "overload": round(levels.count("Overload") / len(all_ids), 2),
                                 "heavy": round(sum(lv in HEAVY for lv in levels) / len(all_ids), 2)})

    # ---- alerts for upcoming weeks
    alerts = []
    for row in rows:
        for cell in row["cells"]:
            if cell["week"] >= current and cell["overload"] >= 0.35:
                alerts.append({
                    "group": row["group"], "n": row["n"], "week": cell["week"],
                    "label": semester.week_label(cell["week"]), "overload": cell["overload"],
                    "text": (f"{round(cell['overload'] * 100)}% of {row['group']} students (n={row['n']}) are overloaded "
                             f"in week {cell['week']} ({semester.week_label(cell['week'])}). A good week for "
                             "de-stress programming or extended CAPS drop-in hours."),
                })
    # one alert per upcoming week (the most affected college), soonest first
    best_per_week: dict[int, dict] = {}
    for a in sorted(alerts, key=lambda a: -a["overload"]):
        best_per_week.setdefault(a["week"], a)
    alerts = [best_per_week[w] for w in sorted(best_per_week)]

    # ---- deadline collisions by course
    enrolled: dict[str, set[int]] = defaultdict(set)
    deadlines: dict[tuple[str, str], dict] = {}
    for uid in all_ids:
        for t in tasks_by_user.get(uid, []):
            enrolled[t["course"]].add(uid)
            if t.get("major"):
                deadlines.setdefault((t["course"], t["title"]), t)
    collisions = []
    for (course, title), t in deadlines.items():
        ids = enrolled[course]
        if len(ids) < min_group:
            continue
        due = datetime.fromisoformat(t["due"]) if isinstance(t["due"], str) else t["due"]
        wk = semester.week_of(due.date())
        if wk < current or wk > weeks:
            continue
        heavy = sum(per_user[i][wk]["level"] in HEAVY for i in ids) / len(ids)
        others = sum(per_user[i][wk]["majors"] - 1 for i in ids) / len(ids)
        if heavy >= 0.5 and others >= 1.0:
            collisions.append({"course": course, "title": title, "due": due.isoformat(), "week": wk,
                               "label": semester.week_label(wk), "n": len(ids), "heavy": round(heavy, 2),
                               "other_majors": round(others, 1)})
    collisions.sort(key=lambda c: (-c["heavy"], c["week"]))
    collisions = collisions[:2 * collision_limit]
    for c in collisions:
        c["what_if"] = _shift_what_if(c, cohort, tasks_by_user, weeks)
        best = min(c["what_if"], key=lambda x: x["heavy"], default=None)
        c["gain"] = round(c["heavy"] - best["heavy"], 2) if best else 0.0
    collisions.sort(key=lambda c: (-c["gain"], -c["heavy"]))
    collisions = collisions[:collision_limit]
    for c in collisions:
        best = min(c["what_if"], key=lambda x: x["heavy"], default=None)
        c["text"] = (f"{c['course']} '{c['title']}' is due in week {c['week']}, when {round(c['heavy'] * 100)}% of its "
                     f"{c['n']} students already face a Heavy or Overload week (about {c['other_majors']:g} other major deadlines each).")
        if best and best["heavy"] < c["heavy"] - 0.1:
            c["text"] += (f" Moving it {best['label']} would drop that to about {round(best['heavy'] * 100)}%.")

    return {"weeks": week_list, "current_week": current, "min_group": min_group, "cohort": len(cohort),
            "suppressed_groups": suppressed, "campus": campus_cells, "heatmap": rows,
            "alerts": alerts[:6], "collisions": collisions}


def _shift_what_if(c: dict, cohort: list[dict], tasks_by_user: dict[int, list[dict]], weeks: int) -> list[dict]:
    """Heavy-week share for the course's students in the deadline's new week if it moved one week earlier or later."""
    caps = {u["id"]: u["weekly_capacity"] for u in cohort}
    ids = [u["id"] for u in cohort if any(t["course"] == c["course"] for t in tasks_by_user.get(u["id"], []))]
    out = []
    for days, label in ((-7, "one week earlier"), (7, "one week later")):
        new_week = c["week"] + days // 7
        if new_week < 1 or new_week >= weeks:  # never suggest moving work into finals week
            continue
        heavy = 0
        for uid in ids:
            shifted = []
            for t in tasks_by_user[uid]:
                if t["course"] == c["course"] and t["title"] == c["title"]:
                    due = datetime.fromisoformat(t["due"]) if isinstance(t["due"], str) else t["due"]
                    t = {**t, "due": (due + timedelta(days=days)).isoformat()}
                shifted.append(t)
            fc = _term_forecasts(shifted, caps[uid], weeks)
            heavy += fc[new_week]["level"] in HEAVY
        out.append({"label": label, "week": new_week, "heavy": round(heavy / max(1, len(ids)), 2)})
    return out
