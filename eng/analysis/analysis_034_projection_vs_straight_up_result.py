"""
analysis_034_projection_vs_straight_up_result.py

PROJECTION vs STRAIGHT-UP RESULT

This script ignores the spread completely.

It evaluates:

Does home_line_proj correctly predict
which team wins the game outright?

This measures pure directional projection skill.
"""

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_ROOT = PROJECT_ROOT / "eng/outputs/backtests"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_backtest():
    subdirs = [d for d in BACKTEST_ROOT.iterdir() if d.is_dir()]
    latest = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest / "backtest_games.json"


def sign(x):
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def main():

    games = load_json(get_latest_backtest())

    correct = 0
    total = 0

    for g in games:

        proj = g.get("Home Line Projection")
        actual_margin = g.get("actual_margin")

        if proj is None or actual_margin is None:
            continue

        proj_winner = sign(proj)
        actual_winner = sign(actual_margin)

        if proj_winner == actual_winner:
            correct += 1

        total += 1

    print("\n=== PROJECTION vs STRAIGHT-UP RESULT ===\n")
    print("Games Checked:", total)
    print("Correct Winner Predictions:", correct)
    print("Accuracy:", round(correct / total, 3))


if __name__ == "__main__":
    main()