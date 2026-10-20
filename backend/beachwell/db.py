"""SQLite storage (Python standard library, no server to install).

Design choices that keep student data minimal:
  * The Canvas feed URL is used once to import deadlines and is never stored.
  * Check-ins store numbers only (hours slept, stress 1-5) plus a safety flag;
    the free-text note is checked and then discarded.
  * DELETE /api/users/{id} removes every row belonging to a student.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    interests TEXT NOT NULL DEFAULT '',
    college TEXT NOT NULL DEFAULT 'Undeclared',
    weekly_capacity REAL NOT NULL DEFAULT 25,
    radar_opt_in INTEGER NOT NULL DEFAULT 1,
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    uid TEXT NOT NULL,
    title TEXT NOT NULL,
    course TEXT NOT NULL,
    due TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT 'homework',
    major INTEGER NOT NULL DEFAULT 0,
    base_hours REAL NOT NULL DEFAULT 2,
    est_source TEXT NOT NULL DEFAULT 'rules',
    user_hours REAL,
    actual_hours REAL,
    done INTEGER NOT NULL DEFAULT 0,
    UNIQUE (user_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_tasks_user_due ON tasks(user_id, due);
CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course TEXT NOT NULL,
    weekday INTEGER NOT NULL,      -- 0 = Monday
    start_hour REAL NOT NULL,      -- 13.5 = 1:30 pm
    end_hour REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    sleep_hours REAL NOT NULL,
    stress INTEGER NOT NULL,
    flagged INTEGER NOT NULL DEFAULT 0,
    UNIQUE (user_id, day)
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    organizer TEXT NOT NULL,
    description TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    series TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    is_sample INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or get_settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def rows(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


def one(cur: sqlite3.Cursor) -> dict[str, Any] | None:
    r = cur.fetchone()
    return dict(r) if r else None
