# eng/analysis/analysis_007_model_edge_correlation.py

import json
from pathlib import Path
from itertools import combinations
import math

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = PROJECT_ROOT / "data/view/nba_games_multi_model_v1.json"


def load_data():
    with INPUT_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["games"]


def pearson_corr(x, y):
    n = len(x)
    if n == 0:
        return None

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    num = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    den_x = math.sqrt(sum((a - mean_x) ** 2 for a in x))
    den_y = math.sqrt(sum((b - mean_y) ** 2 for b in y))

    if den_x == 0 or den_y == 0:
        return None

    return num / (den_x * den_y)


def analyze(games):

    # model_name -> {game_id: edge}
    model_edges = {}

    for game in games:
        game_id = game["game_id"]
        models = game.get("models", {})

        for model_name, model in models.items():

            edge = model.get("spread_edge")  # <- critical fix

            if edge is not None:
                model_edges.setdefault(model_name, {})[game_id] = edge

    print("=== MODEL EDGE CORRELATION MATRIX (Spread) ===\n")

    model_names = sorted(model_edges.keys())

    for m1, m2 in combinations(model_names, 2):

        common_games = (
            set(model_edges[m1].keys())
            & set(model_edges[m2].keys())
        )

        if not common_games:
            continue

        edges1 = [model_edges[m1][gid] for gid in common_games]
        edges2 = [model_edges[m2][gid] for gid in common_games]

        corr = pearson_corr(edges1, edges2)

        if corr is not None:
            print(f"{m1} vs {m2}:  Correlation = {corr:.4f}")
        else:
            print(f"{m1} vs {m2}:  Correlation = N/A")

    print("\n=== END REPORT ===")


def main():
    games = load_data()
    analyze(games)


if __name__ == "__main__":
    main()