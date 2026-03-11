"""
build_calibration_snapshot.py

Purpose:
Freeze backtest statistics into a deterministic calibration snapshot (Confidence Tiers).

Rules:
- Reads latest backtest_games.json for the given league from data/{league}/backtests/backtest_*/.
- Supports --league nba | ncaam.
- No model recalculation; deterministic output.
"""

import argparse
import json
import sys
import numpy as np
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.io_helpers import get_backtest_output_root


# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

CALIBRATION_VERSION = "CALIBRATION_SNAPSHOT_V1"


def _get_calibration_output_path(league: str) -> Path:
    """Canonical calibration snapshot path: data/{league}/calibration/."""
    league = (league or "nba").strip().lower()
    if league == "nba":
        from configs.leagues.league_nba import CALIBRATION_SNAPSHOT_PATH
        return CALIBRATION_SNAPSHOT_PATH
    if league == "ncaam":
        from configs.leagues.league_ncaam import CALIBRATION_SNAPSHOT_PATH
        return CALIBRATION_SNAPSHOT_PATH
    raise ValueError("--league must be nba or ncaam")


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def get_latest_backtest_file(league: str):
    """Latest backtest_* dir under data/{league}/backtests/ (aligned with backtest_gen_runner)."""
    league = (league or "nba").strip().lower()
    backtest_root = get_backtest_output_root(league)
    if not backtest_root.exists():
        raise RuntimeError(
            f"Backtest root not found for league={league}: {backtest_root}. Run backtest_gen_runner first."
        )
    subdirs = [d for d in backtest_root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
    if not subdirs:
        raise RuntimeError(
            f"No backtest_* directories found for league={league} under {backtest_root}."
        )
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


def calculate_percentiles(edge_values: list[float]) -> dict[str, float]:
    """Explicitly generate p10, p25, p50, p75, p90. Uses 0.0 when empty so keys always exist."""
    keys = ("p10", "p25", "p50", "p75", "p90")
    percentiles_q = (10, 25, 50, 75, 90)
    if not edge_values:
        return {k: 0.0 for k in keys}
    return {
        k: float(np.percentile(edge_values, q))
        for k, q in zip(keys, percentiles_q)
    }


def normalize_game_for_calibration(g: dict, league: str) -> dict:
    """Produce a flat record with Spread Edge, Total Edge, Line Bet, Total Bet, spread_result, total_result, spread_home."""
    authority = g.get("selection_authority") or ("nba_model_v1" if league == "nba" else "ncaam_model_v1")
    model_results = g.get("model_results") or {}
    auth = model_results.get(authority) or {}
    return {
        "Spread Edge": g.get("selected_spread_edge") if g.get("selected_spread_edge") is not None else auth.get("spread_edge"),
        "Total Edge": g.get("selected_total_edge") if g.get("selected_total_edge") is not None else auth.get("total_edge"),
        "Line Bet": g.get("selected_spread_pick") or auth.get("spread_pick"),
        "Total Bet": g.get("selected_total_pick") or auth.get("total_pick"),
        "spread_result": g.get("selected_spread_result") or auth.get("spread_result"),
        "total_result": g.get("selected_total_result") or auth.get("total_result"),
        "spread_home": g.get("line_spread") if g.get("line_spread") is not None else g.get("market_spread_home") or g.get("spread_home"),
    }


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def build_snapshot(league: str = "nba"):

    league = (league or "nba").strip().lower()
    if league not in ("nba", "ncaam"):
        raise ValueError("--league must be nba or ncaam")

    backtest_path, folder_name = get_latest_backtest_file(league)

    with backtest_path.open("r", encoding="utf-8") as f:
        raw_games = json.load(f)

    games = [normalize_game_for_calibration(g, league) for g in raw_games]

    # --------------------------------------------------------
    # EDGE DISTRIBUTION
    # --------------------------------------------------------

    spread_edges = [abs(float(g["Spread Edge"])) for g in games if g.get("Spread Edge") is not None]
    total_edges = [abs(float(g["Total Edge"])) for g in games if g.get("Total Edge") is not None]

    spread_percentiles = calculate_percentiles(spread_edges)
    total_percentiles = calculate_percentiles(total_edges)

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

    output_path = _get_calibration_output_path(league)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    snapshot["league"] = league

    # Validation: require p90 so downstream (e.g. build_daily_view) does not KeyError
    if "p90" not in (snapshot.get("spread_edge_percentiles") or {}):
        raise ValueError(
            "spread_edge_percentiles must contain 'p90'. "
            "Check that calibration has enough backtest games with spread edge."
        )

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)

    print(f"Calibration snapshot written: {output_path}")
    print(f"League: {league} | Backtest folder: {folder_name} | Games: {len(games)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build calibration snapshot from latest league backtest.")
    p.add_argument("--league", choices=["nba", "ncaam"], default="nba", help="League (default: nba)")
    args = p.parse_args()
    build_snapshot(league=args.league)