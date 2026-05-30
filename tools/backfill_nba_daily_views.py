#!/usr/bin/env python
"""
tools/backfill_nba_daily_views.py

Backfill-only repair: regenerate missing NBA daily-view JSON files by replaying
the EXISTING daily builder (eng/daily/build_gen_daily_view.py) one date at a time.

This script is read-only with respect to model/scoring/odds/dashboard logic. It
only invokes the existing builder and validates the JSON it writes. It never
recomputes the model or re-ingests data.

Default range: 2026-05-18 .. 2026-05-28 (inclusive).
Existing daily files are SKIPPED unless --force is given.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LEAGUE = "nba"
DEFAULT_START = date(2026, 5, 18)
DEFAULT_END = date(2026, 5, 28)

BUILDER = PROJECT_ROOT / "eng" / "daily" / "build_gen_daily_view.py"


def _daily_dir() -> Path:
    from utils.io_helpers import get_daily_view_output_dir
    return get_daily_view_output_dir(LEAGUE)


def _parse_date(s: str) -> date:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"Invalid date: {s!r} (use YYYY-MM-DD or YYYYMMDD)")


def _date_range(start_d: date, end_d: date) -> list[date]:
    out: list[date] = []
    d = start_d
    while d <= end_d:
        out.append(d)
        d += timedelta(days=1)
    return out


def _output_path(d: date) -> Path:
    return _daily_dir() / f"daily_view_{d.isoformat()}_v1.json"


def _validate_json(path: Path) -> int:
    """Return game count if the file is valid JSON with a 'games' list; raise otherwise."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    games = data.get("games") if isinstance(data, dict) else None
    if not isinstance(games, list):
        raise ValueError("missing 'games' list")
    return len(games)


def _build_one(d: date) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(BUILDER),
        "--league", LEAGUE,
        d.isoformat(),
    ]
    return subprocess.run(cmd, cwd=str(PROJECT_ROOT), text=True, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill NBA daily-view JSON files (build-only, safe)."
    )
    parser.add_argument("--start-date", type=_parse_date, default=DEFAULT_START,
                        help="Start date (YYYY-MM-DD or YYYYMMDD). Default 2026-05-18.")
    parser.add_argument("--end-date", type=_parse_date, default=DEFAULT_END,
                        help="End date (YYYY-MM-DD or YYYYMMDD). Default 2026-05-28.")
    parser.add_argument("--force", action="store_true",
                        help="Rebuild even if the daily file already exists.")
    args = parser.parse_args()

    if args.start_date > args.end_date:
        print(f"ERROR: start-date {args.start_date} is after end-date {args.end_date}")
        return 2

    dates = _date_range(args.start_date, args.end_date)
    daily_dir = _daily_dir()
    daily_dir.mkdir(parents=True, exist_ok=True)

    attempted: list[str] = []
    created: list[str] = []
    skipped: list[str] = []
    zero_game: list[str] = []
    errors: list[tuple[str, str]] = []

    print(f"NBA daily backfill: {args.start_date.isoformat()} .. {args.end_date.isoformat()} "
          f"({len(dates)} dates)  force={args.force}")
    print(f"Output dir: {daily_dir}\n")

    for d in dates:
        iso = d.isoformat()
        out = _output_path(d)

        if out.exists() and not args.force:
            skipped.append(iso)
            print(f"[skip]   {iso}  (exists; use --force to rebuild)")
            continue

        attempted.append(iso)
        print(f"[build]  {iso}  ...")
        proc = _build_one(d)

        if proc.returncode != 0:
            tail = " | ".join((proc.stderr or proc.stdout or "").strip().splitlines()[-3:])
            errors.append((iso, f"builder exit {proc.returncode}: {tail}"))
            print(f"[error]  {iso}  builder returned {proc.returncode}")
            continue

        if not out.exists():
            errors.append((iso, "builder finished but output file not found"))
            print(f"[error]  {iso}  no output file produced")
            continue

        try:
            n = _validate_json(out)
        except Exception as e:
            errors.append((iso, f"invalid JSON: {e}"))
            print(f"[error]  {iso}  invalid JSON: {e}")
            continue

        created.append(iso)
        if n == 0:
            zero_game.append(iso)
        print(f"[ok]     {iso}  created ({n} games)")

    print("\n==================== BACKFILL SUMMARY ====================")
    print(f"Range            : {args.start_date.isoformat()} .. {args.end_date.isoformat()}  ({len(dates)} dates)")
    print(f"Attempted builds : {len(attempted)}  {attempted}")
    print(f"Created          : {len(created)}  {created}")
    print(f"Skipped (exists) : {len(skipped)}  {skipped}")
    print(f"Zero-game dates  : {len(zero_game)}  {zero_game}")
    print(f"Errors           : {len(errors)}")
    for iso, msg in errors:
        print(f"    - {iso}: {msg}")
    print("==========================================================")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())