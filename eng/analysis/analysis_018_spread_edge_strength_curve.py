# eng/analysis/analysis_018_spread_edge_strength_curve.py

"""
SPREAD EDGE STRENGTH CURVE
Backtest-only version.
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

FINAL_PATH = PROJECT_ROOT / "data/view/final_game_view.json"
BACKTEST_ROOT = PROJECT_ROOT / "eng/outputs/backtests"


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_backtest():
    subdirs = [d for d in BACKTEST_ROOT.iterdir() if d.is_dir()]
    latest = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest / "backtest_games.json"


def main():

    games = load_json(FINAL_PATH)
    backtest = load_json(get_latest_backtest())

    # Only use games that exist in backtest
    backtest_lookup = {g["game_id"]: g for g in backtest}

    eligible = []

    for g in games:

        game_id = g["game_id"]

        if game_id not in backtest_lookup:
            continue

        edge = g.get("Spread Edge")

        if edge is None:
            continue

        result = backtest_lookup[game_id].get("spread_result")

        eligible.append({
            "edge": abs(edge),
            "win": 1 if result == "WIN" else 0
        })

    if not eligible:
        print("No eligible spread records found.")
        return

    eligible.sort(key=lambda x: x["edge"])

    n = len(eligible)
    bucket_size = n // 10

    print("\n=== SPREAD EDGE STRENGTH DECILE REPORT (BACKTEST FILTERED) ===\n")

    for i in range(10):

        start = i * bucket_size
        end = (i + 1) * bucket_size if i < 9 else n

        bucket = eligible[start:end]

        if not bucket:
            continue

        avg_edge = sum(x["edge"] for x in bucket) / len(bucket)
        win_rate = sum(x["win"] for x in bucket) / len(bucket)

        print(f"Decile {i+1}")
        print(f"  Games: {len(bucket)}")
        print(f"  Avg |Edge|: {round(avg_edge, 3)}")
        print(f"  Win Rate: {round(win_rate, 3)}")
        print()

    overall = sum(x["win"] for x in eligible) / len(eligible)
    print(f"Overall Win Rate: {round(overall, 4)}\n")


if __name__ == "__main__":
    main()