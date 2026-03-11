"""
analysis_038_total_direction_bias.py

Tests whether total bet direction is biased by Vegas total range.

Buckets:
  <225
  225–242
  >242

Measures:
  - % OVER vs UNDER
  - Win rate
  - Avg projection bias (proj - vegas)
"""

import json
from pathlib import Path
from collections import defaultdict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_ROOT = PROJECT_ROOT / "eng/outputs/backtests"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_backtest():
    subdirs = [d for d in BACKTEST_ROOT.iterdir() if d.is_dir()]
    latest = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest / "backtest_games.json"


def get_bucket(total):
    if total < 225:
        return "<225"
    elif total <= 242:
        return "225–242"
    else:
        return ">242"


def main():

    games = load_json(get_latest_backtest())

    bucket_data = defaultdict(lambda: {
        "over": 0,
        "under": 0,
        "wins": 0,
        "losses": 0,
        "proj_bias": []
    })

    for g in games:

        vegas_total = g.get("total")
        total_bet = g.get("Total Bet")
        total_result = g.get("total_result")
        proj_total = g.get("Total Projection")

        if None in (vegas_total, total_bet, total_result, proj_total):
            continue

        bucket = get_bucket(vegas_total)
        bd = bucket_data[bucket]

        # Direction frequency
        if total_bet == "OVER":
            bd["over"] += 1
        elif total_bet == "UNDER":
            bd["under"] += 1

        # Win/Loss
        if total_result == "WIN":
            bd["wins"] += 1
        elif total_result == "LOSS":
            bd["losses"] += 1

        # Projection bias
        bd["proj_bias"].append(proj_total - vegas_total)

    print("\n=== TOTAL DIRECTION BIAS ANALYSIS ===\n")

    for bucket in ["<225", "225–242", ">242"]:

        bd = bucket_data[bucket]
        total_games = bd["over"] + bd["under"]

        if total_games == 0:
            continue

        over_pct = bd["over"] / total_games
        win_rate = bd["wins"] / total_games
        avg_bias = sum(bd["proj_bias"]) / len(bd["proj_bias"]) if bd["proj_bias"] else 0

        print(f"Bucket: {bucket}")
        print(f"  Games: {total_games}")
        print(f"  % OVER: {round(over_pct, 3)}")
        print(f"  % UNDER: {round(1 - over_pct, 3)}")
        print(f"  Win Rate: {round(win_rate, 3)}")
        print(f"  Avg Projection Bias (Proj - Vegas): {round(avg_bias, 3)}")
        print()


if __name__ == "__main__":
    main()