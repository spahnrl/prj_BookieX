"""
000_RUN_ALL_NCAAM.py

Purpose
-------
Run the NCAA MVP pipeline end-to-end in a deterministic order.

Design goals
------------
- Separate from NBA runner
- Safe for repeatable NCAA MVP execution
- Stops on first failure
- Prints clear step-by-step progress
- Uses the same Python interpreter currently running this file
- Supports optional schedule date-window overrides

Usage
-----
Default recent-window run:
    python 000_RUN_ALL_NCAAM.py

Historical schedule window:
    python 000_RUN_ALL_NCAAM.py --start-date 20260220 --end-date 20260228
"""

import argparse
import subprocess
import sys
from pathlib import Path
from time import perf_counter


PROJECT_ROOT = Path(__file__).resolve().parent

STEPS = [
    "configs/leagues/league_ncaam.py",

    # team universe
    "eng/pipelines/ncaam/a_data_static_000a_build_ncaam_team_map_from_ncaa.py",
    "eng/pipelines/ncaam/a_data_static_000b_ncaam_team_map.py",

    # schedule + scores
    ("eng/pipelines/shared/b_gen_001_ingest_schedule.py", ["--league", "ncaam"]),
    ("eng/pipelines/shared/b_gen_003_join_schedule_teams.py", ["--league", "ncaam"]),
    ("eng/pipelines/shared/b_gen_004_ingest_boxscores.py", ["--league", "ncaam"]),

    # canonical/history
    ("eng/pipelines/shared/d_gen_021_build_canonical_games.py", ["--league", "ncaam"]),
    ("eng/pipelines/shared/d_gen_022_collapse_to_game_level.py", ["--league", "ncaam"]),
    "eng/pipelines/ncaam/c_ncaam_001_build_avg_score_features.py",
    "eng/pipelines/ncaam/c_ncaam_015_build_last5_momentum.py",
    "eng/pipelines/ncaam/c_ncaam_099_merge_model_features.py",

    # market
    ("eng/pipelines/shared/e_gen_031_get_betline.py", ["--league", "ncaam"]),
    ("eng/pipelines/shared/e_gen_032_get_betline_flatten.py", ["--league", "ncaam"]),
    "eng/pipelines/shared/f_gen_041_add_betting_lines.py",

    # models + outputs
    ("eng/models/shared/model_gen_0051_runner.py", ["--league", "ncaam"]),
    ("eng/models/shared/model_gen_0052_add_model.py", ["--league", "ncaam"]),
    ("eng/daily/build_gen_daily_view.py", ["--league", "ncaam"]),
    ("eng/backtest/backtest_gen_runner.py", ["--league", "ncaam"]),
]


def parse_args():
    parser = argparse.ArgumentParser(description="Run the NCAA MVP pipeline end-to-end")
    parser.add_argument("--start-date", dest="start_date", type=str, help="Schedule start date in YYYYMMDD")
    parser.add_argument("--end-date", dest="end_date", type=str, help="Schedule end date in YYYYMMDD")
    parser.add_argument("--quiet", action="store_true", help="Suppress banners and step lines (for combined orchestrator)")
    return parser.parse_args()


def build_step_command(step_spec, args) -> list[str]:
    """step_spec: str (script path) or (script path, list of extra args)."""
    step_path = step_spec[0] if isinstance(step_spec, (list, tuple)) else step_spec
    extra_args = list(step_spec[1]) if isinstance(step_spec, (list, tuple)) and len(step_spec) > 1 else []

    script_path = PROJECT_ROOT / step_path
    if not script_path.exists():
        raise FileNotFoundError(f"Missing pipeline step: {script_path}")

    cmd = [sys.executable, str(script_path)]

    # Schedule step: date-window overrides (unified 001). Default 2025-10-01 to today when not set.
    if "b_gen_001_ingest_schedule.py" in step_path:
        if args.start_date and args.end_date:
            cmd.extend(["--start-date", args.start_date, "--end-date", args.end_date])
        else:
            from datetime import datetime, timezone
            today = datetime.now(timezone.utc).strftime("%Y%m%d")
            cmd.extend(["--start-date", "20251001", "--end-date", today])
    # Unified add-betting-lines: league flag (if not already in extra_args)
    if "f_gen_041_add_betting_lines.py" in step_path and "--league" not in extra_args:
        cmd.extend(["--league", "ncaam"])

    cmd.extend(extra_args)
    return cmd


def run_inline_audit_after_step(step_path: str) -> None:
    """
    Run the integrity check for the given step (NCAAM). Prints INTEGRITY CHECK: PASS/FAIL.
    On mismatch calls sys.exit(1) so the pipeline stops like a script crash.
    """
    from configs.leagues.league_ncaam import (
        SCHEDULE_RAW_JSON_PATH,
        SCHEDULE_RAW_PATH,
        INTERIM_DIR,
        CANONICAL_GAMES_PATH,
        GAME_LEVEL_PATH,
    )
    from utils.audit_helpers import audit_file_consistency, audit_csv_consistency

    if "b_gen_001_ingest_schedule.py" in step_path:
        r = audit_file_consistency(SCHEDULE_RAW_JSON_PATH, SCHEDULE_RAW_PATH, "NCAAM Ingest (schedule)")
        if r["match_status"] != "match":
            print(f"INTEGRITY CHECK: FAIL [{r['label']}] JSON={r['json_count']} CSV={r['csv_count']}")
            sys.exit(1)
        print(f"INTEGRITY CHECK: PASS [{r['label']}] JSON={r['json_count']} CSV={r['csv_count']}")
    elif "b_gen_004_ingest_boxscores.py" in step_path:
        box_json = INTERIM_DIR / "ncaam_boxscores_raw.json"
        box_csv = INTERIM_DIR / "ncaam_boxscores_raw.csv"
        r = audit_file_consistency(box_json, box_csv, "NCAAM Boxscores")
        if r["match_status"] != "match":
            print(f"INTEGRITY CHECK: FAIL [{r['label']}] JSON={r['json_count']} CSV={r['csv_count']}")
            sys.exit(1)
        print(f"INTEGRITY CHECK: PASS [{r['label']}] JSON={r['json_count']} CSV={r['csv_count']}")
    elif "d_gen_022_collapse_to_game_level.py" in step_path:
        r = audit_csv_consistency(
            CANONICAL_GAMES_PATH, GAME_LEVEL_PATH, "NCAAM Canonical (021 vs 022)", expected_derived_per_primary=1.0
        )
        if r["match_status"] != "match":
            print(f"INTEGRITY CHECK: FAIL [{r['label']}] primary={r['primary_count']} derived={r['derived_count']}")
            sys.exit(1)
        print(f"INTEGRITY CHECK: PASS [{r['label']}] primary={r['primary_count']} derived={r['derived_count']}")


def run_step(step_spec, step_num: int, total_steps: int, args, quiet: bool = False) -> float:
    step_path = step_spec[0] if isinstance(step_spec, (list, tuple)) else step_spec
    cmd = build_step_command(step_spec, args)

    if not quiet:
        print("=" * 80)
        print(f"[{step_num}/{total_steps}] RUNNING: {step_path}")
        print(f"COMMAND: {' '.join(cmd)}")
        print("=" * 80)

    start = perf_counter()

    subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        check=True,
    )

    elapsed = perf_counter() - start

    if not quiet:
        print(f"[{step_num}/{total_steps}] SUCCESS: {step_path} | {elapsed:.2f}s")
    if any(x in step_path for x in (
        "b_gen_001_ingest_schedule.py",
        "b_gen_004_ingest_boxscores.py",
        "d_gen_022_collapse_to_game_level.py",
    )):
        run_inline_audit_after_step(step_path)
    return elapsed


def run_all(args) -> None:
    total_steps = len(STEPS)
    total_elapsed = 0.0
    quiet = getattr(args, "quiet", False)

    if not quiet:
        print("\n" + "#" * 80)
        print("STARTING NCAA MVP PIPELINE")
        print("#" * 80)
        print(f"Project root: {PROJECT_ROOT}")
        print(f"Python:       {sys.executable}")
        print(f"Step count:   {total_steps}")
        print(f"Start date:   {args.start_date or '20251001 (default full season)'}")
        print(f"End date:     {args.end_date or 'today (default)'}")

    if (args.start_date and not args.end_date) or (args.end_date and not args.start_date):
        raise ValueError("Both --start-date and --end-date must be provided together")

    for idx, step in enumerate(STEPS, start=1):
        elapsed = run_step(step, idx, total_steps, args, quiet=quiet)
        total_elapsed += elapsed

    if not quiet:
        print("\n" + "#" * 80)
        print("NCAA MVP PIPELINE COMPLETE")
        print("#" * 80)
        print(f"Total elapsed: {total_elapsed:.2f}s")
        print("Artifacts expected under:")
        print(f"  {PROJECT_ROOT / 'data' / 'ncaam'}")


if __name__ == "__main__":
    args = parse_args()
    run_all(args)