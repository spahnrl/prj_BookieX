# eng/analysis/analysis_005_cross_model_edge_stats.py

import json
from pathlib import Path
import statistics

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = PROJECT_ROOT / "data/view/nba_games_multi_model_v1.json"


def load_data():
    with INPUT_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["games"]


def analyze(games):

    model_edges = {}

    for game in games:
        models = game.get("models", {})

        # New shape: dict keyed by model name
        for name, model in models.items():

            edge = model.get("spread_edge")

            if edge is not None:
                model_edges.setdefault(name, []).append(edge)

    print("=== CROSS MODEL EDGE STATS ===\n")

    for name, edges in model_edges.items():

        if not edges:
            continue

        mean_edge = statistics.mean(edges)
        std_edge = statistics.pstdev(edges) if len(edges) > 1 else 0.0
        p90_index = int(len(edges) * 0.9)
        p90 = sorted(edges)[p90_index]

        big_5 = sum(1 for e in edges if abs(e) > 5)
        big_8 = sum(1 for e in edges if abs(e) > 8)
        big_12 = sum(1 for e in edges if abs(e) > 12)

        print(f"{name}")
        print(f"  Edge Count: {len(edges)}")
        print(f"  Mean Edge: {mean_edge:.4f}")
        print(f"  Std Dev: {std_edge:.4f}")
        print(f"  90th Percentile: {p90:.4f}")
        print(f"  |Edge| > 5: {big_5}")
        print(f"  |Edge| > 8: {big_8}")
        print(f"  |Edge| > 12: {big_12}")
        print()

    print("=== END REPORT ===")


def main():
    games = load_data()
    analyze(games)


if __name__ == "__main__":
    main()