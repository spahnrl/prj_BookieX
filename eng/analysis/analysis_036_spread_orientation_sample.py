"""
analysis_036_spread_orientation_sample.py

Purpose:
Inspect 5 random BACKTEST games to confirm
spread orientation and pick mapping.
"""

import json
import random
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


def run():

    print("\n=== SPREAD ORIENTATION SAMPLE (BACKTEST ONLY) ===\n")

    backtest_games = load_json(get_latest_backtest())

    sample_games = random.sample(backtest_games, 5)

    for g in sample_games:

        game_id = g["game_id"]

        models = g.get("models", {})
        joel = models.get("Joel_Baseline_v1", {})

        context = joel.get("context_flags", {})
        proj_home = context.get("proj_home")
        proj_away = context.get("proj_away")

        if proj_home is None or proj_away is None:
            print(f"{game_id} — Missing projection values\n")
            continue

        projected_margin = proj_home - proj_away

        spread_home = g.get("spread_home")
        spread_edge = g.get("Spread Edge")
        line_bet = g.get("Line Bet")
        spread_result = g.get("spread_result")

        actual_margin = g.get("actual_margin")

        print("--------------------------------------------------")
        print(f"Game ID: {game_id}")
        print(f"Projected Margin (Home - Away): {round(projected_margin,3)}")
        print(f"Vegas Spread (Home): {spread_home}")
        print(f"Computed Spread Edge: {round(spread_edge,3)}")
        print(f"Model Pick: {line_bet}")
        print(f"Actual Margin: {actual_margin}")
        print(f"ATS Result: {spread_result}")
        print("--------------------------------------------------\n")


if __name__ == "__main__":
    run()