"""
analysis_033_edge_magnitude_profit_curve.py

EDGE SIGN + MAGNITUDE PROFIT CURVE

This script evaluates:

1. Performance of positive spread_edge bets
2. Performance of negative spread_edge bets
3. Performance by magnitude buckets

Goal:
Determine whether edge sign should be reversed
or whether profitability varies by magnitude.
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


def grade_unit(result):
    if result == "WIN":
        return 0.91
    if result == "LOSS":
        return -1
    return 0


def bucket_label(edge):
    mag = abs(edge)
    if mag < 2:
        return "<2"
    if mag < 4:
        return "2–4"
    if mag < 6:
        return "4–6"
    return "6+"


def main():

    games = load_json(get_latest_backtest())

    pos_stats = {"bets": 0, "wins": 0, "units": 0}
    neg_stats = {"bets": 0, "wins": 0, "units": 0}

    bucket_stats = defaultdict(lambda: {"bets": 0, "wins": 0, "units": 0})

    for g in games:

        edge = g.get("Spread Edge")
        result = g.get("spread_result")

        if edge is None or result not in ("WIN", "LOSS"):
            continue

        unit = grade_unit(result)
        bucket = bucket_label(edge)

        # Positive edge
        if edge > 0:
            pos_stats["bets"] += 1
            pos_stats["wins"] += (result == "WIN")
            pos_stats["units"] += unit

        # Negative edge
        if edge < 0:
            neg_stats["bets"] += 1
            neg_stats["wins"] += (result == "WIN")
            neg_stats["units"] += unit

        # Bucket
        bucket_stats[bucket]["bets"] += 1
        bucket_stats[bucket]["wins"] += (result == "WIN")
        bucket_stats[bucket]["units"] += unit

    print("\n=== EDGE SIGN PERFORMANCE ===\n")

    for label, stats in [("Positive Edge", pos_stats), ("Negative Edge", neg_stats)]:
        if stats["bets"] == 0:
            continue
        win_rate = stats["wins"] / stats["bets"]
        roi = stats["units"] / stats["bets"]
        print(label)
        print("  Bets:", stats["bets"])
        print("  Win Rate:", round(win_rate, 3))
        print("  ROI:", round(roi, 3))
        print()

    print("\n=== EDGE MAGNITUDE BUCKET PERFORMANCE ===\n")

    for bucket in sorted(bucket_stats.keys()):
        stats = bucket_stats[bucket]
        if stats["bets"] == 0:
            continue
        win_rate = stats["wins"] / stats["bets"]
        roi = stats["units"] / stats["bets"]
        print(bucket)
        print("  Bets:", stats["bets"])
        print("  Win Rate:", round(win_rate, 3))
        print("  ROI:", round(roi, 3))
        print()


if __name__ == "__main__":
    main()