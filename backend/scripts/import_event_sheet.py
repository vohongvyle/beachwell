"""Turn the team's event-update spreadsheet into data/events_catalog.csv.

The spreadsheet (docs/BeachWell_Event_Updates.xlsx) has two tabs the team fills in:
  "Event updates"      one row per program already in the catalog
  "New programs (30)"  more real CSULB programs to look up

For every row, the yellow "new" columns win over the old values. A row counts as
checked on an official page when "Source URL used" is a real link (not "Sample");
its date goes into the dates_checked column, and the app shows it as confirmed.
Rows without a link keep their times but stay marked as unconfirmed. A Status of
"Removed" or "Not running" keeps the row (past terms and the evaluation still use it)
but the app stops suggesting it this term. Days and times can stay as they are.
Self-guided programs that are open any time can use 00:00 to 23:59.

Descriptions and tags already in events_catalog.csv are kept; new programs get the
sheet's suggested tags and description until someone writes better ones in the CSV.

Run from backend/ (default sheet path shown):
    python scripts/import_event_sheet.py ../docs/BeachWell_Event_Updates.xlsx
then:
    python scripts/seed.py --reset
"""
from __future__ import annotations

import csv
import re
import sys
from datetime import date, datetime, time
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "events_catalog.csv"
FIELDS = ["series_id", "title", "organizer", "description", "tags", "location", "days", "start", "end",
          "weeks", "source_url", "is_real_program", "dates_checked", "running_this_term"]
STOPPED = {"removed", "not running"}  # Status values that mean "not running this term"
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def norm_days(v) -> str:
    """'Mon;Tue;Wed;Thu:Fri' or 'mon, wed' -> 'Mon;Tue;Wed;Thu;Fri'."""
    parts = [p.strip()[:3].title() for p in re.split(r"[;:,/\s]+", str(v or "")) if p.strip()]
    bad = [p for p in parts if p not in DAYS]
    if bad or not parts:
        raise ValueError(f"days '{v}' (use Mon;Wed)")
    return ";".join(sorted(dict.fromkeys(parts), key=DAYS.index))


def norm_time(v) -> str:
    if isinstance(v, datetime):
        v = v.time()
    if isinstance(v, time):
        return f"{v.hour:02d}:{v.minute:02d}"
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(v or ""))
    if not m:
        raise ValueError(f"time '{v}' (use 24-hour HH:MM)")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def norm_weeks(v) -> str:
    s = str(v if v is not None else "").strip()
    if s.lower() in ("regular", ""):
        return "regular"
    weeks = [int(float(w)) for w in re.split(r"[;,\s]+", s) if w.strip()]
    if any(w < 1 or w > 17 for w in weeks):
        raise ValueError(f"weeks '{v}' (use regular or 8;9;16, weeks 1-17)")
    return ";".join(str(w) for w in sorted(set(weeks)))


def url_in(text) -> str:
    m = re.search(r"https?://\S+", str(text or ""))
    return m.group(0) if m else ""


def checked_date(v) -> str:
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    return str(v or "").strip()


def tags_from(v) -> str:
    tags = [t.strip().lower() for t in re.split(r"[;,]", str(v or "")) if t.strip()]
    tags = ["large-crowd" if t == "crowd" else t for t in tags]
    return ";".join(dict.fromkeys(tags))


def rows_of(ws, header_row_contains: str):
    rows = list(ws.iter_rows(values_only=True))
    h = next(i for i, r in enumerate(rows) if r and r[0] == header_row_contains)
    header = [str(c).strip() if c is not None else "" for c in rows[h]]
    for r in rows[h + 1:]:
        if r and r[0]:
            yield dict(zip(header, r))


def main(sheet_path: str) -> None:
    old = {r["series_id"]: r for r in csv.DictReader(open(CSV_PATH, encoding="utf-8"))}
    wb = load_workbook(sheet_path, data_only=True)
    out, problems, notes = [], [], []

    def build(sid, title, org, days, start, end, weeks, loc, src_used, fallback_src, checked, real,
              desc_default, tags_default, label, status=""):
        try:
            row = {"series_id": sid, "title": title, "organizer": org,
                   "days": norm_days(days), "start": norm_time(start), "end": norm_time(end),
                   "weeks": norm_weeks(weeks)}
        except ValueError as e:
            problems.append(f"{label} {sid}: {e}")
            return
        if row["start"] >= row["end"]:
            problems.append(f"{label} {sid}: start {row['start']} is not before end {row['end']}")
            return
        link = url_in(src_used)
        prev = old.get(sid, {})
        row.update({
            "description": prev.get("description") or desc_default,
            "tags": prev.get("tags") or tags_default,
            "location": str(loc or prev.get("location") or "").strip(),
            "source_url": link or prev.get("source_url") or fallback_src,
            "is_real_program": real,
            "dates_checked": checked if link else "",
            "running_this_term": "no" if str(status or "").strip().lower() in STOPPED else "yes",
        })
        out.append(row)

    for r in rows_of(wb["Event updates"], "Series ID"):
        sid = str(r["Series ID"]).strip()
        prev = old.get(sid, {})
        build(sid, prev.get("title") or r["Program"], prev.get("organizer") or r["Organizer"],
              r["New days"] or r["Days now"], r["New start"] or r["Start now"], r["New end"] or r["End now"],
              r["New weeks"] if r["New weeks"] not in (None, "") else r["Weeks now"],
              r["New location"], r["Source URL used"], url_in(r["Where to check"]), checked_date(r["Date checked"]),
              "yes" if str(r["Real program?"]).strip().lower() == "yes" else "no", "", "", "existing", r.get("Status"))
    new_tab = next((ws for ws in wb if ws.title.startswith("New programs")), None)
    if new_tab is not None:
        for r in rows_of(new_tab, "Suggested ID"):
            sid = str(r["Suggested ID"]).strip()
            if str(r.get("Fits BeachWell?") or "").strip().lower() == "no":
                notes.append(f"skipped {sid}: marked as not a fit")
                continue
            if not (r["Days"] and r["Start"] and r["End"]):
                notes.append(f"skipped {sid}: no days or times yet")
                continue
            build(sid, r["Program"], r["Organizer"], r["Days"], r["Start"], r["End"], r["Weeks"], r["Location"],
                  r["Source URL used"], url_in(r["Source page"]), checked_date(r["Date checked"]), "yes",
                  str(r["What the page says"] or "").strip(), tags_from(r["Suggested tags"]), "new", r.get("Status"))

    if problems:
        print("Fix these cells in the sheet, then run again. Nothing was written:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    ids = [r["series_id"] for r in out]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        sys.exit(f"Duplicate series ids: {', '.join(sorted(dupes))}")
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    checked = sum(bool(r["dates_checked"]) for r in out)
    stopped = [r["series_id"] for r in out if r["running_this_term"] == "no"]
    if stopped:
        notes.append(f"not running this term (kept for past terms and the evaluation): {', '.join(stopped)}")
    print(f"Wrote {len(out)} programs to {CSV_PATH.relative_to(ROOT)}: {checked} with dates checked on an official page, "
          f"{len(out) - checked} still unconfirmed.")
    for n in notes:
        print("  ", n)
    print("Next: python scripts/seed.py --reset")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT.parent / "docs" / "BeachWell_Event_Updates.xlsx"))
