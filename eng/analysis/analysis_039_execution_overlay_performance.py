"""
analysis_039_execution_overlay_performance.py

Analyzes performance by execution overlay bucket.

Buckets:
  - Dual Sweet Spot
  - Spread Sweet Spot
  - Total Sweet Spot
  - Neutral
  - Avoid
  - All Games

Measures:
  - Games
  - Win %
  - ROI (assumes -110 pricing)
"""

import json
from pathlib import Path
from collections import defaultdict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_ROOT = PROJECT_ROOT / "eng/outputs/backtests"

BET_PRICE = -110
PAYOUT_MULTIPLIER = 100 / abs(BET_PRICE)  # ~0.9091


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_backtest():
    subdirs = [d for d in BACKTEST_ROOT.iterdir() if d.is_dir()]
    latest = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest / "backtest_games.json"


def classify_overlay(g):
    overlay = g.get("execution_overlay") or {}

    if overlay.get("dual_sweet_spot"):
        return "Dual Sweet Spot"

    if overlay.get("spread_sweet_spot") and not overlay.get("total_sweet_spot"):
        return "Spread Sweet Spot"

    if overlay.get("total_sweet_spot") and not overlay.get("spread_sweet_spot"):
        return "Total Sweet Spot"

    if overlay.get("spread_avoid") or overlay.get("total_avoid"):
        return "Avoid"

    return "Neutral"


def main():

    games = load_json(get_latest_backtest())

    bucket_data = defaultdict(lambda: {
        "games": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "profit": 0.0
    })

    for g in games:

        spread_result = g.get("spread_result")
        total_result = g.get("total_result")

        if spread_result is None or total_result is None:
            continue

        bucket = classify_overlay(g)

        for result in [spread_result, total_result]:

            if result not in ["WIN", "LOSS", "PUSH"]:
                continue

            bucket_data[bucket]["games"] += 1
            bucket_data["All Games"]["games"] += 1

            if result == "WIN":
                bucket_data[bucket]["wins"] += 1
                bucket_data[bucket]["profit"] += PAYOUT_MULTIPLIER
                bucket_data["All Games"]["wins"] += 1
                bucket_data["All Games"]["profit"] += PAYOUT_MULTIPLIER

            elif result == "LOSS":
                bucket_data[bucket]["losses"] += 1
                bucket_data[bucket]["profit"] -= 1
                bucket_data["All Games"]["losses"] += 1
                bucket_data["All Games"]["profit"] -= 1

            elif result == "PUSH":
                bucket_data[bucket]["pushes"] += 1
                bucket_data["All Games"]["pushes"] += 1

    print("\n=== EXECUTION OVERLAY PERFORMANCE ===\n")
    print(f"{'Bucket':<20} {'Games':<8} {'Win%':<8} {'ROI':<8}")
    print("-" * 50)

    ordered_buckets = [
        "Dual Sweet Spot",
        "Spread Sweet Spot",
        "Total Sweet Spot",
        "Neutral",
        "Avoid",
        "All Games"
    ]

    for bucket in ordered_buckets:

        bd = bucket_data.get(bucket)

        if not bd or bd["games"] == 0:
            continue

        win_rate = bd["wins"] / bd["games"]
        roi = bd["profit"] / bd["games"]

        print(
            f"{bucket:<20} "
            f"{bd['games']:<8} "
            f"{round(win_rate,3):<8} "
            f"{round(roi,3):<8}"
        )


if __name__ == "__main__":
    main()