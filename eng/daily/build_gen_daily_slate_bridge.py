"""
Build daily slate bridge artifacts for leagues that have canonical bridge rows
but do not yet have model or ROI outputs.

This is intentionally not a predictive model builder. It reads canonical games
and emits dashboard-ready slate records with explicit non-model metadata.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.io_helpers import get_canonical_games_csv_path, get_daily_view_output_dir

SUPPORTED_BRIDGE_LEAGUES = ("wnba", "nhl", "mlb", "nfl", "ncaaf")
ARTIFACT_TYPE = "daily_slate_bridge"
SOURCE = "canonical_bridge"
BRIDGE_WARNING = "Bridge artifact only. Not a predictive model output. No ROI or pick generated."

GAME_FIELDS = [
    "league",
    "game_id",
    "game_date",
    "commence_time",
    "home_team",
    "away_team",
    "home_team_key",
    "away_team_key",
    "status",
    "completed",
    "source_system",
    "has_schedule_match",
    "bookmaker_count",
    "market_count",
    "has_h2h",
    "has_spreads",
    "has_totals",
    "display_matchup",
    "display_time_utc",
    "bridge_warning",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_text(value).lower()
    return text in {"1", "true", "yes", "y"}


def _to_int(value) -> int:
    text = _safe_text(value)
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def _load_canonical_rows(league: str) -> tuple[Path, list[dict]]:
    path = get_canonical_games_csv_path(league)
    if not path.exists():
        raise FileNotFoundError(f"Missing canonical bridge CSV for {league}: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise ValueError(f"Canonical bridge CSV is empty for {league}: {path}")
    return path, rows


def _bridge_game(row: dict, league: str) -> dict:
    home_team = _safe_text(row.get("home_team"))
    away_team = _safe_text(row.get("away_team"))
    commence_time = _safe_text(row.get("commence_time"))

    return {
        "league": _safe_text(row.get("league")) or league,
        "game_id": _safe_text(row.get("game_id")),
        "game_date": _safe_text(row.get("game_date")),
        "commence_time": commence_time,
        "home_team": home_team,
        "away_team": away_team,
        "home_team_key": _safe_text(row.get("home_team_key")),
        "away_team_key": _safe_text(row.get("away_team_key")),
        "status": _safe_text(row.get("status")),
        "completed": _to_bool(row.get("completed")),
        "source_system": _safe_text(row.get("source_system")),
        "has_schedule_match": _to_bool(row.get("has_schedule_match")),
        "bookmaker_count": _to_int(row.get("bookmaker_count")),
        "market_count": _to_int(row.get("market_count")),
        "has_h2h": _to_bool(row.get("has_h2h")),
        "has_spreads": _to_bool(row.get("has_spreads")),
        "has_totals": _to_bool(row.get("has_totals")),
        "display_matchup": f"{away_team} at {home_team}".strip(),
        "display_time_utc": commence_time,
        "bridge_warning": BRIDGE_WARNING,
    }


def _validate_games(games: list[dict], league: str) -> list[str]:
    issues = []
    required = ["game_id", "home_team", "away_team", "home_team_key", "away_team_key"]
    for idx, game in enumerate(games, start=1):
        missing = [field for field in required if not _safe_text(game.get(field))]
        if missing:
            issues.append(f"{league} row {idx} missing: {', '.join(missing)}")
    return issues


def _output_paths(league: str) -> tuple[Path, Path]:
    daily_dir = get_daily_view_output_dir(league)
    daily_dir.mkdir(parents=True, exist_ok=True)
    return (
        daily_dir / f"{league}_daily_slate_bridge.json",
        daily_dir / f"{league}_daily_slate_bridge.csv",
    )


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _write_csv(path: Path, games: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=GAME_FIELDS)
        writer.writeheader()
        for game in games:
            writer.writerow({field: game.get(field, "") for field in GAME_FIELDS})


def build_daily_slate_bridge(league: str) -> dict:
    league = _safe_text(league).lower()
    if league not in SUPPORTED_BRIDGE_LEAGUES:
        raise ValueError(f"Unsupported bridge league: {league}. Use one of: {', '.join(SUPPORTED_BRIDGE_LEAGUES)}")

    input_path, rows = _load_canonical_rows(league)
    games = [_bridge_game(row, league) for row in rows]
    issues = _validate_games(games, league)
    if issues:
        raise ValueError("; ".join(issues))

    json_path, csv_path = _output_paths(league)
    payload = {
        "league": league,
        "artifact_type": ARTIFACT_TYPE,
        "generated_at_utc": _utc_now_iso(),
        "source": SOURCE,
        "source_file": str(input_path),
        "is_model_output": False,
        "is_roi_output": False,
        "record_count": len(games),
        "games": games,
    }
    _write_json(json_path, payload)
    _write_csv(csv_path, games)

    return {
        "league": league,
        "input_path": input_path,
        "json_path": json_path,
        "csv_path": csv_path,
        "record_count": len(games),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build non-model daily slate bridge artifacts for WNBA/NHL/MLB/NFL/NCAAF.")
    parser.add_argument("--league", required=True, choices=SUPPORTED_BRIDGE_LEAGUES)
    args = parser.parse_args()

    result = build_daily_slate_bridge(args.league)
    print(
        f"[daily_slate_bridge] league={result['league']} rows={result['record_count']} "
        f"json={result['json_path']} csv={result['csv_path']}"
    )


if __name__ == "__main__":
    main()
