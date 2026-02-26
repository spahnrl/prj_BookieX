"""
build_calibration_snapshot.py

Purpose:
Freeze Phase 1.5 backtest statistics into a deterministic
calibration_snapshot_v1.json artifact.

Rules:
- Reads latest backtest_games.json
- No model recalculation
- No re-running backtests
- Deterministic output
"""

import json
import numpy as np
from pathlib import Path
from datetime import datetime


# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_ROOT = PROJECT_ROOT / "eng/outputs/backtests"
OUTPUT_DIR = PROJECT_ROOT / "eng/calibration"

CALIBRATION_VERSION = "CALIBRATION_SNAPSHOT_V1"


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def get_latest_backtest_file():
    subdirs = [d for d in BACKTEST_ROOT.iterdir() if d.is_dir()]
    if not subdirs:
        raise RuntimeError("No backtest directories found.")

    latest_dir = max(subdirs, key=lambda d: d.stat().st_mtime)
    file_path = latest_dir / "backtest_games.json"

    if not file_path.exists():
        raise RuntimeError(f"No backtest_games.json in {latest_dir}")

    return file_path, latest_dir.name


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


def win_rate(results):
    return float(np.mean(results)) if results else None


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def build_snapshot():

    backtest_path, folder_name = get_latest_backtest_file()

    with backtest_path.open("r", encoding="utf-8") as f:
        games = json.load(f)

    # --------------------------------------------------------
    # EDGE DISTRIBUTION
    # --------------------------------------------------------

    spread_edges = [abs(float(g["Spread Edge"])) for g in games if g.get("Spread Edge") is not None]
    total_edges = [abs(float(g["Total Edge"])) for g in games if g.get("Total Edge") is not None]

    spread_percentiles = {
        "p10": float(np.percentile(spread_edges, 10)),
        "p25": float(np.percentile(spread_edges, 25)),
        "p50": float(np.percentile(spread_edges, 50)),
        "p75": float(np.percentile(spread_edges, 75)),
        "p90": float(np.percentile(spread_edges, 90)),
    }

    total_percentiles = {
        "p10": float(np.percentile(total_edges, 10)),
        "p25": float(np.percentile(total_edges, 25)),
        "p50": float(np.percentile(total_edges, 50)),
        "p75": float(np.percentile(total_edges, 75)),
        "p90": float(np.percentile(total_edges, 90)),
    }

    # --------------------------------------------------------
    # PERFORMANCE BY BUCKET
    # --------------------------------------------------------

    spread_buckets = {}
    total_buckets = {}

    for g in games:

        spread_edge = g.get("Spread Edge")
        if spread_edge is not None:
            bucket = bucket_label(abs(float(spread_edge)))
            spread_buckets.setdefault(bucket, []).append(g.get("spread_result") == "WIN")

        total_edge = g.get("Total Edge")
        if total_edge is not None:
            bucket = bucket_label(abs(float(total_edge)))
            total_buckets.setdefault(bucket, []).append(g.get("total_result") == "WIN")

    spread_bucket_win_rates = {
        bucket: win_rate(results)
        for bucket, results in spread_buckets.items()
    }

    total_bucket_win_rates = {
        bucket: win_rate(results)
        for bucket, results in total_buckets.items()
    }

    # --------------------------------------------------------
    # BIAS METRICS
    # --------------------------------------------------------

    over_results = []
    under_results = []
    fav_results = []
    dog_results = []

    for g in games:

        # OVER / UNDER
        if g.get("Total Bet") == "OVER":
            over_results.append(g.get("total_result") == "WIN")

        if g.get("Total Bet") == "UNDER":
            under_results.append(g.get("total_result") == "WIN")

        # FAVORITE / DOG
        if g.get("Line Bet") and g.get("spread_home") is not None:
            home_is_fav = g["spread_home"] < 0
            bet_on_home = g["Line Bet"] == "HOME"

            is_favorite_pick = (home_is_fav and bet_on_home) or (not home_is_fav and not bet_on_home)

            if is_favorite_pick:
                fav_results.append(g.get("spread_result") == "WIN")
            else:
                dog_results.append(g.get("spread_result") == "WIN")

    bias_baseline = {
        "over_win_rate": win_rate(over_results),
        "under_win_rate": win_rate(under_results),
        "favorite_win_rate": win_rate(fav_results),
        "dog_win_rate": win_rate(dog_results)
    }

    # --------------------------------------------------------
    # BUILD SNAPSHOT
    # --------------------------------------------------------

    snapshot = {
        "calibration_version": CALIBRATION_VERSION,
        "snapshot_date": datetime.now().strftime("%Y-%m-%d"),
        "backtest_folder_used": folder_name,
        "total_games_used": len(games),
        "spread_edge_percentiles": spread_percentiles,
        "total_edge_percentiles": total_percentiles,
        "spread_bucket_win_rates": spread_bucket_win_rates,
        "total_bucket_win_rates": total_bucket_win_rates,
        "bias_baseline": bias_baseline
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "calibration_snapshot_v1.json"

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)

    print(f"Calibration snapshot written: {output_path}")
    print(f"Backtest folder used: {folder_name}")
    print(f"Games analyzed: {len(games)}")


if __name__ == "__main__":
    build_snapshot()