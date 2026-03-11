# eng/analysis_002_performance_by_bucket.py

import json
import sys
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.io_helpers import get_backtest_output_root


def get_latest_backtest_file():
    backtest_root = get_backtest_output_root("nba")
    subdirs = [d for d in backtest_root.iterdir() if d.is_dir()]
    if not subdirs:
        raise RuntimeError("No backtest directories found.")

    latest_dir = max(subdirs, key=lambda d: d.stat().st_mtime)
    file_path = latest_dir / "backtest_games.json"

    if not file_path.exists():
        raise RuntimeError(f"No backtest_games.json in {latest_dir}")

    return file_path


def _spread_result(g: dict) -> str:
    return (g.get("selected_spread_result") or g.get("spread_result") or "").strip()


def _total_result(g: dict) -> str:
    return (g.get("selected_total_result") or g.get("total_result") or "").strip()


def _spread_edge(g: dict):
    return g.get("selected_spread_edge") if g.get("selected_spread_edge") is not None else g.get("Spread Edge")


def _total_edge(g: dict):
    return g.get("selected_total_edge") if g.get("selected_total_edge") is not None else g.get("Total Edge")


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
    return _spread_result(g) == "WIN"


def evaluate_total(g):
    return _total_result(g) == "WIN"

def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(INPUT_PATH)

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        games = json.load(f)
    spread_buckets = {}
    total_buckets = {}

    for g in games:
        spread_edge = _spread_edge(g)
        spread_result = _spread_result(g)

        if spread_edge is not None:
            bucket = bucket_label(abs(float(spread_edge)))
            win = (spread_result == "WIN")
            spread_buckets.setdefault(bucket, []).append(win)

        total_edge = _total_edge(g)
        total_result = _total_result(g)

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