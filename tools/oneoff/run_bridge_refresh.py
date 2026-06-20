"""
Run the WNBA/NHL/MLB bridge refresh flow end to end.

Bridge-only scope:
1. fetch raw odds
2. flatten odds
3. ingest schedule
4. build odds-only canonical bridge
5. build daily slate bridge
6. for WNBA/MLB, build market-value daily model view
7. validate final daily bridge JSON and league daily model JSON
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_LEAGUES = ("wnba", "nhl", "mlb")


def _bridge_json_path(league: str) -> Path:
    return PROJECT_ROOT / "data" / league / "daily" / f"{league}_daily_slate_bridge.json"


def _daily_model_paths(league: str) -> list[Path]:
    daily_dir = PROJECT_ROOT / "data" / league / "daily"
    return sorted(daily_dir.glob(f"daily_view_{league}_*_v1.json"))


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


def _validate_daily_model_json(league: str) -> dict:
    paths = _daily_model_paths(league)
    if not paths:
        raise SystemExit(
            f"[bridge_refresh] FAIL missing {league.upper()} daily model JSON: "
            f"data/{league}/daily/daily_view_{league}_*_v1.json"
        )

    total_games = 0
    total_picks = 0
    latest_path = max(paths, key=lambda p: p.stat().st_mtime)
    latest_payload: dict | None = None

    for path in paths:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            raise SystemExit(f"[bridge_refresh] FAIL invalid {league.upper()} daily model shape: {path}")
        if payload.get("is_model_output") is not True:
            raise SystemExit(f"[bridge_refresh] FAIL {league.upper()} daily model is_model_output must be true: {path}")
        if payload.get("is_roi_output") is not False:
            raise SystemExit(f"[bridge_refresh] FAIL {league.upper()} daily model is_roi_output must be false: {path}")
        games = payload.get("games")
        if not isinstance(games, list) or not games:
            raise SystemExit(f"[bridge_refresh] FAIL {league.upper()} daily model has no games: {path}")
        total_games += len(games)
        for game in games:
            model = (game or {}).get("model_output") or {}
            if model.get("spread_pick") or model.get("total_pick"):
                total_picks += 1
        if path == latest_path:
            latest_payload = payload

    return {
        "daily_model_file_count": len(paths),
        "daily_model_latest_path": latest_path,
        "daily_model_latest_date": (latest_payload or {}).get("date"),
        "daily_model_latest_game_count": len((latest_payload or {}).get("games") or []),
        "daily_model_total_games": total_games,
        "daily_model_games_with_picks": total_picks,
        "daily_model_version": (latest_payload or {}).get("model_version"),
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
    if league in ("wnba", "mlb") and not args.skip_daily_model:
        daily_script = f"eng/daily/build_{league}_daily_view.py"
        daily_cmd = [py, daily_script]
        if args.daily_model_date:
            daily_cmd.extend(["--date", args.daily_model_date])
        commands.append(daily_cmd)
    return commands


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh WNBA/NHL/MLB bridge artifacts only.")
    parser.add_argument("--league", required=True, choices=SUPPORTED_LEAGUES)
    parser.add_argument("--start-date", help="Schedule start date YYYYMMDD. Must be used with --end-date.")
    parser.add_argument("--end-date", help="Schedule end date YYYYMMDD. Must be used with --start-date.")
    parser.add_argument("--skip-odds-fetch", action="store_true", help="Use existing raw odds snapshot.")
    parser.add_argument("--skip-schedule", action="store_true", help="Use existing schedule snapshot.")
    parser.add_argument("--skip-daily-model", action="store_true", help="WNBA/MLB only: skip market-value daily model build.")
    parser.add_argument("--daily-model-date", help="WNBA/MLB only: optional YYYY-MM-DD date passed to daily model builder.")
    args = parser.parse_args()

    for cmd in _build_commands(args):
        _run_step(cmd)

    summary = _validate_bridge_json(args.league)
    daily_summary = _validate_daily_model_json(args.league) if args.league in ("wnba", "mlb") and not args.skip_daily_model else None
    print("\n[bridge_refresh] OK")
    print(f"league={args.league}")
    print(f"daily_bridge_path={summary['path']}")
    print(f"record_count={summary['record_count']}")
    print(f"generated_at_utc={summary['generated_at_utc']}")
    print(f"is_model_output={summary['is_model_output']}")
    print(f"is_roi_output={summary['is_roi_output']}")
    if daily_summary:
        print(f"daily_model_latest_path={daily_summary['daily_model_latest_path']}")
        print(f"daily_model_latest_date={daily_summary['daily_model_latest_date']}")
        print(f"daily_model_latest_game_count={daily_summary['daily_model_latest_game_count']}")
        print(f"daily_model_total_games={daily_summary['daily_model_total_games']}")
        print(f"daily_model_games_with_picks={daily_summary['daily_model_games_with_picks']}")
        print(f"daily_model_version={daily_summary['daily_model_version']}")


if __name__ == "__main__":
    main()
