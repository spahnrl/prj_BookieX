# eng/analysis/analysis_006_model_performance_by_bucket.py

import json
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = PROJECT_ROOT / "data/view/nba_games_multi_model_v1.json"
BASELINE_INPUT = PROJECT_ROOT / "data/view/final_game_view.json"


def load_multi():
    with INPUT_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["games"]


def load_baseline():
    with BASELINE_INPUT.open("r", encoding="utf-8") as f:
        return {g["game_id"]: g for g in json.load(f)}


def edge_bucket(edge):
    if abs(edge) < 3:
        return "0–3"
    elif abs(edge) < 6:
        return "3–6"
    elif abs(edge) < 10:
        return "6–10"
    else:
        return "10+"


def analyze(multi_games, baseline_games):

    results = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "losses": 0}))

    for game in multi_games:

        game_id = game["game_id"]

        if game_id not in baseline_games:
            continue

        base_record = baseline_games[game_id]

        actual_total = (
            base_record.get("home_points", 0)
            + base_record.get("away_points", 0)
        )

        market_total = base_record.get("total")

        if market_total is None:
            continue

        models = game.get("models", {})

        # NEW SHAPE: dict
        for model_name, model in models.items():

            edge = model.get("total_edge")
            if edge is None:
                continue

            bucket = edge_bucket(edge)

            predicted_over = edge > 0
            actual_over = actual_total > market_total

            if predicted_over == actual_over:
                results[model_name][bucket]["wins"] += 1
            else:
                results[model_name][bucket]["losses"] += 1

    print("=== MODEL PERFORMANCE BY EDGE BUCKET ===\n")

    for model_name, buckets in results.items():
        print(model_name)

        for bucket, stats in buckets.items():
            total = stats["wins"] + stats["losses"]
            if total == 0:
                continue

            win_rate = stats["wins"] / total
            print(
                f"  {bucket}  |  Games: {total:3}  |  Win Rate: {win_rate:.3f}"
            )

        print()

    print("=== END REPORT ===")


def main():
    multi_games = load_multi()
    baseline_games = load_baseline()
    analyze(multi_games, baseline_games)


if __name__ == "__main__":
    main()