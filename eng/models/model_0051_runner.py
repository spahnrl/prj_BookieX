# model_0051_runner.py

import json
from pathlib import Path
from datetime import datetime, timezone
import csv

from eng.models.joel_baseline_model import JoelBaselineModel
from eng.models.fatigue_plus_model import FatiguePlusModel
from eng.models.monkey_darts_model import MonkeyDartsModel
from eng.models.market_pressure_model import MarketPressureModel
from eng.models.injury_model import InjuryModel


MODEL_REGISTRY = [
    JoelBaselineModel,
    FatiguePlusModel,
    InjuryModel,
    MonkeyDartsModel,
]

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# INPUT_PATH = PROJECT_ROOT / "data/view/final_game_view.json"
INPUT_PATH = PROJECT_ROOT / "data/view/nba_games_game_level_with_odds.json"
OUTPUT_PATH = PROJECT_ROOT / "data/view/nba_games_multi_model_v1.json"
CSV_OUTPUT_PATH = PROJECT_ROOT / "data/view/nba_games_multi_model_v1.csv"

# ===============================
# MODEL CONTRACT V1 VALIDATION
# ===============================

# REQUIRED_MODEL_KEYS = {
#     "model_name",
#     "total_projection",
#     "total_edge",
#     "total_pick",
#     "home_line_proj",
#     "spread_edge",
#     "spread_pick",
#     "parlay_edge_score",
#     "context_flags",
# }
REQUIRED_MODEL_KEYS = {
    "model_name",

    # TOTAL
    "total_projection",
    "total_distance",
    "total_edge",
    "total_pick",

    # SPREAD
    "home_line_proj",
    "spread_distance",
    "spread_edge",
    "spread_pick",

    # AGGREGATE
    "parlay_edge_score",

    # REQUIRED
    "context_flags",
}

def validate_model_contract(result: dict, game_id: str):
    """
    Enforces ModelContract_v1 compliance.
    Raises ValueError if schema mismatch detected.
    """

    if not isinstance(result, dict):
        raise ValueError(f"[ModelContractError] Game {game_id}: Model returned non-dict result")

    missing = REQUIRED_MODEL_KEYS - result.keys()
    extra = result.keys() - REQUIRED_MODEL_KEYS

    if missing:
        raise ValueError(
            f"[ModelContractError] Game {game_id}: Missing keys: {missing}"
        )

    if extra:
        raise ValueError(
            f"[ModelContractError] Game {game_id}: Unexpected keys: {extra}"
        )

    if not isinstance(result["context_flags"], dict):
        raise ValueError(
            f"[ModelContractError] Game {game_id}: context_flags must be dict"
        )



def load_games():
    with INPUT_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def run_models(games):
    models = [model_cls() for model_cls in MODEL_REGISTRY]

    multi_output = []

    for game in sorted(games, key=lambda g: g["game_id"]):

        model_results = {}

        for model in models:
            # Pass model_results for dependent models
            try:
                result = model.run(game, model_results)
            except TypeError:
                # Backward compatibility if model not yet updated
                result = model.run(game)

            # Validate ModelContract_v1 compliance
            validate_model_contract(result, game.get("game_id"))

            model_results[result["model_name"]] = result

        container = dict(game)  # copy original full game record
        container["models"] = model_results

        multi_output.append(container)

    return multi_output

def write_output(games_output):
    payload = {
        "version": "MULTI_MODEL_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "games": games_output
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

def write_csv(games_output):
    rows = []

    for game in games_output:
        game_id = game["game_id"]

        for model_name, model in game["models"].items():
            rows.append({
                "game_id": game_id,
                "model_name": model_name,

                "total_projection": model.get("total_projection"),
                "home_line_proj": model.get("home_line_proj"),

                "spread_pick": model.get("spread_pick"),
                "total_pick": model.get("total_pick"),

                "spread_edge": model.get("spread_edge"),
                "total_edge": model.get("total_edge"),
                "parlay_edge_score": model.get("parlay_edge_score"),
            })

    rows.sort(key=lambda r: (r["game_id"], r["model_name"]))

    CSV_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with CSV_OUTPUT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "game_id",
                "model_name",
                "total_projection",
                "home_line_proj",
                "spread_pick",
                "total_pick",
                "spread_edge",
                "total_edge",
                "parlay_edge_score",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

def main():
    games = load_games()
    results = run_models(games)
    write_output(results)
    write_csv(results)


if __name__ == "__main__":
    main()