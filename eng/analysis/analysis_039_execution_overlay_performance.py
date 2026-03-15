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

Writes execution_overlay_performance.json to the same backtest dir when run,
for use by the dashboard (Execution Overlay Backtest Reference).
"""

import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.io_helpers import get_backtest_output_root
from utils.decorators import get_ncaam_execution_overlay_from_edges
from eng.execution.build_execution_overlay import compute_overlay_from_edges

BET_PRICE = -110
PAYOUT_MULTIPLIER = 100 / abs(BET_PRICE)  # ~0.9091

ORDERED_BUCKETS = [
    "Dual Sweet Spot",
    "Spread Sweet Spot",
    "Total Sweet Spot",
    "Neutral",
    "Avoid",
    "All Games",
]

# Human-readable rule for each bucket (matches eng/execution/build_execution_overlay.py).
# ASCII only for console; dashboard can show same or richer.
BUCKET_EXPLANATIONS = {
    "Dual Sweet Spot": "Spread edge 1-4 pts, total edge 1-4 pts, total 225-242, spread line <10",
    "Spread Sweet Spot": "Spread edge 1-4 pts, spread line <12",
    "Total Sweet Spot": "Total edge 1-4 pts, total 225-242, spread line <12",
    "Neutral": "Outside sweet spot and avoid bands",
    "Avoid": "Spread edge >6 or spread >=12, or total edge >8 or total <225",
    "All Games": "All graded games",
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_backtest_dir_and_games_path(league: str):
    """Return (latest_backtest_dir, path_to_backtest_games.json)."""
    backtest_root = get_backtest_output_root(league)
    if not backtest_root.exists():
        raise FileNotFoundError(f"Backtest root not found: {backtest_root}")
    subdirs = [d for d in backtest_root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
    if not subdirs:
        raise FileNotFoundError(f"No backtest_* directories in {backtest_root}")
    latest_dir = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest_dir, latest_dir / "backtest_games.json"


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
    parser = argparse.ArgumentParser(description="Execution overlay bucket performance; writes JSON for dashboard.")
    parser.add_argument("--league", choices=["nba", "ncaam"], default="nba", help="League (default: nba)")
    args = parser.parse_args()
    league = args.league.strip().lower()

    latest_dir, games_path = get_latest_backtest_dir_and_games_path(league)
    games = load_json(games_path)

    bucket_data = defaultdict(lambda: {
        "games": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "profit": 0.0
    })

    for g in games:

        spread_result = g.get("selected_spread_result") or g.get("spread_result")
        total_result = g.get("selected_total_result") or g.get("total_result")

        if spread_result is None or total_result is None:
            continue

        if not g.get("execution_overlay"):
            spread_e = g.get("selected_spread_edge") if g.get("selected_spread_edge") is not None else g.get("Spread Edge")
            total_e = g.get("selected_total_edge") if g.get("selected_total_edge") is not None else g.get("Total Edge")
            try:
                spread_e = float(spread_e) if spread_e is not None else None
            except (TypeError, ValueError):
                spread_e = None
            try:
                total_e = float(total_e) if total_e is not None else None
            except (TypeError, ValueError):
                total_e = None
            if league == "ncaam":
                line_bet = (g.get("spread_pick") or g.get("selected_spread_pick") or "").strip()
                total_bet = (g.get("total_pick") or g.get("selected_total_pick") or "").strip()
                overlay = get_ncaam_execution_overlay_from_edges(spread_e, total_e, line_bet, total_bet)
            else:
                spread_home = g.get("market_spread_home") or g.get("spread_home") or g.get("spread_home_last")
                vegas_total = g.get("market_total") or g.get("total") or g.get("total_last")
                overlay = compute_overlay_from_edges(spread_e, total_e, spread_home, vegas_total)
            if overlay:
                g["execution_overlay"] = overlay

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
    print(f"{'Bucket':<20} {'Games':<8} {'Win%':<8} {'ROI':<8}  Explanation")
    print("-" * 90)

    buckets_for_json = []

    for bucket in ORDERED_BUCKETS:

        bd = bucket_data.get(bucket)

        if not bd or bd["games"] == 0:
            continue

        win_rate = bd["wins"] / bd["games"]
        roi = bd["profit"] / bd["games"]
        explanation = BUCKET_EXPLANATIONS.get(bucket, "")

        print(
            f"{bucket:<20} "
            f"{bd['games']:<8} "
            f"{round(win_rate,3):<8} "
            f"{round(roi,3):<8}  "
            f"{explanation}"
        )
        buckets_for_json.append({
            "Bucket": bucket,
            "Games": bd["games"],
            "Win%": round(win_rate, 4),
            "ROI": round(roi, 4),
            "Explanation": explanation,
        })

    out_path = latest_dir / "execution_overlay_performance.json"
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "league": league,
        "source_backtest_dir": latest_dir.name,
        "buckets": buckets_for_json,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\nWrote: {out_path}")


if __name__ == "__main__":
    main()