"""
Validate WNBA daily market-value model artifacts.

Read-only helper: reports games, picks, model lanes, and ROI flags without
creating outputs or mutating tracked data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DAILY_DIR = PROJECT_ROOT / "data" / "wnba" / "daily"


def _load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise SystemExit(f"Invalid JSON object: {path}")
    return payload


def _paths() -> list[Path]:
    return sorted(DAILY_DIR.glob("daily_view_wnba_*_v1.json"))


def _summarize_game(game: dict) -> dict:
    identity = game.get("identity") or {}
    model = game.get("model_output") or {}
    edge = game.get("edge_metrics") or {}
    return {
        "matchup": f"{identity.get('away_team', '')} @ {identity.get('home_team', '')}",
        "spread_pick": model.get("spread_pick") or "",
        "total_pick": model.get("total_pick") or "",
        "confidence_tier": model.get("confidence_tier") or "",
        "actionability": model.get("actionability") or "",
        "spread_edge": edge.get("spread_edge"),
        "total_edge": edge.get("total_edge"),
        "model_lanes": ",".join((game.get("models") or {}).keys()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate WNBA daily market-value model artifacts.")
    parser.add_argument("--date", help="Optional slate date YYYY-MM-DD.")
    args = parser.parse_args()

    paths = _paths()
    if args.date:
        paths = [p for p in paths if f"_{args.date}_" in p.name]
    if not paths:
        raise SystemExit(f"No WNBA daily model artifacts found in {DAILY_DIR}")

    total_games = 0
    total_picks = 0
    print(f"[wnba_daily_model_validation] files={len(paths)}")
    for path in paths:
        payload = _load(path)
        games = payload.get("games") or []
        if payload.get("is_model_output") is not True:
            raise SystemExit(f"is_model_output must be true: {path}")
        if payload.get("is_roi_output") is not False:
            raise SystemExit(f"is_roi_output must be false: {path}")
        if not games:
            raise SystemExit(f"No games in artifact: {path}")
        game_picks = sum(1 for g in games if (g.get("model_output") or {}).get("spread_pick") or (g.get("model_output") or {}).get("total_pick"))
        total_games += len(games)
        total_picks += game_picks
        print(
            f"\nfile={path}"
            f"\ndate={payload.get('date')}"
            f"\nmodel_version={payload.get('model_version')}"
            f"\ngames={len(games)}"
            f"\ngames_with_picks={game_picks}"
            f"\nis_model_output={payload.get('is_model_output')}"
            f"\nis_roi_output={payload.get('is_roi_output')}"
        )
        for row in [_summarize_game(g) for g in games]:
            print(
                "  "
                f"{row['matchup']} | spread={row['spread_pick'] or '-'} | total={row['total_pick'] or '-'} "
                f"| tier={row['confidence_tier']} | action={row['actionability']} "
                f"| edges=({row['spread_edge']}, {row['total_edge']})"
            )

    print(f"\n[wnba_daily_model_validation] OK total_games={total_games} total_games_with_picks={total_picks}")


if __name__ == "__main__":
    main()
