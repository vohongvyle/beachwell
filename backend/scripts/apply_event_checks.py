"""Apply the simple "To check" sheet (docs/BeachWell_Events_To_Check.xlsx) to the team tracker,
then rebuild data/events_catalog.csv.

For each row someone filled in:
  Still running? = No       -> Status "Removed" / "Not running" (the app stops suggesting it this term)
  Link you checked          -> Source URL used + today's date (the app shows it as "Checked")
  Correct days/time/weeks   -> the tracker's new days, start, end and weeks

Run from backend/:
    python scripts/apply_event_checks.py ../docs/BeachWell_Events_To_Check.xlsx
    python scripts/seed.py --reset
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
TRACKER = ROOT.parent / "docs" / "BeachWell_Event_Updates.xlsx"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_event_sheet as imp  # noqa: E402

# tracker column names per tab: (id, link, status, date, days, start, end, weeks, stopped value)
TABS = {
    "Event updates": ("Series ID", "Source URL used", "Status", "Date checked", "New days", "New start", "New end",
                      "New weeks", "Removed"),
    "New programs": ("Suggested ID", "Source URL used", "Status", "Date checked", "Days", "Start", "End", "Weeks",
                     "Not running"),
}


def read_checks(path: str) -> dict[str, dict]:
    ws = load_workbook(path, data_only=True)["To check"]
    rows = list(ws.iter_rows(values_only=True))
    h = next(i for i, r in enumerate(rows) if r and r[0] == "ID")
    header = [str(c or "").strip() for c in rows[h]]
    out = {}
    for r in rows[h + 1:]:
        if r and r[0]:
            d = dict(zip(header, r))
            if any(d.get(k) not in (None, "") for k in ("Still running? (Yes/No)", "Link you checked", "Correct days",
                                                         "Correct time", "Correct weeks")):
                out[str(r[0]).strip()] = d
    return out


def main(checks_path: str) -> None:
    checks = read_checks(checks_path)
    if not checks:
        sys.exit("Nothing filled in yet.")
    wb = load_workbook(TRACKER)
    done, problems = [], []
    for ws in wb:
        tab = next((t for t in TABS if ws.title.startswith(t)), None)
        if not tab:
            continue
        idc, linkc, statc, datec, daysc, startc, endc, weeksc, stopped = TABS[tab]
        hrow = next(r for r in ws.iter_rows(min_row=1, max_row=12) if r[0].value == idc)
        col = {c.value: c.column - 1 for c in hrow}
        for row in ws.iter_rows(min_row=hrow[0].row + 1):
            sid = str(row[0].value or "").strip()
            if sid not in checks:
                continue
            c = checks[sid]
            try:
                if str(c.get("Still running? (Yes/No)") or "").strip().lower() == "no":
                    row[col[statc]].value = stopped
                link = imp.url_in(c.get("Link you checked"))
                if link:
                    row[col[linkc]].value = link
                    row[col[datec]].value = date.today()
                if c.get("Correct days"):
                    row[col[daysc]].value = imp.norm_days(c["Correct days"])
                if c.get("Correct time"):
                    a, b = re.split(r"\s*[-–to]+\s*", str(c["Correct time"]).strip(), maxsplit=1)
                    row[col[startc]].value, row[col[endc]].value = imp.norm_time(a), imp.norm_time(b)
                if c.get("Correct weeks"):
                    row[col[weeksc]].value = imp.norm_weeks(c["Correct weeks"])
                done.append(sid)
            except ValueError as e:
                problems.append(f"{sid}: {e}")
    if problems:
        print("Fix these cells in the To check sheet, then run again. Nothing was changed:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    wb.save(TRACKER)
    print(f"Updated {len(done)} programs in {TRACKER.name}: {', '.join(done)}")
    missing = sorted(set(checks) - set(done))
    if missing:
        print("Not found in the tracker:", ", ".join(missing))
    imp.main(str(TRACKER))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT.parent / "docs" / "BeachWell_Events_To_Check.xlsx"))
