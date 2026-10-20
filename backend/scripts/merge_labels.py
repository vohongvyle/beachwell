"""Combine Vy's and Deborah's labels, measure how well they agree, and write the final test labels.

Each person fills in their own sheets in labeling/ WITHOUT looking at the other's:
    labeling/effort_labels_vy.csv        labeling/effort_labels_deborah.csv
    labeling/persona_labels_vy.csv       labeling/persona_labels_deborah.csv

Then run (from backend/):
    python scripts/merge_labels.py

It writes:
    eval/data/effort_labels.csv     final hours = average of the two; type = agreed type
                                    (disagreements are listed so you can settle them together)
    eval/data/event_personas.json   gold events = every event either person picked
    labeling/agreement_report.md    the agreement numbers to quote in the report
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
import os
LAB = Path(os.environ.get("LABELING_DIR", ROOT / "labeling"))
OUT = Path(os.environ.get("LABEL_OUT_DIR", ROOT / "eval" / "data"))
TYPES = ["exam", "quiz", "project", "presentation", "essay", "lab", "homework", "discussion", "reading", "admin"]


def read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Agreement beyond chance for two raters' category labels (1 = perfect, 0 = chance)."""
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def pearson(x: list[float], y: list[float]) -> float:
    mx, my = mean(x), mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = (sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)) ** 0.5
    return num / den if den else 1.0


def merge_effort() -> tuple[list[str], list[str]]:
    a, b = read(LAB / "effort_labels_vy.csv"), read(LAB / "effort_labels_deborah.csv")
    problems, report = [], []
    if len(a) != len(b):
        sys.exit("The two effort sheets have a different number of rows.")
    rows, disagree = [], []
    ha, hb, ta, tb = [], [], [], []
    for x, y in zip(a, b):
        for who, r in (("Vy", x), ("Deborah", y)):
            if r["type"].strip().lower() not in TYPES:
                problems.append(f"effort item {r['item_id']} ({who}): type must be one of {', '.join(TYPES)}")
            try:
                float(r["hours"])
            except ValueError:
                problems.append(f"effort item {r['item_id']} ({who}): hours is missing or not a number")
    if problems:
        return problems, report
    for x, y in zip(a, b):
        t1, t2 = x["type"].strip().lower(), y["type"].strip().lower()
        h1, h2 = float(x["hours"]), float(y["hours"])
        ha.append(h1); hb.append(h2); ta.append(t1); tb.append(t2)
        if t1 != t2:
            disagree.append(f"| {x['item_id']} | {x['title']} | {t1} | {t2} |")
        rows.append({"title": x["title"], "course": x["course"], "description": x["description"],
                     "type": t1, "hours": round((h1 + h2) / 2, 2)})
    with open(OUT / "effort_labels.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["title", "course", "description", "type", "hours"])
        w.writeheader(); w.writerows(rows)
    gap = [abs(p - q) for p, q in zip(ha, hb)]
    report += ["## Time estimates", "",
               f"- Items labeled: {len(rows)}",
               f"- Type agreement: {sum(p == q for p, q in zip(ta, tb))}/{len(rows)} items, Cohen's kappa = {cohen_kappa(ta, tb):.2f}",
               f"- Hours: average difference between the two of us = {mean(gap):.2f} h; correlation = {pearson(ha, hb):.2f}",
               "- Final hours = average of both estimates. Where types differ, Vy's type was kept; settle these together:", ""]
    report += (["| # | Title | Vy | Deborah |", "| --- | --- | --- | --- |"] + disagree) if disagree else ["None."]
    return problems, report + [""]


def merge_personas() -> tuple[list[str], list[str]]:
    a, b = read(LAB / "persona_labels_vy.csv"), read(LAB / "persona_labels_deborah.csv")
    valid = {r["series_id"] for r in read(LAB / "event_choices.csv")}
    problems, out, overlaps, top1 = [], [], [], []
    for x, y in zip(a, b):
        picks = []
        for who, r in (("Vy", x), ("Deborah", y)):
            p = [r[f"best_event_{k}"].strip() for k in (1, 2, 3) if r[f"best_event_{k}"].strip()]
            bad = [e for e in p if e not in valid]
            if not p:
                problems.append(f"persona {r['persona_id']} ({who}): pick at least one event")
            if bad:
                problems.append(f"persona {r['persona_id']} ({who}): unknown event id {', '.join(bad)} (see event_choices.csv)")
            picks.append(p)
        if problems:
            continue
        s1, s2 = set(picks[0]), set(picks[1])
        overlaps.append(len(s1 & s2) / len(s1 | s2))
        top1.append(picks[0][0] in s2 or picks[1][0] in s1)
        out.append({"interests": x["what_helps_this_student_recharge"], "gold": list(dict.fromkeys(picks[0] + picks[1]))})
    if problems:
        return problems, []
    json.dump(out, open(OUT / "event_personas.json", "w", encoding="utf-8"), indent=1)
    return [], ["## Event picks for sample students", "",
                f"- Personas labeled: {len(out)}",
                f"- Overlap between our picks (Jaccard, 0 to 1): {mean(overlaps):.2f}",
                f"- Each person's first choice was also picked by the other: {sum(top1)}/{len(top1)}",
                "- Gold set = every event either of us picked.", ""]


if __name__ == "__main__":
    p1, r1 = merge_effort()
    p2, r2 = merge_personas()
    if p1 or p2:
        problems = p1 + p2
        print(f"Not ready yet: {len(problems)} cells still need a value. Nothing was written.")
        for p in problems[:12]:
            print("  -", p)
        if len(problems) > 12:
            print(f"  ... and {len(problems) - 12} more. Fill in every row of your sheets in labeling/.")
        sys.exit(1)
    report = ["# Labeling agreement", "", "Vy and Deborah labeled the same items independently.", ""] + r1 + r2
    (LAB / "agreement_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print("Final labels written to eval/data/. Now run: python eval/evaluate.py")
