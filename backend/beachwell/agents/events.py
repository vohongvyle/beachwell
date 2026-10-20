"""Event Recommender: campus de-stress events that fit a student's heavy weeks and free time.

Pipeline for each Heavy or Overload week:
  1. Candidates = posted events that week + "expected" events projected from past
     semesters (a recurring series, e.g. finals-week activities, that has not been posted yet).
  2. Time-fit filter: the event must not overlap a class or a planned study block.
  3. Score = cosine similarity(student interests, event text)
             + 0.10 if it is a de-stress event, + 0.05 if it is short,
             - 0.15 for big crowds when the student says they dislike crowds,
             - 0.05 if it is only "expected".
  4. Online, Gemini re-ranks the top 8 and writes the one-line reasons; offline,
     reasons come from a template built from the matched terms and the free slot.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

from .. import llm, semester
from ..ical import LOCAL_TZ

# Approximate start dates of past terms, used only to project recurring events into
# the current term by week number. Placeholders: check against the CSULB calendar.
PAST_TERMS = {"Fall 2025": date(2025, 8, 25), "Spring 2026": date(2026, 1, 19)}

CROWD_AVERSE = re.compile(r"\b(hate|avoid|dislike|not into|don'?t like|no)\s+(big\s+|large\s+)?crowds?\b|\bintrovert|\bquiet\b",
                          re.IGNORECASE)


def _term_start_for(d: date) -> date:
    starts = sorted(list(PAST_TERMS.values()) + [semester.semester_start()])
    best = starts[0]
    for s in starts:
        if s <= d:
            best = s
    return best - timedelta(days=best.weekday())


def project_expected(events: list[dict], today: date) -> list[dict]:
    """Project recurring past-term events into the current term (marked expected=True)."""
    cur_start = semester.semester_start()
    posted = {(e["series"], semester.week_of(datetime.fromisoformat(e["start"]).date()))
              for e in events if e["series"] and datetime.fromisoformat(e["start"]).date() >= cur_start}
    projected: dict[tuple[str, int, int], dict] = {}
    for e in events:
        if not e["series"]:
            continue
        s = datetime.fromisoformat(e["start"])
        if s.date() >= cur_start:
            continue
        term0 = _term_start_for(s.date())
        offset = s.date() - term0
        new_day = cur_start + offset
        if new_day < today:
            continue
        wk = semester.week_of(new_day)
        if (e["series"], wk) in posted:
            continue
        key = (e["series"], wk, new_day.weekday())
        delta = datetime.combine(new_day, s.timetz()) - s
        projected[key] = {
            **e,
            "id": f"{e['id']}~expected",
            "start": (s + delta).isoformat(),
            "end": (datetime.fromisoformat(e["end"]) + delta).isoformat(),
            "expected": True,
        }
    return list(projected.values())


def _overlaps(a0: float, a1: float, b0: float, b1: float) -> bool:
    return a0 < b1 and b0 < a1


def _window_free(h0: float, h1: float, busy: list[tuple[float, float]]) -> bool:
    return not any(_overlaps(h0, h1, b0, b1) for b0, b1 in busy)


def fits_free_time(ev: dict, classes: list[dict], blocks: list[dict]) -> bool:
    """Short events must fit whole. Drop-in events longer than 90 minutes need any free 45 minutes inside them."""
    s, e = datetime.fromisoformat(ev["start"]), datetime.fromisoformat(ev["end"])
    h0, h1 = s.hour + s.minute / 60, e.hour + e.minute / 60
    busy = [(c["start_hour"], c["end_hour"]) for c in classes if c["weekday"] == s.weekday()]
    busy += [(b["start_hour"], b["end_hour"]) for b in blocks if b["day"] == s.date().isoformat()]
    if h1 - h0 <= 1.5:
        return _window_free(h0, h1, busy)
    t = h0
    while t + 0.75 <= h1 + 1e-9:
        if _window_free(t, t + 0.75, busy):
            return True
        t += 0.25
    return False


def _fmt_time(dt: datetime) -> str:
    h = dt.hour % 12 or 12
    return f"{h}:{dt.minute:02d} {'am' if dt.hour < 12 else 'pm'}" if dt.minute else f"{h} {'am' if dt.hour < 12 else 'pm'}"


def slot_text(ev: dict) -> str:
    s, e = datetime.fromisoformat(ev["start"]), datetime.fromisoformat(ev["end"])
    return f"{s.strftime('%a %b')} {s.day}, {_fmt_time(s)}–{_fmt_time(e)}"


def _event_text(ev: dict) -> str:
    return f"{ev['title']}. {ev['description']} Tags: {ev['tags'].replace(',', ', ')}"


def score_events(interests: str, candidates: list[dict]) -> list[tuple[float, dict]]:
    if not candidates:
        return []
    query = (interests or "") + " take a break, relax, recharge, stress relief"
    vecs = llm.embed([query] + [_event_text(e) for e in candidates])
    sims = vecs[1:] @ vecs[0]
    crowd_averse = bool(CROWD_AVERSE.search(interests or ""))
    said = set(_said_words(interests))
    scored = []
    for sim, ev in zip(sims, candidates):
        tags = set(ev["tags"].split(","))
        if crowd_averse and "large-crowd" in tags and not _mentioned(ev, interests):
            continue  # respect a stated dislike unless the event matches something they asked for
        s, e = datetime.fromisoformat(ev["start"]), datetime.fromisoformat(ev["end"])
        # hybrid retrieval: semantic similarity plus a small bonus for words the student literally wrote
        overlap = len(said & {_stem(t) for t in llm._TOKEN_RE.findall(_event_text(ev).lower())})
        bonus = 0.06 * min(overlap, 3) + 0.10 * ("destress" in tags) + 0.05 * ((e - s) <= timedelta(hours=1.5))
        bonus -= 0.15 * (crowd_averse and "large-crowd" in tags)
        bonus -= 0.05 * bool(ev.get("expected"))
        scored.append((float(sim) + bonus, ev))
    scored.sort(key=lambda x: -x[0])
    return scored


def _stem(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


_NOT_INTERESTS = {"crowd", "crowds", "hate", "drain", "drains", "rather", "something", "make", "outside", "major",
                  "love", "dislike", "avoid", "would", "being", "doing", "people", "things", "lots"}


def _said_words(interests: str) -> list[str]:
    return [_stem(w) for w in llm._TOKEN_RE.findall((interests or "").lower())
            if w not in llm._STOP and w not in _NOT_INTERESTS and len(w) > 3]


def _mentioned(ev: dict, interests: str) -> list[str]:
    """Words the student actually wrote (no synonyms) that this event covers."""
    event_words = {_stem(t) for t in llm._TOKEN_RE.findall(_event_text(ev).lower())}
    return [w for w in dict.fromkeys(_said_words(interests)) if w in event_words]


def _template_reason(ev: dict, interests: str, week: dict) -> str:
    said = _mentioned(ev, interests)
    lead = f"You mentioned {' and '.join(said[:2])}" if said else "A low-effort way to reset"
    text = f"{lead}; it fits a free slot on {slot_text(ev)}"
    if week["level"] == "Overload":
        text += f", right in your overload week {week['week']}"
    if ev.get("expected"):
        text += ". Not posted yet: it ran at this point in past semesters"
    return text + "."


RERANK_PROMPT = """You recommend campus de-stress events to a stressed college student.
Student interests and preferences: {interests}
Their week: {level}, because {reasons}.
Pick the 3 events that would help this student recharge most, respecting stated dislikes.
For each, write one friendly sentence (max 22 words) explaining why it fits them.
Return JSON: [{{"id": "...", "reason": "..."}}] using ids from this list:
{events}"""


def recommend(interests: str, weeks: list[dict], events: list[dict], classes: list[dict], blocks: list[dict],
              today: date, per_week: int = 3) -> list[dict]:
    """weeks: forecast dicts. Returns [{week, level, picks: [...]}] for Heavy/Overload weeks (or this week)."""
    now = datetime.combine(today, datetime.min.time(), LOCAL_TZ)
    pool = [e for e in events if datetime.fromisoformat(e["start"]) >= now] + project_expected(events, today)
    heavy = [w for w in weeks if w["level"] in ("Heavy", "Overload")] or weeks[:1]
    out = []
    shown: dict[str, int] = {}  # series already suggested in earlier weeks -> times
    for w in heavy:
        start, end = date.fromisoformat(w["start"]), date.fromisoformat(w["end"])
        cands = [e for e in pool if start <= datetime.fromisoformat(e["start"]).date() <= end
                 and fits_free_time(e, classes, blocks)]
        ranked = sorted(((sc - 0.06 * shown.get(ev["series"] or ev["id"], 0), ev)
                         for sc, ev in score_events(interests, cands)), key=lambda x: -x[0])
        seen_series, top = set(), []
        for score, ev in ranked:
            key = ev["series"] or ev["id"]
            if key in seen_series:
                continue
            seen_series.add(key)
            top.append((score, ev))
            if len(top) >= 8:
                break
        picks = _rerank_online(interests, w, top[:8]) or [
            {**_public(ev), "score": round(sc, 3), "reason": _template_reason(ev, interests, w), "by": "rules"}
            for sc, ev in top[:per_week]
        ]
        for pk in picks[:per_week]:
            key = next((ev["series"] or ev["id"] for _, ev in top if ev["id"] == pk["id"]), pk["id"])
            shown[key] = shown.get(key, 0) + 1
        out.append({"week": w["week"], "label": w["label"], "level": w["level"], "picks": picks[:per_week]})
    return out


def _public(ev: dict) -> dict:
    return {k: ev[k] for k in ("id", "title", "organizer", "description", "location", "start", "end", "source_url")} | {
        "tags": ev["tags"].split(","), "expected": bool(ev.get("expected")), "is_sample": bool(ev.get("is_sample", 1)),
        "when": slot_text(ev)}


def _rerank_online(interests: str, week: dict, top: list[tuple[float, dict]]) -> list[dict] | None:
    if llm.mode() == "offline" or not top:
        return None
    listing = "\n".join(json.dumps({"id": ev["id"], "title": ev["title"], "when": slot_text(ev),
                                    "description": ev["description"][:200], "tags": ev["tags"]}) for _, ev in top)
    answer = llm.generate_json(RERANK_PROMPT.format(interests=interests or "not given", level=week["level"],
                                                    reasons="; ".join(week["reasons"]), events=listing),
                               name="events.rerank")
    if not isinstance(answer, list):
        return None
    by_id = {ev["id"]: (sc, ev) for sc, ev in top}
    picks = []
    for a in answer:
        if isinstance(a, dict) and a.get("id") in by_id:
            sc, ev = by_id[a["id"]]
            picks.append({**_public(ev), "score": round(sc, 3), "reason": str(a.get("reason", ""))[:200], "by": "gemini"})
    return picks or None

