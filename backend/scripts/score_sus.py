"""Score the classmate usability survey.

Reads usability/sus_responses.csv (one row per participant) and writes usability/sus_results.md.

SUS scoring (Brooke, 1996): for odd items subtract 1 from the answer, for even items
subtract the answer from 5, add the ten results and multiply by 2.5. That gives a score
from 0 to 100 for each person; we report the average.

Usage (from backend/):  python scripts/score_sus.py [path/to/responses.csv]
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT = ROOT / "usability" / "sus_responses.csv"


def sus_score(answers: list[int]) -> float:
    if len(answers) != 10 or any(a < 1 or a > 5 for a in answers):
        raise ValueError("SUS needs ten answers from 1 to 5")
    return 2.5 * sum((a - 1) if i % 2 == 0 else (5 - a) for i, a in enumerate(answers))


def main(path: Path) -> int:
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8-sig")) if r.get("participant", "").strip()]
    if not rows:
        print(f"No responses yet in {path}. Add one row per participant, then run this again.")
        return 1
    scores, problems = [], []
    for r in rows:
        try:
            scores.append(sus_score([int(r[f"q{i}"]) for i in range(1, 11)]))
        except (ValueError, KeyError) as exc:
            problems.append(f"{r.get('participant', '?')}: {exc}")
    if problems:
        print("Fix these rows first:", *problems, sep="\n  ")
        return 1

    def share(col: str) -> str:
        vals = [r.get(col, "").strip().lower() for r in rows]
        yes = sum(v == "yes" for v in vals)
        maybe = sum(v == "maybe" for v in vals)
        return f"{yes}/{len(vals)} yes, {maybe} maybe"

    sd = f", standard deviation {stdev(scores):.1f}" if len(scores) > 1 else ""
    lines = ["# Usability test results", "",
             f"- Participants: {len(scores)}",
             f"- Average SUS score: **{mean(scores):.1f}** out of 100 (range {min(scores):.0f}–{max(scores):.0f}{sd}). "
             "About 68 is average for software.",
             f"- Would follow a plan like this during midterms: {share('would_follow_plan')}",
             f"- Would go to a suggested event: {share('would_attend_event')}", "",
             "## Comments", ""]
    for r in rows:
        for col, label in (("favorite_part", "Liked"), ("most_confusing_part", "Confusing")):
            if r.get(col, "").strip():
                lines.append(f"- {r['participant']} ({label.lower()}): {r[col].strip()}")
    out = path.parent / "sus_results.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nSaved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT))
