"""Pull the summary table from the public Google Sheet into static/mediana-research_MMYYYY.csv.

The month in the file name is the newest month column that has data. Only that month's file
is written: older monthly CSVs are the published archive and are never touched.
Run by .github/workflows/sync-sheet.yml; can also be run by hand: python sync_sheet.py

Exit code 0 = nothing to do or file updated, 1 = the sheet looks wrong and nothing was written.
"""
from __future__ import annotations

import csv
import io
import re
import sys
import urllib.request
from pathlib import Path

SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vR04aAelBkYuAAWPwcN1cY5gu_8yQ8EDbyBoEe1xPfObbaO0bMUUlx6DkuHLsNLUCX9azVcsImTVXxf"
    "/pub?gid=1994855062&single=true&output=csv"
)
STATIC_DIR = Path(__file__).resolve().parent / "static"
DATA_CSV = re.compile(r"mediana-research_(0[1-9]|1[0-2])(\d{4})\.csv")
MONTH_COL = re.compile(r"(0[1-9]|1[0-2])\.(\d{2})")
MIN_PROJECTS = 50  # fewer rows than this means a broken export, not real data


def fail(msg: str) -> None:
    print(f"sync_sheet: {msg}; nothing written", file=sys.stderr)
    sys.exit(1)


def download() -> str:
    req = urllib.request.Request(SHEET_CSV_URL, headers={"User-Agent": "mediana-sheet-sync"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        if "text/csv" not in resp.headers.get("Content-Type", ""):
            fail(f"expected CSV, got {resp.headers.get('Content-Type')}")
        return resp.read().decode("utf-8-sig")


def latest_saved() -> tuple[int, int]:
    found = [(int(m[2]), int(m[1])) for f in STATIC_DIR.glob("*.csv") if (m := DATA_CSV.fullmatch(f.name))]
    return max(found, default=(0, 0))


def main() -> None:
    text = download()
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0][0].strip() != "Проект":
        fail("first header cell is not «Проект»")
    head = rows[0]
    months = [i for i, h in enumerate(head) if MONTH_COL.fullmatch(h.strip())]
    if not months or months != list(range(months[0], months[0] + len(months))):
        fail("month columns MM.YY not found or not contiguous")

    projects = [r for r in rows[2:] if r and r[0].strip() and any(c.strip() for c in r[months[0]:])]
    if len(projects) < MIN_PROJECTS:
        fail(f"only {len(projects)} project rows")

    # Newest month that has any project value; month columns added ahead of time are dropped.
    filled = [i for i in months if any(len(r) > i and r[i].strip() for r in projects)]
    last = filled[-1]
    mm, yy = MONTH_COL.fullmatch(head[last].strip()).groups()
    year, month = 2000 + int(yy), int(mm)
    if (year, month) < latest_saved():
        fail(f"sheet ends at {mm}.{year}, older than the newest saved CSV")

    if last != months[-1]:
        out = io.StringIO()
        csv.writer(out, lineterminator="\r\n").writerows(r[: last + 1] for r in rows)
        text = out.getvalue()
    data = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")

    target = STATIC_DIR / f"mediana-research_{mm}{year}.csv"
    if target.is_file() and target.read_bytes() == data:
        print(f"sync_sheet: {target.name} is up to date")
        return
    action = "updated" if target.is_file() else "created"
    target.write_bytes(data)
    n = sum(1 for r in projects if len(r) > last and r[last].strip())
    print(f"sync_sheet: {action} {target.name} ({len(projects)} projects, {n} with data for {mm}.{year})")


if __name__ == "__main__":
    main()
