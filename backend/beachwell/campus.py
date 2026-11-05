"""Where an event is on campus, and links to get there.

data/campus_locations.csv maps a location as the team wrote it ("SRWC 203C", "PH1 141",
"Central Quad") to a building name and a search text that map apps understand. The app
links to Google Maps for walking directions and shows a small embedded map; no API key
and no stored coordinates are needed, because the map app finds the building by name.
Add a row to the CSV when a new building appears.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

LOCATIONS_CSV = Path(__file__).resolve().parent.parent / "data" / "campus_locations.csv"
CAMPUS = "California State University Long Beach, Long Beach, CA"


@lru_cache(maxsize=1)
def _table() -> list[dict]:
    try:
        with open(LOCATIONS_CSV, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r.get("code")]
    except OSError:
        rows = []
    # longest code first, so "SRWC Aquatics" style names match "SRWC" and "PH1" wins over "PH"
    return sorted(rows, key=lambda r: -len(r["code"]))


def place_for(location: str) -> dict:
    """{"building", "room", "off_campus", "map_query", "directions_url", "map_url", "embed_url"}"""
    loc = (location or "").strip()
    match = None
    for r in _table():
        code = r["code"]
        if loc.lower() == code.lower() or re.match(rf"{re.escape(code)}(\b|[-\s])", loc, re.IGNORECASE):
            match = r
            break
    if match:
        rest = loc[len(match["code"]):].strip(" -")
        room = rest if re.fullmatch(r"[A-Za-z]?\d{2,4}[A-Za-z]?", rest or "") else ""
        building = match["name"] + (f" ({rest})" if rest and not room else "")
        query = match["map_query"]
        off = match.get("off_campus", "no").strip().lower() == "yes"
    else:
        room, building, off = "", loc or "CSULB", False
        query = f"{loc}, {CAMPUS}" if loc else CAMPUS
    q = quote_plus(query)
    return {
        "building": building,
        "room": room,
        "off_campus": off,
        "map_query": query,
        "directions_url": f"https://www.google.com/maps/dir/?api=1&destination={q}&travelmode={'driving' if off else 'walking'}",
        "map_url": f"https://www.google.com/maps/search/?api=1&query={q}",
        "embed_url": f"https://maps.google.com/maps?q={q}&z={14 if off else 17}&output=embed",
    }
