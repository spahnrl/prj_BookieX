"""
eng/daily/build_gen_daily_view.py

Unified daily view builder: produces dashboard-safe JSON/CSV for the selected
date. League-agnostic entrypoint; delegates to existing NBA/NCAAM logic so
output structure remains identical for the Streamlit UI. Outputs are
league-scoped (data/nba/daily, data/ncaam/daily); data/daily is not used.

Usage:
  python eng/daily/build_gen_daily_view.py --league nba
  python eng/daily/build_gen_daily_view.py --league ncaam
  python eng/daily/build_gen_daily_view.py --league ncaam 2026-03-08
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.run_log import set_silent


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
    from utils.io_helpers import get_model_runner_output_json_path, get_daily_view_output_dir
    import eng.daily.build_daily_view_ncaam as ncaam_daily
    from configs.leagues.league_ncaam import DAILY_DIR, ensure_ncaam_dirs

    ncaam_daily.INPUT_PATH = get_model_runner_output_json_path("ncaam")
    # NCAAM get_output_paths uses DAILY_DIR; ensure it matches io_helpers
    ncaam_daily.DAILY_DIR = get_daily_view_output_dir("ncaam")
    ensure_ncaam_dirs()
    if date_arg is not None:
        sys.argv = [sys.argv[0], date_arg]
    else:
        sys.argv = [sys.argv[0]]
    ncaam_daily.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build daily view for dashboard (NBA or NCAAM)")
    parser.add_argument("--league", required=True, choices=["nba", "ncaam"])
    parser.add_argument("date", nargs="?", help="Optional date (e.g. 2026-03-08); else earliest upcoming")
    parser.add_argument("--silent", action="store_true", help="Only print critical errors")
    args = parser.parse_args()
    set_silent(args.silent)
    if args.league == "nba":
        run_nba(args.date)
    else:
        run_ncaam(args.date)


if __name__ == "__main__":
    main()
