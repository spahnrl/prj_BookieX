"""
analysis_036_large_spread_behavior.py

Diagnose performance behavior as Vegas spread magnitude increases.

Uses latest backtest_games.json (graded results).
"""

import json
import math
from pathlib import Path
from collections import defaultdict


# ------------------------------------------------------------------
# PATH RESOLUTION (Same Pattern as analysis_034)
# ------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_ROOT = PROJECT_ROOT / "eng/outputs/backtests"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_backtest():
    subdirs = [d for d in BACKTEST_ROOT.iterdir() if d.is_dir()]
    latest = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest / "backtest_games.json"


# ------------------------------------------------------------------
# BUCKET CONFIG
# ------------------------------------------------------------------

SPREAD_BUCKETS = [
    (0, 3),
    (3, 6),
    (6, 9),
    (9, 12),
    (12, 100)
]


def get_bucket(abs_spread):
    for low, high in SPREAD_BUCKETS:
        if low <= abs_spread < high:
            return f"{low}–{high}"
    return "OTHER"


def safe_mean(values):
    return sum(values) / len(values) if values else 0


def safe_std(values):
    if not values:
        return 0
    mean = safe_mean(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------

def main():

    games = load_json(get_latest_backtest())

    bucket_data = defaultdict(lambda: {
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "units": 0.0,
        "actual_margins": [],
        "proj_errors": [],
        "favorite_wins": 0,
        "favorite_games": 0,
        "dog_wins": 0,
        "dog_games": 0,
        "total_games": 0
    })

    for g in games:

        spread_home = g.get("spread_home")
        result = g.get("spread_result")
        actual_margin = g.get("actual_margin")
        proj = g.get("Home Line Projection")

        if spread_home is None or result is None:
            continue

        abs_spread = abs(spread_home)
        bucket = get_bucket(abs_spread)
        bd = bucket_data[bucket]

        bd["total_games"] += 1

        # -----------------------
        # Win / Loss / Push
        # -----------------------

        if result == "WIN":
            bd["wins"] += 1
            bd["units"] += 0.91
        elif result == "LOSS":
            bd["losses"] += 1
            bd["units"] -= 1
        elif result == "PUSH":
            bd["pushes"] += 1

        # -----------------------
        # Variance
        # -----------------------

        if actual_margin is not None:
            bd["actual_margins"].append(actual_margin)

        if proj is not None and actual_margin is not None:
            bd["proj_errors"].append(actual_margin - proj)

        # -----------------------
        # Favorite vs Dog
        # -----------------------

        is_home_favorite = spread_home < 0

        if is_home_favorite:
            bd["favorite_games"] += 1
            if result == "WIN":
                bd["favorite_wins"] += 1
        else:
            bd["dog_games"] += 1
            if result == "WIN":
                bd["dog_wins"] += 1

    # ------------------------------------------------------------------
    # OUTPUT
    # ------------------------------------------------------------------

    print("\n=== LARGE SPREAD BEHAVIOR DIAGNOSTIC (BACKTEST) ===\n")

    for bucket in sorted(bucket_data.keys()):
        bd = bucket_data[bucket]

        games_count = bd["total_games"]
        if games_count == 0:
            continue

        win_rate = bd["wins"] / games_count
        roi = bd["units"] / games_count

        margin_std = safe_std(bd["actual_margins"])
        proj_error_std = safe_std(bd["proj_errors"])

        fav_wr = (
            bd["favorite_wins"] / bd["favorite_games"]
            if bd["favorite_games"] > 0 else 0
        )

        dog_wr = (
            bd["dog_wins"] / bd["dog_games"]
            if bd["dog_games"] > 0 else 0
        )

        print(f"Bucket: {bucket}")
        print(f"  Games: {games_count}")
        print(f"  Win Rate: {round(win_rate, 3)}")
        print(f"  ROI: {round(roi, 3)}")
        print(f"  Actual Margin StdDev: {round(margin_std, 3)}")
        print(f"  Projection Error StdDev: {round(proj_error_std, 3)}")
        print(f"  Favorite Win Rate: {round(fav_wr, 3)}")
        print(f"  Dog Win Rate: {round(dog_wr, 3)}")
        print()


if __name__ == "__main__":
    main()