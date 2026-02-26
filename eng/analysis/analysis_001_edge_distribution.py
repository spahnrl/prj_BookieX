# analysis_001_edge_distribution.py

import json
import numpy as np
from pathlib import Path

# ---------- CONFIG ----------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = PROJECT_ROOT / "data/view/final_game_view.json"

print(f'INPUT_PATH = {INPUT_PATH}')


def compute_stats(values, label):
    values = np.array(values)

    print(f"\n=== {label} ===")
    print(f"Count: {len(values)}")
    print(f"Mean: {values.mean():.4f}")
    print(f"Median: {np.median(values):.4f}")
    print(f"Std Dev: {values.std():.4f}")
    print(f"Min: {values.min():.4f}")
    print(f"Max: {values.max():.4f}")
    print(f"P10: {np.percentile(values, 10):.4f}")
    print(f"P25: {np.percentile(values, 25):.4f}")
    print(f"P50: {np.percentile(values, 50):.4f}")
    print(f"P75: {np.percentile(values, 75):.4f}")
    print(f"P90: {np.percentile(values, 90):.4f}")


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"File not found: {INPUT_PATH}")

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        games = json.load(f)

    spread_edges = [g["Spread Edge"] for g in games if g.get("Spread Edge") is not None]
    total_edges = [g["Total Edge"] for g in games if g.get("Total Edge") is not None]

    compute_stats(spread_edges, "SPREAD EDGE")
    compute_stats(total_edges, "TOTAL EDGE")


if __name__ == "__main__":
    main()