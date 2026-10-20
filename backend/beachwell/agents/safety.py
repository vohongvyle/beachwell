"""Safety Agent: runs on every piece of free text before anything else.

Recall comes first: a message is routed to help if the rules OR (online) Gemini flag it.
The response shown to the student is fixed text written and reviewed by people; the
LLM never writes a crisis response. Everyday exaggerations ("this exam is killing me")
are deliberately not matched by the rules.
"""
from __future__ import annotations

import re

from .. import llm

CRISIS_PATTERNS = [
    r"\bkill(ing)? myself\b", r"\bend (my|it all|my own) li(fe|ves)\b", r"\bend(ed|ing)? it all\b",
    r"\bend(ing)? it\b(?! (with|for|on|early|soon|there|here|now))(?=\s*(all|$|\.|,|permanently|tonight|forever))",
    r"\b(want|wants|wanted) (it all|everything) to end\b", r"\bwanna die\b",
    r"\bthinking about ending it\b", r"\bnever wake up\b", r"\b(point|reason) (of|in|to) (living|live|being alive)\b",
    r"\b(isn'?t|is not|not) worth living\b", r"\bbetter off (if i|without me)\b",
    r"\bself[- ]?harm(ing)?\b", r"\bharming myself\b",
    r"\btake my (own )?life\b", r"\bsuicid(e|al)\b", r"\b(want|wanna|wish|going) to die\b",
    r"\bwish i (was|were) dead\b", r"\bbetter off dead\b", r"\b(don'?t|do not) want to (live|be alive|exist|wake up)\b",
    r"\bno (reason|point) (to|in) (live|living|go on|going on)\b", r"\bnot worth living\b",
    r"\b(hurt|harm|cut|cutting|hurting|harming) myself\b", r"\bself[- ]?harm\b", r"\boverdos(e|ing)\b",
    r"\bcan'?t go on\b", r"\bcannot go on\b", r"\bgive up on (life|everything|living)\b",
    r"\b(hurt|kill|shoot|stab) (someone|somebody|people|him|her|them)\b",
    r"\bnobody would (care|notice) if i (was|were) gone\b", r"\bdisappear forever\b",
]
_RE = [re.compile(p, re.IGNORECASE) for p in CRISIS_PATTERNS]

RESOURCES = {
    "level": "crisis",
    "title": "You don't have to handle this alone",
    "message": ("It sounds like you're going through something really hard. Please reach out to someone "
                "right now. These services are free and confidential."),
    "contacts": [
        {"name": "988 Suicide & Crisis Lifeline", "action": "Call or text 988", "href": "tel:988",
         "note": "24/7, free"},
        {"name": "CSULB Counseling and Psychological Services (CAPS)", "action": "Call 562-985-4001",
         "href": "tel:5629854001", "note": "Ask for crisis support"},
        {"name": "Emergency", "action": "Call 911", "href": "tel:911",
         "note": "If you or someone else is in immediate danger"},
    ],
}

PROMPT = """You are a safety screen for a student wellbeing app. Decide if the message suggests risk of
suicide, self-harm, or harming others, now or soon. Everyday exaggeration about school
("this exam is killing me", "I'm dead tired") is NOT risk. When unsure, answer "crisis".
Return JSON: {{"label": "crisis" or "ok"}}
Message: {text}"""


def rules_flag(text: str) -> bool:
    return any(r.search(text or "") for r in _RE)


def check(text: str) -> dict:
    """Return {"level": "ok"} or the fixed crisis resources, plus which layer fired."""
    text = (text or "").strip()
    if not text:
        return {"level": "ok", "by": "empty"}
    if rules_flag(text):
        return {**RESOURCES, "by": "rules"}
    answer = llm.generate_json(PROMPT.format(text=text[:1000]), name="safety.check", temperature=0.0)
    if isinstance(answer, dict) and str(answer.get("label", "")).lower() == "crisis":
        return {**RESOURCES, "by": "gemini"}
    return {"level": "ok", "by": "gemini" if answer is not None else "rules"}
