"""Settings, read from environment variables (and backend/.env if present).

Nothing secret is ever hard-coded here. Copy backend/.env.example to backend/.env
and fill in GEMINI_API_KEY to switch the agents from offline mode to Gemini.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines). Real environment variables win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BACKEND_DIR / ".env")


def _date(name: str, default: str) -> date:
    return date.fromisoformat(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY", "").strip())
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", "gemini-2.5-flash"))
    embedding_model: str = field(default_factory=lambda: os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001"))
    embedding_dim: int = field(default_factory=lambda: int(os.environ.get("EMBEDDING_DIM", "768")))
    db_path: Path = field(
        default_factory=lambda: Path(os.environ.get("DB_PATH", str(BACKEND_DIR / "data" / "beachwell.db")))
    )
    # Semester calendar. Placeholder values: check them against the official
    # CSULB academic calendar before a real deployment.
    semester_start: date = field(default_factory=lambda: _date("SEMESTER_START", "2026-08-24"))
    semester_weeks: int = field(default_factory=lambda: int(os.environ.get("SEMESTER_WEEKS", "17")))
    # Lets a demo pretend "today" is a fixed date so the video is reproducible.
    demo_today: str = field(default_factory=lambda: os.environ.get("DEMO_TODAY", "").strip())
    # Campus Radar never shows a group smaller than this (k-anonymity floor).
    radar_min_group: int = field(default_factory=lambda: int(os.environ.get("RADAR_MIN_GROUP", "10")))
    # Allow the server to download a Canvas feed from a URL (https only).
    allow_feed_fetch: bool = field(default_factory=lambda: os.environ.get("ALLOW_FEED_FETCH", "1") == "1")

    @property
    def online(self) -> bool:
        """True when a Gemini key is configured; otherwise agents use offline fallbacks."""
        return bool(self.gemini_api_key) and os.environ.get("BEACHWELL_OFFLINE", "0") != "1"

    def today(self) -> date:
        return date.fromisoformat(self.demo_today) if self.demo_today else date.today()


def get_settings() -> Settings:
    return Settings()
