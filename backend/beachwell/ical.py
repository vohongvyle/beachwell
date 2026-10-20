"""Read Canvas calendar feeds (iCalendar / .ics) and write study plans back out.

Dependency-free on purpose: the iCalendar subset Canvas emits is small. Canvas puts
the course name in square brackets at the end of each SUMMARY, for example
"Project Milestone 2 [CECS 458 Sec 01 Fall 2026]".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Los_Angeles")


@dataclass
class FeedItem:
    uid: str
    title: str
    course: str
    due: datetime  # timezone-aware, local time
    description: str = ""
    url: str = ""
    all_day: bool = False


def _unfold(text: str) -> list[str]:
    """RFC 5545 line unfolding: a line starting with space/tab continues the previous one."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
    )


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _parse_dt(value: str, params: dict[str, str]) -> tuple[datetime, bool]:
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value[:8], "%Y%m%d").date()
        # All-day items count as due at 11:59 pm local time.
        return datetime.combine(d, time(23, 59), LOCAL_TZ), True
    if value.endswith("Z"):
        dt = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.astimezone(LOCAL_TZ), False
    fmt = "%Y%m%dT%H%M%S" if len(value) >= 15 else "%Y%m%dT%H%M"
    dt = datetime.strptime(value, fmt)
    tz = ZoneInfo(params["TZID"]) if "TZID" in params else LOCAL_TZ
    return dt.replace(tzinfo=tz).astimezone(LOCAL_TZ), False


_COURSE_RE = re.compile(r"^(?P<title>.*?)\s*\[(?P<course>[^\[\]]+)\]\s*$")


def split_course(summary: str) -> tuple[str, str]:
    """'Lab 4 [CECS 458 Sec 01 Fall 2026]' -> ('Lab 4', 'CECS 458')."""
    m = _COURSE_RE.match(summary.strip())
    if not m:
        return summary.strip(), "Other"
    course_full = m.group("course").strip()
    short = re.match(r"([A-Z]{2,5})\s*-?\s*(\d{2,3}[A-Z]?)", course_full)
    return m.group("title").strip(), (f"{short.group(1)} {short.group(2)}" if short else course_full)


def parse_ics(text: str) -> list[FeedItem]:
    """Parse VEVENTs from an iCalendar string into FeedItems (one per event)."""
    items: list[FeedItem] = []
    current: dict[str, tuple[str, dict[str, str]]] | None = None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current and "DTSTART" in current and "SUMMARY" in current:
                # Canvas uses DTEND (or DTSTART when equal) as the due time.
                key = "DTEND" if "DTEND" in current else "DTSTART"
                due, all_day = _parse_dt(*current[key])
                title, course = split_course(_unescape(current["SUMMARY"][0]))
                items.append(
                    FeedItem(
                        uid=_unescape(current.get("UID", ("", {}))[0]) or f"{title}-{due.isoformat()}",
                        title=title,
                        course=course,
                        due=due,
                        description=_unescape(current.get("DESCRIPTION", ("", {}))[0])[:2000],
                        url=_unescape(current.get("URL", ("", {}))[0]),
                        all_day=all_day,
                    )
                )
            current = None
            continue
        if current is None or ":" not in line:
            continue
        head, value = line.split(":", 1)
        name, *param_parts = head.split(";")
        params = {}
        for part in param_parts:
            if "=" in part:
                k, v = part.split("=", 1)
                params[k.upper()] = v.strip('"')
        current[name.upper()] = (value, params)
    return items


def _fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fold(line: str) -> str:
    """Fold long lines at 74 characters as RFC 5545 asks."""
    out, chunk = [], line
    while len(chunk) > 74:
        out.append(chunk[:74])
        chunk = " " + chunk[74:]
    out.append(chunk)
    return "\r\n".join(out)


def write_ics(events: Iterable[dict], calendar_name: str = "BeachWell study plan") -> str:
    """events: dicts with uid, title, start, end (aware datetimes) and optional description."""
    now = _fmt_utc(datetime.now(timezone.utc))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//BeachWell//Study Plan//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_escape(calendar_name)}",
    ]
    for ev in events:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{_escape(str(ev['uid']))}@beachwell",
            f"DTSTAMP:{now}",
            f"DTSTART:{_fmt_utc(ev['start'])}",
            f"DTEND:{_fmt_utc(ev['end'])}",
            f"SUMMARY:{_escape(ev['title'])}",
        ]
        if ev.get("description"):
            lines.append(f"DESCRIPTION:{_escape(ev['description'])}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def local_dt(d: date, hour: float) -> datetime:
    """A local datetime on day d at a fractional hour (e.g. 18.5 -> 6:30 pm)."""
    h = int(hour)
    m = int(round((hour - h) * 60))
    return datetime.combine(d, time(0, 0), LOCAL_TZ) + timedelta(hours=h, minutes=m)
