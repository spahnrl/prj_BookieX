# eng/analysis_003_bias_detection.py

import json
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_ROOT = PROJECT_ROOT / "eng/outputs/backtests"

def get_latest_backtest_file():
    subdirs = [d for d in BACKTEST_ROOT.iterdir() if d.is_dir()]
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
        # ----- OVER vs UNDER -----
        if g.get("Total Bet") == "OVER":
            if g.get("total_result"):
                over_results.append(g["total_result"] == "WIN")

        if g.get("Total Bet") == "UNDER":
            if g.get("total_result"):
                under_results.append(g["total_result"] == "WIN")

        # ----- Favorite vs Dog -----
        if g.get("Line Bet"):
            # If spread_home is negative → home is favorite
            if g.get("spread_home") is not None:
                home_is_fav = g["spread_home"] < 0
                bet_on_home = g["Line Bet"] == "HOME"

                is_favorite_pick = (home_is_fav and bet_on_home) or (not home_is_fav and not bet_on_home)

                if is_favorite_pick:
                    fav_results.append(g["spread_result"] == "WIN")
                else:
                    dog_results.append(g["spread_result"] == "WIN")

        # ----- Fatigue Bias -----
        if g.get("home_fatigue_flag") or g.get("away_fatigue_flag"):
            fatigue_results.append(g["parlay_result"] == "WIN")
        else:
            non_fatigue_results.append(g["parlay_result"] == "WIN")

        # ----- 3PT Diff Bias -----
        diff = g.get("home_away_3pt_pct_diff")
        if diff is not None:
            if abs(diff) > 0.05:
                high_3pt_diff_results.append(g["parlay_result"] == "WIN")
            else:
                low_3pt_diff_results.append(g["parlay_result"] == "WIN")

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