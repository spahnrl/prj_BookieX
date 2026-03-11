"""
analysis_037_projection_error_by_spread.py

Measures absolute projection error grouped by Vegas spread magnitude.

This isolates projection accuracy independent of betting results.
"""

import json
import math
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


def main():

    games = load_json(get_latest_backtest())

    bucket_errors = defaultdict(list)

    for g in games:

        spread_home = g.get("spread_home")
        proj = g.get("Home Line Projection")
        actual_margin = g.get("actual_margin")

        if spread_home is None or proj is None or actual_margin is None:
            continue

        abs_spread = abs(spread_home)
        bucket = get_bucket(abs_spread)

        abs_error = abs(actual_margin - proj)

        bucket_errors[bucket].append(abs_error)

    print("\n=== PROJECTION ERROR BY SPREAD SIZE ===\n")

    for bucket in sorted(bucket_errors.keys()):

        errors = bucket_errors[bucket]
        if not errors:
            continue

        print(f"Bucket: {bucket}")
        print(f"  Games: {len(errors)}")
        print(f"  Avg Absolute Error: {round(safe_mean(errors), 3)}")
        print(f"  Error StdDev: {round(safe_std(errors), 3)}")
        print()


if __name__ == "__main__":
    main()