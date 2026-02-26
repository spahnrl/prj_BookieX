# eng/analysis/analysis_004_model_comparison.py

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = PROJECT_ROOT / "data/view/nba_games_multi_model_v1.json"


def load_data():
    with INPUT_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["games"]


def analyze(games):

    total_games = 0
    projection_delta_sum = 0.0
    edge_delta_sum = 0.0
    edge_count = 0
    disagreement_count = 0

    for game in games:

        # New shape: models is already a dict keyed by model_name
        models = game.get("models", {})

        if "Joel_Baseline_v1" not in models or "FatiguePlus_v3" not in models:
            continue

        baseline = models["Joel_Baseline_v1"]
        fatigue = models["FatiguePlus_v3"]

        # Updated field names
        base_proj = baseline.get("home_line_proj")
        fat_proj = fatigue.get("home_line_proj")

        base_edge = baseline.get("spread_edge")
        fat_edge = fatigue.get("spread_edge")

        if base_proj is None or fat_proj is None:
            continue

        total_games += 1
        projection_delta_sum += (fat_proj - base_proj)

        if base_edge is not None and fat_edge is not None:
            edge_delta_sum += (fat_edge - base_edge)
            edge_count += 1

            # Direction disagreement
            if (base_edge > 0 and fat_edge < 0) or \
               (base_edge < 0 and fat_edge > 0):
                disagreement_count += 1

    print("=== MODEL COMPARISON REPORT ===")
    print(f"Games Compared: {total_games}")

    if total_games > 0:
        print(
            f"Avg Projection Delta (Fatigue - Baseline): "
            f"{projection_delta_sum / total_games:.4f}"
        )

    if edge_count > 0:
        print(
            f"Avg Edge Delta (Fatigue - Baseline): "
            f"{edge_delta_sum / edge_count:.4f}"
        )
        print(f"Directional Disagreements: {disagreement_count}")
    else:
        print("No edge comparisons available.")

    print("=== END REPORT ===")


def main():
    games = load_data()
    analyze(games)


if __name__ == "__main__":
    main()