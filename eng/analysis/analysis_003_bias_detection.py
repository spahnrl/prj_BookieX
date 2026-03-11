# eng/analysis_003_bias_detection.py

import json
import sys
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.io_helpers import get_backtest_output_root


def _result(g: dict, key: str) -> str:
    """Prefer current backtest schema (selected_*) with fallback to legacy keys."""
    if key == "spread_result":
        return (g.get("selected_spread_result") or g.get("spread_result") or "").strip()
    if key == "total_result":
        return (g.get("selected_total_result") or g.get("total_result") or "").strip()
    if key == "parlay_result":
        return (g.get("selected_parlay_result") or g.get("parlay_result") or "").strip()
    return (g.get(key) or "").strip()


def _pick(g: dict, key: str) -> str:
    """Prefer current schema (selected_*_pick) with fallback to legacy (Line Bet / Total Bet)."""
    if key == "spread":
        return (g.get("selected_spread_pick") or g.get("Line Bet") or "").strip()
    if key == "total":
        return (g.get("selected_total_pick") or g.get("Total Bet") or "").strip()
    return (g.get(key) or "").strip()


def get_latest_backtest_file():
    backtest_root = get_backtest_output_root("nba")
    subdirs = [d for d in backtest_root.iterdir() if d.is_dir()]
    latest_dir = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest_dir / "backtest_games.json"


def win_rate(results):
    return np.mean(results) if results else 0

def main():
    input_path = get_latest_backtest_file()

    with open(input_path, "r", encoding="utf-8") as f:
        games = json.load(f)

    # --- OVER vs UNDER ---
    over_results = []
    under_results = []

    # --- Favorites vs Dogs ---
    fav_results = []
    dog_results = []

    # --- Fatigue Bias ---
    fatigue_results = []
    non_fatigue_results = []

    # --- 3PT Differential ---
    high_3pt_diff_results = []
    low_3pt_diff_results = []

    for g in games:
        total_pick = _pick(g, "total")
        total_result = _result(g, "total_result")
        spread_pick = _pick(g, "spread")
        spread_result = _result(g, "spread_result")
        parlay_result = _result(g, "parlay_result")
        spread_home_val = g.get("spread_home") if g.get("spread_home") is not None else g.get("market_spread_home")

        # ----- OVER vs UNDER -----
        if total_pick == "OVER" and total_result:
            over_results.append(total_result == "WIN")
        if total_pick == "UNDER" and total_result:
            under_results.append(total_result == "WIN")

        # ----- Favorite vs Dog -----
        if spread_pick and spread_home_val is not None:
            home_is_fav = spread_home_val < 0
            bet_on_home = spread_pick == "HOME"

            is_favorite_pick = (home_is_fav and bet_on_home) or (not home_is_fav and not bet_on_home)
            if is_favorite_pick:
                fav_results.append(spread_result == "WIN")
            else:
                dog_results.append(spread_result == "WIN")

        # ----- Fatigue Bias -----
        if g.get("home_fatigue_flag") or g.get("away_fatigue_flag"):
            fatigue_results.append(parlay_result == "WIN")
        else:
            non_fatigue_results.append(parlay_result == "WIN")

        # ----- 3PT Diff Bias -----
        diff = g.get("home_away_3pt_pct_diff")
        if diff is not None:
            if abs(diff) > 0.05:
                high_3pt_diff_results.append(parlay_result == "WIN")
            else:
                low_3pt_diff_results.append(parlay_result == "WIN")

    print("\n=== OVER vs UNDER ===")
    print(f"OVER WinRate:  {win_rate(over_results):.3f}  Count={len(over_results)}")
    print(f"UNDER WinRate: {win_rate(under_results):.3f}  Count={len(under_results)}")

    print("\n=== FAVORITES vs DOGS ===")
    print(f"Favorite WinRate: {win_rate(fav_results):.3f}  Count={len(fav_results)}")
    print(f"Dog WinRate:      {win_rate(dog_results):.3f}  Count={len(dog_results)}")

    print("\n=== FATIGUE vs NON-FATIGUE ===")
    print(f"Fatigue WinRate:     {win_rate(fatigue_results):.3f}  Count={len(fatigue_results)}")
    print(f"Non-Fatigue WinRate: {win_rate(non_fatigue_results):.3f}  Count={len(non_fatigue_results)}")

    print("\n=== HIGH 3PT DIFF vs LOW ===")
    print(f"High Diff WinRate: {win_rate(high_3pt_diff_results):.3f}  Count={len(high_3pt_diff_results)}")
    print(f"Low Diff WinRate:  {win_rate(low_3pt_diff_results):.3f}  Count={len(low_3pt_diff_results)}")

if __name__ == "__main__":
    main()