"""Write the 40 practice semesters used to test the forecast.

Each semester has three courses of normal weekly work, ONE planted crunch week
(3 major deadlines within about 4 days) and ONE decoy week (6 small quizzes or posts).
The forecast should flag the crunch week and ignore the decoy week.

Usage (from backend/):  python scripts/make_practice_semesters.py
Output: eval/data/practice_semesters.json  (and a readable CSV of every deadline)
"""
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SEMESTER_START", "2026-08-24")

from eval.evaluate import RNG_SEED, synthetic_semesters  # noqa: E402

if __name__ == "__main__":
    sems = []
    for i, (tasks, crunch, decoy) in enumerate(synthetic_semesters(40, RNG_SEED), 1):
        sems.append({"id": i, "crunch_week": crunch, "decoy_week": decoy, "tasks": tasks})
    out = ROOT / "eval" / "data" / "practice_semesters.json"
    out.write_text(json.dumps({"description": "40 practice semesters, each with one planted crunch week and one decoy week.",
                               "semesters": sems}, indent=1), encoding="utf-8")
    with open(ROOT / "eval" / "data" / "practice_semesters_deadlines.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["semester", "title", "type", "major", "hours", "due", "is_crunch_week", "is_decoy_week"])
        from datetime import datetime
        from beachwell import semester as sem
        for s in sems:
            for t in s["tasks"]:
                wk = sem.week_of(datetime.fromisoformat(t["due"]).date())
                w.writerow([s["id"], t["title"], t["type"], t["major"], t["hours"], t["due"],
                            wk == s["crunch_week"], wk == s["decoy_week"]])
    print(f"wrote {len(sems)} semesters to {out}")
