"""Deadline Agent: classify each Canvas item and estimate the hours it takes.

Online, Gemini reads the title and description (few-shot, JSON output) in one batched
call. Offline, or if Gemini fails, a rule-based estimator uses title cues, page counts
and point values. Students can always correct an estimate in the app; those
corrections feed the personal pace model (agents/pace.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .. import llm

TYPES = ["exam", "quiz", "project", "presentation", "essay", "lab", "homework", "discussion", "reading", "admin"]
MAJOR_TYPES = {"exam", "project", "presentation", "essay"}

# Days before the due date that work on each type normally starts. Used by the
# forecast (to spread hours) and the planner (as the default window).
LEAD_DAYS = {
    "exam": 5, "project": 10, "presentation": 5, "essay": 7, "lab": 3,
    "homework": 3, "quiz": 2, "discussion": 1, "reading": 2, "admin": 1,
}


@dataclass
class Estimate:
    type: str
    hours: float
    major: bool
    source: str  # "gemini" or "rules"
    reason: str = ""


_RULES: list[tuple[str, str, float]] = [
    # (regex on lower-cased title, type, base hours). First match wins, so order matters.
    (r"\bfinal (exam|examination)\b|\bfinals?\b.*\bexam\b", "exam", 10.0),
    (r"\b(midterm|mid-term)\b", "exam", 7.0),
    (r"\b(exam|test)\b", "exam", 6.0),
    (r"\bquiz(zes)?\b", "quiz", 1.5),
    (r"\b(final|capstone) (project|report|deliverable|prototype)\b", "project", 14.0),
    (r"\b(presentation|pitch|demo day|poster session|demo video|video pitch)\b", "presentation", 5.0),
    (r"\b(milestone|proposal|checkpoint|progress report|status report|phase \d)\b", "project", 6.0),
    (r"\bproject\b", "project", 8.0),
    (r"\blab report\b", "lab", 4.0),
    (r"\breading (response|reflection|quiz|notes)\b", "reading", 1.5),
    (r"\b(research paper|term paper|final paper|final essay)\b", "essay", 10.0),
    (r"\b(reflection|response|journal|summary|annotation|annotated)\b", "essay", 2.0),
    (r"\b(essay|paper|write-?up|report|draft|thesis|analysis)\b", "essay", 5.0),
    (r"\blab\b", "lab", 3.0),
    (r"\b(discussion|post|reply|forum|comment)\b", "discussion", 1.0),
    (r"\b(reading|read ch|read chapter|chapters?)\b", "reading", 1.5),
    (r"\b(homework|hw|problem set|pset|assignment|exercise|worksheet|practice)\b", "homework", 3.0),
    (r"\b(survey|syllabus|attendance|check-?in|sign[- ]?up|introduce yourself|intro)\b", "admin", 0.5),
]


def is_major(kind: str, hours: float) -> bool:
    """Exams, projects and presentations always count; essays only when they are substantial."""
    return kind in {"exam", "project", "presentation"} or (kind == "essay" and hours >= 4)


def estimate_rules(title: str, description: str = "") -> Estimate:
    t = title.lower()
    kind, hours, why = "homework", 2.5, "no clear cue, default homework estimate"
    for pattern, typ, base in _RULES:
        if re.search(pattern, t):
            kind, hours, why = typ, base, f"title matches '{typ}'"
            break
    text = f"{title} {description}".lower()
    pages = re.search(r"(\d{1,2})\s*(?:-|to|–)\s*(\d{1,2})\s*pages?|(\d{1,2})\s*pages?", text)
    if pages and kind in ("essay", "project", "homework"):
        n = int(pages.group(2) or pages.group(3))
        hours = max(hours, round(1.1 * n, 1))
        why += f"; about {n} pages"
    pts = re.search(r"(\d{2,4})\s*(?:pts|points)\b", text)
    if pts and int(pts.group(1)) >= 100 and kind not in ("exam", "admin"):
        hours = round(hours * 1.3, 1)
        why += f"; worth {pts.group(1)} points"
    return Estimate(kind, hours, is_major(kind, hours), "rules", why)


PROMPT = """You estimate student workload for a study-planning app at a U.S. public university.
For each Canvas calendar item, return its type and the realistic number of hours an average
undergraduate spends on it (for exams: total preparation hours). Use the description when present.
Types: {types}. "major" is true for exams, projects, presentations and essays of 4+ hours.

Examples:
{{"title": "Quiz 3", "course": "MATH 122"}} -> {{"type": "quiz", "hours": 1.5, "major": false, "reason": "short weekly quiz"}}
{{"title": "Final Project Report (10-12 pages)", "course": "CECS 458"}} -> {{"type": "project", "hours": 15, "major": true, "reason": "long final report"}}
{{"title": "Discussion: Week 7 reply", "course": "PSY 100"}} -> {{"type": "discussion", "hours": 1, "major": false, "reason": "short forum post"}}
{{"title": "Midterm Exam", "course": "BIOL 211"}} -> {{"type": "exam", "hours": 8, "major": true, "reason": "midterm prep in a lab science"}}

Return a JSON list with one object per item, in the same order, with keys type, hours, major, reason.
Items:
{items}"""


def estimate_batch(items: list[dict]) -> list[Estimate]:
    """items: dicts with title, course and description. Returns one Estimate per item."""
    if not items:
        return []
    rules = [estimate_rules(i["title"], i.get("description", "")) for i in items]
    results: list[Estimate] = list(rules)
    for start in range(0, len(items), 40):
        chunk = items[start:start + 40]
        payload = "\n".join(
            json.dumps({"title": i["title"], "course": i.get("course", ""), "description": i.get("description", "")[:300]})
            for i in chunk
        )
        answer = llm.generate_json(PROMPT.format(types=", ".join(TYPES), items=payload), name="deadline.estimate")
        if not isinstance(answer, list) or len(answer) != len(chunk):
            continue  # keep rule-based estimates for this chunk
        for offset, a in enumerate(answer):
            try:
                kind = a["type"] if a["type"] in TYPES else rules[start + offset].type
                hours = min(max(float(a["hours"]), 0.25), 40.0)
                results[start + offset] = Estimate(kind, round(hours, 1), is_major(kind, hours),
                                                   "gemini", str(a.get("reason", ""))[:160])
            except (KeyError, TypeError, ValueError):
                pass
    return results
