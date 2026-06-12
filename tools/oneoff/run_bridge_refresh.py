"""
Run the WNBA/NHL bridge refresh flow end to end.

Bridge-only scope:
1. fetch raw odds
2. flatten odds
3. ingest schedule
4. build odds-only canonical bridge
5. build daily slate bridge
6. validate final daily bridge JSON
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_LEAGUES = ("wnba", "nhl")


def _bridge_json_path(league: str) -> Path:
    return PROJECT_ROOT / "data" / league / "daily" / f"{league}_daily_slate_bridge.json"


def _run_step(cmd: list[str]) -> None:
    printable = " ".join(cmd)
    print(f"\n[bridge_refresh] RUN {printable}", flush=True)
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print(f"[bridge_refresh] FAIL exit_code={result.returncode} command={printable}", flush=True)
        raise SystemExit(result.returncode)


def _validate_bridge_json(league: str) -> dict:
    path = _bridge_json_path(league)
    if not path.exists():
        raise SystemExit(f"[bridge_refresh] FAIL missing final daily bridge JSON: {path}")

    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        raise SystemExit(f"[bridge_refresh] FAIL invalid JSON shape: {path}")

    games = payload.get("games")
    record_count = int(payload.get("record_count") or 0)
    if not isinstance(games, list) or not games:
        raise SystemExit(f"[bridge_refresh] FAIL no games in final daily bridge JSON: {path}")
    if record_count <= 0:
        raise SystemExit(f"[bridge_refresh] FAIL record_count must be > 0 in: {path}")
    if payload.get("is_model_output") is not False:
        raise SystemExit(f"[bridge_refresh] FAIL is_model_output must be false in: {path}")
    if payload.get("is_roi_output") is not False:
        raise SystemExit(f"[bridge_refresh] FAIL is_roi_output must be false in: {path}")

    return {
        "path": path,
        "record_count": record_count,
        "generated_at_utc": payload.get("generated_at_utc"),
        "is_model_output": payload.get("is_model_output"),
        "is_roi_output": payload.get("is_roi_output"),
    }


def _build_commands(args: argparse.Namespace) -> list[list[str]]:
    py = sys.executable
    league = args.league
    commands: list[list[str]] = []

    if not args.skip_odds_fetch:
        commands.append([py, "eng/pipelines/shared/e_gen_031_get_betline.py", "--league", league])

    commands.append([py, "eng/pipelines/shared/e_gen_032_get_betline_flatten.py", "--league", league])

    if not args.skip_schedule:
        schedule_cmd = [py, "eng/pipelines/shared/b_gen_001_ingest_schedule.py", "--league", league]
        if args.start_date or args.end_date:
            if not (args.start_date and args.end_date):
                raise SystemExit("--start-date and --end-date must be provided together.")
            schedule_cmd.extend(["--start-date", args.start_date, "--end-date", args.end_date])
        commands.append(schedule_cmd)

    commands.append([py, "eng/pipelines/shared/d_gen_020_build_odds_only_canonical.py", "--league", league])
    commands.append([py, "eng/daily/build_gen_daily_slate_bridge.py", "--league", league])
    return commands


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh WNBA/NHL bridge artifacts only.")
    parser.add_argument("--league", required=True, choices=SUPPORTED_LEAGUES)
    parser.add_argument("--start-date", help="Schedule start date YYYYMMDD. Must be used with --end-date.")
    parser.add_argument("--end-date", help="Schedule end date YYYYMMDD. Must be used with --start-date.")
    parser.add_argument("--skip-odds-fetch", action="store_true", help="Use existing raw odds snapshot.")
    parser.add_argument("--skip-schedule", action="store_true", help="Use existing schedule snapshot.")
    args = parser.parse_args()

    for cmd in _build_commands(args):
        _run_step(cmd)

    summary = _validate_bridge_json(args.league)
    print("\n[bridge_refresh] OK")
    print(f"league={args.league}")
    print(f"daily_bridge_path={summary['path']}")
    print(f"record_count={summary['record_count']}")
    print(f"generated_at_utc={summary['generated_at_utc']}")
    print(f"is_model_output={summary['is_model_output']}")
    print(f"is_roi_output={summary['is_roi_output']}")


if __name__ == "__main__":
    main()
