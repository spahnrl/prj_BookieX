"""
eng/daily/build_gen_daily_view.py

Unified daily view builder: both leagues build from final view. Same contract
(final_view -> daily_view); shared slate-date logic via datetime_bridge.
Delegates to league-specific builders; output structure unchanged for UI.

Usage:
  python eng/daily/build_gen_daily_view.py --league nba
  python eng/daily/build_gen_daily_view.py --league ncaam
  python eng/daily/build_gen_daily_view.py --league ncaam 2026-03-08
  python eng/daily/build_gen_daily_view.py --league ncaam --start-date 20250316 --end-date 20250321
  python eng/daily/build_gen_daily_view.py --league nfl 2025-09-07
  python eng/daily/build_gen_daily_view.py --league ncaaf 2025-09-06

Default (no date, no start/end window): builds **today** and **tomorrow** (CST),
and **yesterday** only before **noon Central** — see ``default_pipeline_daily_dates_cst``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.run_log import set_silent
from utils.datetime_bridge import default_pipeline_daily_dates_cst


def _nba_next_upcoming_slate_dates(existing_dates: list[str], limit: int = 3) -> list[str]:
    from utils.datetime_bridge import get_default_target_slate_date, slate_date_for_game
    from utils.io_helpers import get_final_view_json_path

    path = get_final_view_json_path("nba")
    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    games = payload.get("games") if isinstance(payload, dict) else payload
    if not isinstance(games, list):
        return []

    today_str = get_default_target_slate_date()
    existing = set(existing_dates)
    slate_dates = sorted({
        d
        for d in (slate_date_for_game(g) for g in games if isinstance(g, dict))
        if d and d >= today_str and d not in existing
    })
    return slate_dates[:limit]


def run_nba(date_arg: str | None) -> None:
    from utils.io_helpers import get_final_view_json_path, get_daily_view_output_dir
    import eng.daily.build_daily_view as nba_daily

    nba_daily.MODEL_ARTIFACT_PATH = get_final_view_json_path("nba")
    nba_daily.OUTPUT_DIR = get_daily_view_output_dir("nba")
    if date_arg is not None:
        sys.argv = [sys.argv[0], date_arg]
    else:
        sys.argv = [sys.argv[0]]
    nba_daily.build_daily_view()


def run_ncaam(date_arg: str | None) -> None:
    import eng.daily.build_daily_view_ncaam as ncaam_daily
    from configs.leagues.league_ncaam import ensure_ncaam_dirs

    ensure_ncaam_dirs()
    if date_arg is not None:
        sys.argv = [sys.argv[0], date_arg]
    else:
        sys.argv = [sys.argv[0]]
    ncaam_daily.run()


def run_football(league: str, date_arg: str | None) -> None:
    import eng.daily.build_football_daily_view as football_daily

    football_daily.build_daily_view(league, date_arg)


def _parse_yyyymmdd(s: str) -> date | None:
    """Parse YYYYMMDD to date. Returns None if invalid."""
    if not s or len(s) != 8:
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _date_range_inclusive(start_d: date, end_d: date) -> list[date]:
    """Inclusive range of dates from start_d through end_d. Returns [] if start_d > end_d."""
    if start_d > end_d:
        return []
    out = []
    d = start_d
    while d <= end_d:
        out.append(d)
        d += timedelta(days=1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build daily view for dashboard")
    parser.add_argument("--league", required=True, choices=["nba", "ncaam", "nfl", "ncaaf"])
    parser.add_argument("date", nargs="?", help="Optional date (e.g. 2026-03-08); else earliest upcoming")
    parser.add_argument("--start-date", dest="start_date", type=str, help="Start date YYYYMMDD (use with --end-date for multi-date build)")
    parser.add_argument("--end-date", dest="end_date", type=str, help="End date YYYYMMDD (use with --start-date for multi-date build)")
    parser.add_argument("--silent", action="store_true", help="Only print critical errors")
    args = parser.parse_args()
    set_silent(args.silent)

    use_window = args.start_date and args.end_date
    start_d = _parse_yyyymmdd(args.start_date) if args.start_date else None
    end_d = _parse_yyyymmdd(args.end_date) if args.end_date else None
    if use_window and (start_d is None or end_d is None):
        use_window = False
    if use_window and start_d > end_d:
        use_window = False

    if use_window:
        # Build one file per date in [start_d, end_d]. League builders expect YYYY-MM-DD.
        for d in _date_range_inclusive(start_d, end_d):
            date_str = d.isoformat()
            if args.league == "nba":
                run_nba(date_str)
            elif args.league == "ncaam":
                run_ncaam(date_str)
            else:
                run_football(args.league, date_str)
        return

    # Default pipeline: CST slate window (yesterday before noon, always today + tomorrow).
    if args.date is None:
        daily_dates = list(default_pipeline_daily_dates_cst())
        if args.league == "nba":
            daily_dates.extend(_nba_next_upcoming_slate_dates(daily_dates))
        for d in daily_dates:
            if args.league == "nba":
                run_nba(d)
            elif args.league == "ncaam":
                run_ncaam(d)
            else:
                run_football(args.league, d)
        return

    if args.league == "nba":
        run_nba(args.date)
    elif args.league == "ncaam":
        run_ncaam(args.date)
    else:
        run_football(args.league, args.date)


if __name__ == "__main__":
    main()
