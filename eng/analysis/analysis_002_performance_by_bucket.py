# eng/analysis_002_performance_by_bucket.py

import json
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
from pathlib import Path

BACKTEST_ROOT = PROJECT_ROOT / "eng/outputs/backtests"

def get_latest_backtest_file():
    subdirs = [d for d in BACKTEST_ROOT.iterdir() if d.is_dir()]
    if not subdirs:
        raise RuntimeError("No backtest directories found.")

    latest_dir = max(subdirs, key=lambda d: d.stat().st_mtime)
    file_path = latest_dir / "backtest_games.json"

    if not file_path.exists():
        raise RuntimeError(f"No backtest_games.json in {latest_dir}")

    return file_path

INPUT_PATH = get_latest_backtest_file()
def bucket_label(value):
    if value < 1:
        return "0-1"
    elif value < 2:
        return "1-2"
    elif value < 4:
        return "2-4"
    elif value < 8:
        return "4-8"
    else:
        return "8+"

def evaluate_spread(g):
    return g.get("spread_result") == "WIN"

def evaluate_total(g):
    return g.get("total_result") == "WIN"

def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(INPUT_PATH)

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        games = json.load(f)
    spread_buckets = {}
    total_buckets = {}

    for g in games:
        spread_edge = g.get("Spread Edge")
        spread_result = g.get("spread_result")

        if spread_edge is not None:
            bucket = bucket_label(abs(float(spread_edge)))
            win = (spread_result == "WIN")
            spread_buckets.setdefault(bucket, []).append(win)

        total_edge = g.get("Total Edge")
        total_result = g.get("total_result")

        if total_edge is not None:
            bucket = bucket_label(abs(float(total_edge)))
            win = (total_result == "WIN")
            total_buckets.setdefault(bucket, []).append(win)

    print("\n=== SPREAD PERFORMANCE BY EDGE BUCKET ===")
    for bucket in sorted(spread_buckets.keys()):
        results = spread_buckets[bucket]
        win_rate = np.mean(results)
        print(f"{bucket}: Count={len(results)} WinRate={win_rate:.3f}")

    print("\n=== TOTAL PERFORMANCE BY EDGE BUCKET ===")
    for bucket in sorted(total_buckets.keys()):
        results = total_buckets[bucket]
        win_rate = np.mean(results)
        print(f"{bucket}: Count={len(results)} WinRate={win_rate:.3f}")

if __name__ == "__main__":
    main()