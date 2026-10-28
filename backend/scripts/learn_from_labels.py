"""Learn from the team's labels (run after scripts/merge_labels.py, from backend/):

    python scripts/learn_from_labels.py

1. Event profiles (data/event_profiles.json): for each campus program, what the labeled
   sample students who picked it wrote, weighted by pick order. The recommender compares a
   new student's words with these profiles as well as with the event description, so
   "I really need sleep" can find the Rest and Recharge Room even though its text never says "sleep".
2. Effort calibration (data/effort_calibration.json): a per-type multiplier that moves the
   rule-based hour estimates toward the team's labels, shrunk toward the overall ratio.

The evaluation (eval/evaluate.py) never scores an item or a student with something learned
from that same item or student (leave-one-out), so its numbers stay fair.
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from beachwell.agents import deadline  # noqa: E402
from beachwell.agents.events import PROFILE_FILE, build_profiles  # noqa: E402

personas = json.loads((ROOT / "eval" / "data" / "event_personas.json").read_text(encoding="utf-8"))
profiles = build_profiles(personas)
PROFILE_FILE.write_text(json.dumps(profiles, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Event profiles: {len(profiles)} programs, from {len(personas)} labeled students -> {PROFILE_FILE.relative_to(ROOT)}")

rows = list(csv.DictReader(open(ROOT / "eval" / "data" / "effort_labels.csv", encoding="utf-8")))
mult = deadline.learn_calibration(rows)
deadline.CALIBRATION_FILE.write_text(json.dumps({"labeled_items": len(rows), "multipliers": mult}, indent=1) + "\n",
                                     encoding="utf-8")
print(f"Effort calibration from {len(rows)} labeled items -> {deadline.CALIBRATION_FILE.relative_to(ROOT)}")
for k, v in sorted(mult.items()):
    print(f"  {k:13s} x{v}")
