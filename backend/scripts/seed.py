"""Create the SQLite database with sample data.

Usage (from backend/):
    python scripts/seed.py            # seed if the database is empty
    python scripts/seed.py --reset    # wipe and reseed
    python scripts/seed.py --reset --llm   # also estimate the demo student's deadlines with Gemini
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beachwell.seed import seed  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="delete the database first")
    ap.add_argument("--cohort", type=int, default=420, help="synthetic students for the Campus Radar")
    ap.add_argument("--llm", action="store_true", help="use Gemini for the demo student's estimates")
    args = ap.parse_args()
    print(json.dumps(seed(reset=args.reset, cohort_size=args.cohort, use_llm=args.llm), indent=2))
