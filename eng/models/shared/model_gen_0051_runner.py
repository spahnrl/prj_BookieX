"""
eng/models/model_gen_0051_runner.py

Unified model runner: load game-level data (with lines), run league-specific
model registry, write multi-model projection JSON and CSV.

Uses utils.io_helpers:
- load_game_state(league) for input (game-level with odds)
- get_model_runner_output_json_path(league), get_model_runner_output_csv_path(league)

Usage:
  python eng/models/model_gen_0051_runner.py --league nba
  python eng/models/model_gen_0051_runner.py --league ncaam

Output schema: { "version": "...", "generated_at": "...", "games": [...] }
Matches Streamlit UI expectation for both leagues. Forward-only: reads only
game state; writes only runner output. Does not modify model math.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.run_log import set_silent, log_info


# =============================================================================
# SHARED: Model contract and validate
# =============================================================================

REQUIRED_MODEL_KEYS = {
    "model_name",
    "total_projection",
    "total_distance",
    "total_edge",
    "total_pick",
    "home_line_proj",
    "spread_distance",
    "spread_edge",
    "spread_pick",
    "parlay_edge_score",
    "context_flags",
}


def validate_model_contract(result: dict, game_id: str) -> None:
    if not isinstance(result, dict):
        raise ValueError(f"[ModelContractError] Game {game_id}: Model returned non-dict result")
    missing = REQUIRED_MODEL_KEYS - result.keys()
    extra = result.keys() - REQUIRED_MODEL_KEYS
    if missing:
        raise ValueError(f"[ModelContractError] Game {game_id}: Missing keys: {missing}")
    if extra:
        raise ValueError(f"[ModelContractError] Game {game_id}: Unexpected keys: {extra}")
    if not isinstance(result.get("context_flags"), dict):
        raise ValueError(f"[ModelContractError] Game {game_id}: context_flags must be dict")


# =============================================================================
# SHARED: Run models over games (registry and sort key are league-specific)
# =============================================================================

def run_models(games: list[dict], model_registry: list, sort_key) -> list[dict]:
    models = [cls() for cls in model_registry]
    multi_output = []

    for game in sorted(games, key=sort_key):
        model_results = {}
        for model in models:
            try:
                result = model.run(game, model_results)
            except TypeError:
                result = model.run(game)
            game_id = game.get("game_id") or game.get("canonical_game_id") or ""
            validate_model_contract(result, str(game_id))
            model_results[result["model_name"]] = result

        container = dict(game)
        container["models"] = model_results
        multi_output.append(container)

    return multi_output


# =============================================================================
# SHARED: Write output (JSON payload + CSV) via io_helpers paths
# =============================================================================

def write_output(league: str, games_output: list[dict], version: str) -> None:
    from utils.io_helpers import get_model_runner_output_json_path

    path = get_model_runner_output_json_path(league)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "games": games_output,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def write_csv(league: str, games_output: list[dict], game_id_key: str, csv_extra_keys: list[str]) -> None:
    from utils.io_helpers import get_model_runner_output_csv_path

    path = get_model_runner_output_csv_path(league)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for game in games_output:
        row_base = {game_id_key: game.get(game_id_key, "")}
        if "game_date" in csv_extra_keys:
            row_base["game_date"] = game.get("game_date", "")
        for model_name, model in game["models"].items():
            row = dict(row_base)
            row["model_name"] = model_name
            row["total_projection"] = model.get("total_projection")
            row["home_line_proj"] = model.get("home_line_proj")
            row["spread_pick"] = model.get("spread_pick")
            row["total_pick"] = model.get("total_pick")
            row["spread_edge"] = model.get("spread_edge")
            row["total_edge"] = model.get("total_edge")
            row["parlay_edge_score"] = model.get("parlay_edge_score")
            rows.append(row)

    sort_keys = [game_id_key] + (["game_date"] if "game_date" in csv_extra_keys else []) + ["model_name"]
    rows.sort(key=lambda r: tuple(r.get(k, "") for k in sort_keys))

    fieldnames = list(rows[0].keys()) if rows else []
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# =============================================================================
# NBA: Registry, sort key, load from io_helpers
# =============================================================================

def run_nba() -> None:
    from utils.io_helpers import load_game_state, get_model_runner_output_json_path, get_model_runner_output_csv_path

    from eng.models.shared.joel_baseline_model import JoelBaselineModel
    from eng.models.shared.fatigue_plus_model import FatiguePlusModel
    from eng.models.shared.monkey_darts_model import MonkeyDartsModel
    from eng.models.shared.market_pressure_model import MarketPressureModel
    from eng.models.shared.injury_model import InjuryModel
    from eng.models.shared.market_blend_model import MarketBlendModel
    from eng.models.shared.momentum_5game_model import Momentum5GameModel

    MODEL_REGISTRY = [
        JoelBaselineModel,
        FatiguePlusModel,
        InjuryModel,
        MarketPressureModel,
        MarketBlendModel,
        Momentum5GameModel,
        MonkeyDartsModel,
    ]

    games = load_game_state("nba")
    results = run_models(games, MODEL_REGISTRY, sort_key=lambda g: g.get("game_id", ""))
    write_output("nba", results, "MULTI_MODEL_V1")
    write_csv("nba", results, game_id_key="game_id", csv_extra_keys=[])

    json_path = get_model_runner_output_json_path("nba")
    csv_path = get_model_runner_output_csv_path("nba")
    log_info(f"Loaded games:        {len(games)}")
    log_info(f"JSON output:        {json_path}")
    log_info(f"CSV output:         {csv_path}")
    log_info(f"Model registry:     {len(MODEL_REGISTRY)}")


# =============================================================================
# NCAAM: Registry, sort key, load from io_helpers
# =============================================================================

def run_ncaam() -> None:
    from utils.io_helpers import load_game_state, get_model_runner_output_json_path, get_model_runner_output_csv_path

    from eng.models.ncaam.ncaam_avg_score_model import NCAAMAvgScoreModel
    from eng.models.ncaam.ncaam_momentum5_model import NCAAMMomentum5Model
    from eng.models.ncaam.ncaam_market_pressure_model import NCAAMMarketPressureModel

    MODEL_REGISTRY = [
        NCAAMAvgScoreModel,
        NCAAMMomentum5Model,
        NCAAMMarketPressureModel,
    ]

    games = load_game_state("ncaam")
    sort_key = lambda g: (g.get("game_date", ""), g.get("canonical_game_id", ""))
    results = run_models(games, MODEL_REGISTRY, sort_key=sort_key)
    write_output("ncaam", results, "NCAAM_MULTI_MODEL_V1")
    write_csv("ncaam", results, game_id_key="canonical_game_id", csv_extra_keys=["game_date"])

    json_path = get_model_runner_output_json_path("ncaam")
    csv_path = get_model_runner_output_csv_path("ncaam")
    log_info(f"Loaded games:        {len(games)}")
    log_info(f"JSON output:        {json_path}")
    log_info(f"CSV output:         {csv_path}")
    log_info(f"Model registry:     {len(MODEL_REGISTRY)}")


# =============================================================================
# ENTRYPOINT
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Run multi-model projections (NBA or NCAAM)")
    parser.add_argument("--league", required=True, choices=["nba", "ncaam"])
    parser.add_argument("--silent", action="store_true", help="Only print critical errors")
    args = parser.parse_args()
    set_silent(args.silent)
    if args.league == "nba":
        run_nba()
    else:
        run_ncaam()


if __name__ == "__main__":
    main()
