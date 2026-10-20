"""BeachWell evaluation: every AI component against a simple non-AI baseline.

Run from backend/:
    python eval/evaluate.py              # offline (rules + hashed embeddings), fully reproducible
    GEMINI_API_KEY=... python eval/evaluate.py   # also scores the Gemini versions

Writes eval/results.md and eval/results.json.

Honesty notes (also printed in results.md):
  * effort_labels.csv, event_personas.json and safety_messages.csv were written by the
    prototype author as PLACEHOLDER labels. For the final report, two team members should
    re-label them independently and report their agreement.
  * Crunch detection, pace learning and the planner are measured on synthetic semesters.
"""
from __future__ import annotations

import csv
import json
import math
import os
import random
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("DB_PATH", str(Path(tempfile.mkdtemp()) / "eval.db"))
os.environ.setdefault("SEMESTER_START", "2026-08-24")

from beachwell import ical, llm, semester, seed  # noqa: E402
from beachwell.agents import deadline, events, forecast, pace, planner, safety  # noqa: E402

RNG_SEED = 2026
HEAVY = ("Heavy", "Overload")


# ------------------------------------------------------------------ A. effort estimation

def eval_effort() -> dict:
    rows = list(csv.DictReader(open(HERE / "data" / "effort_labels.csv", encoding="utf-8")))
    methods = {
        "Constant 3 h per deadline (baseline)": lambda r: ("homework", 3.0),
        "Type keyword only (baseline)": lambda r: _type_only(r["title"]),
        "BeachWell rules (title + description cues)": lambda r: (lambda e: (e.type, e.hours))(
            deadline.estimate_rules(r["title"], r["description"])),
    }
    out = {"n": len(rows), "methods": {}}
    for name, fn in methods.items():
        preds = [fn(r) for r in rows]
        out["methods"][name] = _effort_metrics(rows, preds)
    if llm.mode() == "gemini":
        ests = deadline.estimate_batch([{"title": r["title"], "course": r["course"], "description": r["description"]}
                                        for r in rows])
        out["methods"]["BeachWell + Gemini"] = _effort_metrics(rows, [(e.type, e.hours) for e in ests])
    return out


def _type_only(title: str) -> tuple[str, float]:
    t = title.lower()
    import re
    for pattern, typ, base in deadline._RULES:
        if re.search(pattern, t):
            return typ, {"exam": 6, "quiz": 1.5, "project": 8, "presentation": 5, "essay": 5, "lab": 3,
                         "homework": 3, "discussion": 1, "reading": 1.5, "admin": 0.5}[typ]
    return "homework", 3.0


def _effort_metrics(rows, preds) -> dict:
    err = [abs(float(r["hours"]) - h) for r, (_, h) in zip(rows, preds)]
    type_acc = mean(r["type"] == t for r, (t, _) in zip(rows, preds))
    major_true = [deadline.is_major(r["type"], float(r["hours"])) for r in rows]
    major_pred = [deadline.is_major(t, h) for t, h in preds]
    return {"mae_hours": round(mean(err), 2), "median_abs_error": round(sorted(err)[len(err) // 2], 2),
            "type_accuracy": round(type_acc, 3), "major_accuracy": round(mean(a == b for a, b in zip(major_true, major_pred)), 3)}


# ------------------------------------------------------------------ B. crunch-week detection

def _mk(i, title, d, kind, hours):
    return {"id": i, "title": title, "course": "SYN", "due": ical.local_dt(d, 23.98).isoformat(), "type": kind,
            "major": deadline.is_major(kind, hours), "hours": hours, "done": False}


def synthetic_semesters(n: int = 40, seed_value: int = RNG_SEED):
    """Light background workload, one planted crunch week and one decoy week of many small items."""
    rng = random.Random(seed_value)
    for _ in range(n):
        tasks, k = [], 0
        for course in range(3):
            for wk in range(2, 17):
                start = semester.week_start(wk)
                k += 1
                tasks.append(_mk(k, f"Homework {wk}", start + timedelta(days=course), "homework", rng.choice([2, 2.5, 3])))
                k += 1
                tasks.append(_mk(k, f"Reading {wk}", start + timedelta(days=3), "reading", 1.5))
        crunch = rng.randint(5, 13)
        decoy = rng.choice([w for w in range(4, 15) if abs(w - crunch) >= 3])
        cstart = semester.week_start(crunch) + timedelta(days=rng.randint(0, 2))
        for j, (title, kind, hours) in enumerate([("Project Report", "project", rng.choice([10, 12, 14])),
                                                  ("Midterm Exam", "exam", rng.choice([7, 8])),
                                                  ("Essay", "essay", rng.choice([8, 9, 10]))]):
            k += 1
            tasks.append(_mk(k, title, cstart + timedelta(days=j + rng.randint(0, 1)), kind, hours))
        dstart = semester.week_start(decoy)
        for j in range(6):
            k += 1
            tasks.append(_mk(k, f"Quiz {j}", dstart + timedelta(days=j % 5), rng.choice(["quiz", "discussion"]), 1.25))
        yield tasks, crunch, decoy


SEMESTERS_FILE = HERE / "data" / "practice_semesters.json"


def load_semesters():
    """Use the saved practice semesters (scripts/make_practice_semesters.py) so results are reproducible."""
    if SEMESTERS_FILE.exists():
        data = json.loads(SEMESTERS_FILE.read_text(encoding="utf-8"))
        return [(s["tasks"], s["crunch_week"], s["decoy_week"]) for s in data["semesters"]]
    return list(synthetic_semesters())


def eval_crunch() -> dict:
    sems = load_semesters()
    weeks = list(range(2, 17))

    def prf(pred_fn):
        tp = fp = fn = decoy_flags = 0
        for tasks, crunch, decoy in sems:
            flagged = pred_fn(tasks)
            for w in weeks:
                truth = w == crunch
                tp += truth and w in flagged
                fp += (not truth) and w in flagged
                fn += truth and w not in flagged
            decoy_flags += decoy in flagged
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r) if p + r else 0, 3),
                "decoy_weeks_flagged": f"{decoy_flags}/{len(sems)}"}

    def count_baseline(threshold):
        def fn(tasks):
            c = Counter(semester.week_of(date.fromisoformat(t["due"][:10])) for t in tasks)
            return {w for w, n in c.items() if n >= threshold}
        return fn

    best = max((prf(count_baseline(t)) | {"threshold": t} for t in range(6, 14)), key=lambda x: x["f1"])

    def ours(tasks):
        fc = forecast.forecast(tasks, semester.week_start(1), 25, None, 17)
        return {w.week for w in fc if w.level in HEAVY}

    return {"semesters": len(sems), "truth": "one planted crunch week per semester (3 major deadlines in about 4 days); "
            "every semester also has a decoy week with 6 small quizzes or posts",
            "Deadline count per week (baseline, best threshold)": best,
            "BeachWell workload score (Heavy or Overload)": prf(ours)}


# ------------------------------------------------------------------ C. personal pace learning

def eval_pace(students: int = 40) -> dict:
    rng = random.Random(RNG_SEED)
    courses = ["CECS 458", "MATH 380", "ENGL 317", "BIOL 211", "FIN 300", "PSY 100", "ART 130", "KIN 301"]
    errs = defaultdict(lambda: {"first_half": [], "second_half": []})
    for _ in range(students):
        student = math.exp(rng.gauss(0, 0.2))
        by_type = {t: student * math.exp(rng.gauss(0, 0.3)) for t in deadline.TYPES}
        items = []
        for c in rng.sample(courses, 5):
            for it in seed.course_items(c):
                e = deadline.estimate_rules(it.title, it.description)
                items.append((seed.item_due(it), e.type, e.hours))
        items.sort()
        history = []
        for due, kind, est in items:
            actual = est * by_type[kind] * math.exp(rng.gauss(0, 0.15))
            half = "first_half" if semester.week_of(due.date()) <= 8 else "second_half"
            model = pace.fit(history)
            preds = {"No personal pace (baseline)": est,
                     "One overall multiplier": est * model.global_mult,
                     "BeachWell pace model (per type, shrunk)": est * model.multiplier(kind)}
            for name, p in preds.items():
                errs[name][half].append(abs(actual - p))
            if rng.random() < 0.7:  # students log about 70% of tasks
                history.append((kind, est, actual))
    return {"students": students, "methods": {k: {h: round(mean(v), 2) for h, v in d.items()} for k, d in errs.items()}}


# ------------------------------------------------------------------ D. planner

def eval_planner(students: int = 20) -> dict:
    rng = random.Random(RNG_SEED)
    start = semester.week_start(1)
    viol = scheduled = total = 0
    peaks_before, peaks_after, over_before, over_after = [], [], [], []
    for s in range(students):
        college = rng.choice(list(seed.COLLEGES))
        courses = rng.sample(seed.COLLEGES[college], 3) + rng.sample(seed.GE_COURSES, 2)
        tasks, k = [], 0
        for c in dict.fromkeys(courses):
            for it in seed.course_items(c):
                e = deadline.estimate_rules(it.title, it.description)
                k += 1
                tasks.append({"id": k, "title": it.title, "course": c, "due": seed.item_due(it).isoformat(),
                              "hours": e.hours, "type": e.type, "major": e.major, "done": False})
        classes = [{"course": f"C{i}", "weekday": d, "start_hour": h, "end_hour": h + 1.25}
                   for i, (d, h) in enumerate(rng.sample([(d, h) for d in range(5) for h in (8, 9.5, 11, 13, 14.5, 16, 17.5)], 9))]
        out = planner.plan(tasks, classes, start, daily_cap=5, weekly_capacity=25)
        viol += len(planner.check_constraints(out, tasks, classes, 5))
        total += sum(t["hours"] for t in tasks)
        scheduled += sum(b["hours"] for b in out["blocks"])
        before = forecast.forecast(tasks, start, 25, None, 17)
        after = forecast.forecast(tasks, start, 25, None, 17, plan_days=out["days"])
        peaks_before.append(max(w.hours for w in before))
        peaks_after.append(max(w.hours for w in after))
        over_before.append(sum(w.level == "Overload" for w in before))
        over_after.append(sum(w.level == "Overload" for w in after))
    return {"students": students, "rule_violations": viol, "share_of_hours_scheduled": round(scheduled / total, 3),
            "peak_week_hours": {"default_schedule": round(mean(peaks_before), 1), "with_plan": round(mean(peaks_after), 1)},
            "overload_weeks_per_student": {"default_schedule": round(mean(over_before), 2),
                                           "with_plan": round(mean(over_after), 2)}}


# ------------------------------------------------------------------ E. event recommendations

def eval_events() -> dict:
    personas = json.load(open(HERE / "data" / "event_personas.json", encoding="utf-8"))
    wk_start, wk_end = semester.week_range(9)
    pool, seen = [], set()
    for e in seed.build_events():
        d = e["start"][:10]
        if wk_start.isoformat() <= d <= wk_end.isoformat() and e["series"] not in seen:
            seen.add(e["series"])
            pool.append(e)
    freq = Counter(e["series"] for e in seed.build_events())
    rng = random.Random(RNG_SEED)

    def keyword(interests):
        said = set(llm._TOKEN_RE.findall(interests.lower()))
        return sorted(pool, key=lambda e: -len(said & set(llm._TOKEN_RE.findall(events._event_text(e).lower()))))

    methods = {
        "Random (baseline, expected)": None,
        "Most frequent programs (popularity baseline)": lambda i: sorted(pool, key=lambda e: -freq[e["series"]]),
        "Keyword overlap (baseline)": keyword,
        "BeachWell offline (hashed embeddings + rules)": lambda i: [e for _, e in events.score_events(i, pool)],
    }
    out = {"personas": len(personas), "pool": len(pool), "methods": {}}
    for name, fn in methods.items():
        p3, hit1 = [], []
        for per in personas:
            gold = set(per["gold"])
            if fn is None:
                p3.append(len(gold & seen) / len(pool))
                hit1.append(len(gold & seen) / len(pool))
                continue
            ranked = [e["series"] for e in fn(per["interests"])]
            p3.append(len(set(ranked[:3]) & gold) / 3)
            hit1.append(float(bool(ranked) and ranked[0] in gold))
        out["methods"][name] = {"precision_at_3": round(mean(p3), 3), "hit_at_1": round(mean(hit1), 3)}
    if llm.mode() == "gemini":
        p3, hit1 = [], []
        for per in personas:
            ranked = [e for _, e in events.score_events(per["interests"], pool)]
            week = {"week": 9, "level": "Overload", "reasons": ["3 major deadlines within 4 days"], "label": ""}
            picks = events._rerank_online(per["interests"], week, [(0, e) for e in ranked[:8]]) or []
            ids = [p["id"] for p in picks]
            series = [next(e["series"] for e in pool if e["id"] == i) for i in ids]
            p3.append(len(set(series[:3]) & set(per["gold"])) / 3)
            hit1.append(float(bool(series) and series[0] in per["gold"]))
        out["methods"]["BeachWell + Gemini (embeddings and re-ranking)"] = {"precision_at_3": round(mean(p3), 3),
                                                                            "hit_at_1": round(mean(hit1), 3)}
    _ = rng
    return out


# ------------------------------------------------------------------ F. safety

def eval_safety() -> dict:
    rows = list(csv.DictReader(open(HERE / "data" / "safety_messages.csv", encoding="utf-8")))
    crisis = [r["text"] for r in rows if r["label"] == "crisis"]
    ok = [r["text"] for r in rows if r["label"] == "ok"]
    res = {"messages": len(rows), "crisis": len(crisis), "ok": len(ok), "methods": {}}
    res["methods"]["Rules only"] = {
        "crisis_recall": round(mean(safety.rules_flag(t) for t in crisis), 3),
        "false_alarm_rate": round(mean(safety.rules_flag(t) for t in ok), 3),
        "missed": [t for t in crisis if not safety.rules_flag(t)],
    }
    fresh = HERE.parent / "labeling" / "safety_messages_team.csv"
    if fresh.exists():
        frows = [r for r in csv.DictReader(open(fresh, encoding="utf-8-sig")) if r.get("text", "").strip()]
        fc = [r["text"] for r in frows if r["label"].strip().lower() == "crisis"]
        fo = [r["text"] for r in frows if r["label"].strip().lower() == "ok"]
        if fc and fo:
            res["methods"]["Rules only, team-written unseen set"] = {
                "crisis_recall": round(mean(safety.rules_flag(t) for t in fc), 3),
                "false_alarm_rate": round(mean(safety.rules_flag(t) for t in fo), 3),
                "missed": [t for t in fc if not safety.rules_flag(t)],
            }
    if llm.mode() == "gemini":
        flags_c = [safety.check(t)["level"] == "crisis" for t in crisis]
        flags_o = [safety.check(t)["level"] == "crisis" for t in ok]
        res["methods"]["Rules + Gemini"] = {"crisis_recall": round(mean(flags_c), 3),
                                            "false_alarm_rate": round(mean(flags_o), 3),
                                            "missed": [t for t, f in zip(crisis, flags_c) if not f]}
    return res


# ------------------------------------------------------------------ report

def _table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def main() -> None:
    results = {"mode": llm.mode(), "effort": eval_effort(), "crunch": eval_crunch(), "pace": eval_pace(),
               "planner": eval_planner(), "events": eval_events(), "safety": eval_safety()}
    (HERE / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    e, c, p, pl, ev, sf = (results[k] for k in ("effort", "crunch", "pace", "planner", "events", "safety"))
    md = [f"# BeachWell evaluation results\n\nMode: **{results['mode']}** "
          f"({'Gemini models' if results['mode'] == 'gemini' else 'no API key; rules and hashed embeddings'}). "
          "Re-run with `python eval/evaluate.py`.\n",
          "> Labels in `eval/data/` are placeholders written by the prototype author. Before the final report, "
          "two team members should re-label them independently and report agreement. Crunch detection, pace "
          "learning and the planner use synthetic semesters.\n",
          f"## A. Effort estimation ({e['n']} labeled Canvas items)\n",
          _table(["Method", "Mean abs. error (h)", "Median abs. error (h)", "Type accuracy", "Major-deadline accuracy"],
                 [[k, v["mae_hours"], v["median_abs_error"], v["type_accuracy"], v["major_accuracy"]]
                  for k, v in e["methods"].items()]),
          f"\n## B. Finding crunch weeks ({c['semesters']} synthetic semesters)\n\nGround truth: {c['truth']}.\n",
          _table(["Method", "Precision", "Recall", "F1", "Decoy weeks flagged"],
                 [[k, v["precision"], v["recall"], v["f1"], v["decoy_weeks_flagged"]]
                  for k, v in c.items() if isinstance(v, dict)]),
          f"\n## C. Learning a student's pace ({p['students']} simulated students, 70% of tasks logged)\n\n"
          "Mean absolute error of hour predictions, weeks 1 to 8 versus weeks 9 to 17.\n",
          _table(["Method", "Weeks 1-8 (h)", "Weeks 9-17 (h)"],
                 [[k, v["first_half"], v["second_half"]] for k, v in p["methods"].items()]),
          f"\n## D. Planner ({pl['students']} synthetic students, whole semester)\n",
          _table(["Measure", "Default schedule", "With BeachWell plan"],
                 [["Peak week (hours of work)", pl["peak_week_hours"]["default_schedule"], pl["peak_week_hours"]["with_plan"]],
                  ["Overload weeks per student", pl["overload_weeks_per_student"]["default_schedule"],
                   pl["overload_weeks_per_student"]["with_plan"]]]),
          f"\nRule violations across all plans: **{pl['rule_violations']}**. Share of estimated hours placed in "
          f"study blocks: **{round(pl['share_of_hours_scheduled'] * 100)}%** (the rest did not fit before its due time).\n",
          f"## E. Event recommendations ({ev['personas']} personas, {ev['pool']} programs in one week)\n",
          _table(["Method", "Precision@3", "Hit@1"],
                 [[k, v["precision_at_3"], v["hit_at_1"]] for k, v in ev["methods"].items()]),
          f"\n## F. Safety screen ({sf['crisis']} help-needed and {sf['ok']} everyday-stress messages)\n\n"
          "The rules were revised after a first run on this set (crisis recall rose from 0.71 to 1.0), so these "
          "numbers are optimistic. Measure again on a fresh, team-written set before quoting them.\n",
          _table(["Method", "Crisis recall", "False-alarm rate", "Missed"],
                 [[k, v["crisis_recall"], v["false_alarm_rate"], "; ".join(v["missed"]) or "none"]
                  for k, v in sf["methods"].items()]),
          ]
    (HERE / "results.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
