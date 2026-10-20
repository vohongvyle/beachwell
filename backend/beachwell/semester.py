"""Semester calendar helpers: week numbers and week date ranges."""
from __future__ import annotations

from datetime import date, timedelta

from .config import get_settings


def semester_start() -> date:
    start = get_settings().semester_start
    return start - timedelta(days=start.weekday())  # align to Monday


def week_of(d: date) -> int:
    """Week 1 is the first week of classes. Dates before the semester give week <= 0."""
    return (d - semester_start()).days // 7 + 1


def week_start(week: int) -> date:
    return semester_start() + timedelta(days=7 * (week - 1))


def week_range(week: int) -> tuple[date, date]:
    start = week_start(week)
    return start, start + timedelta(days=6)


def week_label(week: int) -> str:
    start, end = week_range(week)
    if start.month == end.month:
        return f"{start.strftime('%b')} {start.day}–{end.day}"
    return f"{start.strftime('%b')} {start.day} – {end.strftime('%b')} {end.day}"
