"""
eng/analysis/analysis_gen_003_bias_detection.py

Sport-agnostic bias detection over backtest results. Uses the latest backtest
run in data/{league}/backtests/ (same pathing as backtest_gen_runner) and
generic column names (HOME_SCORE, AWAY_SCORE, selected_* / Total Bet, Line Bet)
so logic works for both NBA and NCAAM.

Usage:
  python eng/analysis/analysis_gen_003_bias_detection.py
  python eng/analysis/analysis_gen_003_bias_detection.py --league ncaam
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def get_backtest_root(league: str) -> Path:
    """data/{league}/backtests/ (aligned with backtest_gen_runner)."""
    league = (league or "nba").strip().lower()
    if league not in ("nba", "ncaam"):
        raise ValueError("--league must be nba or ncaam")
    return PROJECT_ROOT / "data" / league / "backtests"


def get_latest_backtest_dir(league: str) -> Path:
    """Latest backtest_* folder in data/{league}/backtests/ by modification time."""
    root = get_backtest_root(league)
    if not root.exists():
        raise FileNotFoundError(f"Backtest root not found: {root}")
    subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
    if not subdirs:
        raise FileNotFoundError(f"No backtest_* directories in {root}")
    return max(subdirs, key=lambda d: d.stat().st_mtime)


def get_latest_backtest_games_path(league: str) -> Path:
    """Path to backtest_games.json in the latest backtest run."""
    return get_latest_backtest_dir(league) / "backtest_games.json"


# -----------------------------------------------------------------------------
# Normalize game row to generic names (works for NBA and NCAAM backtest output)
# -----------------------------------------------------------------------------


def _norm(g: dict, *keys, default=None):
    for k in keys:
        v = g.get(k)
        if v is not None and v != "":
            return v
    return default


def normalize_game(g: dict) -> dict:
    """
    Map backtest game row to generic names so bias logic is sport-agnostic.
    HOME_SCORE / AWAY_SCORE: from home_score|home_points, away_score|away_points.
    TOTAL_PICK / SPREAD_PICK: from selected_* or legacy Total Bet / Line Bet.
    SPREAD_HOME: market_spread_home or spread_home.
    """
    home_score = _norm(g, "home_score", "home_points")
    away_score = _norm(g, "away_score", "away_points")
    spread_home = _norm(g, "market_spread_home", "spread_home")
    total_pick = (_norm(g, "selected_total_pick") or _norm(g, "Total Bet") or "").strip().upper()
    spread_pick_raw = (_norm(g, "selected_spread_pick") or _norm(g, "Line Bet") or "").strip()
    home_team = (_norm(g, "home_team_display", "home_team") or "").strip().upper()
    away_team = (_norm(g, "away_team_display", "away_team") or "").strip().upper()

    # Normalize spread pick to HOME | AWAY for favorite/dog logic
    if spread_pick_raw.upper() in ("HOME", "AWAY"):
        spread_pick_side = spread_pick_raw.upper()
    elif home_team and spread_pick_raw.upper() == home_team:
        spread_pick_side = "HOME"
    elif away_team and spread_pick_raw.upper() == away_team:
        spread_pick_side = "AWAY"
    else:
        spread_pick_side = ""

    total_result = _norm(g, "selected_total_result", "total_result") or ""
    spread_result = _norm(g, "selected_spread_result", "spread_result") or ""
    parlay_result = _norm(g, "selected_parlay_result", "parlay_result") or ""

    try:
        spread_home_num = float(spread_home) if spread_home is not None and spread_home != "" else None
    except (TypeError, ValueError):
        spread_home_num = None

    return {
        "HOME_SCORE": home_score,
        "AWAY_SCORE": away_score,
        "SPREAD_HOME": spread_home_num,
        "TOTAL_PICK": total_pick,
        "SPREAD_PICK": spread_pick_side,
        "TOTAL_RESULT": total_result,
        "SPREAD_RESULT": spread_result,
        "PARLAY_RESULT": parlay_result,
        "home_fatigue_flag": g.get("home_fatigue_flag"),
        "away_fatigue_flag": g.get("away_fatigue_flag"),
        "home_away_3pt_pct_diff": g.get("home_away_3pt_pct_diff"),
    }


def win_rate(results) -> float:
    return float(np.mean(results)) if results else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bias detection over latest backtest (NBA or NCAAM)."
    )
    parser.add_argument(
        "--league",
        choices=["nba", "ncaam"],
        default="nba",
        help="League whose backtest to analyze (default: nba)",
    )
    args = parser.parse_args()
    league = args.league.strip().lower()

    input_path = get_latest_backtest_games_path(league)
    if not input_path.exists():
        raise FileNotFoundError(f"Backtest games not found: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        games = json.load(f)

    if not isinstance(games, list):
        raise ValueError("backtest_games.json must be a list of game rows")

    over_results = []
    under_results = []
    fav_results = []
    dog_results = []
    fatigue_results = []
    non_fatigue_results = []
    high_3pt_diff_results = []
    low_3pt_diff_results = []

    for g in games:
        n = normalize_game(g)
        total_pick = n["TOTAL_PICK"]
        total_result = n["TOTAL_RESULT"]
        spread_pick = n["SPREAD_PICK"]
        spread_home = n["SPREAD_HOME"]
        spread_result = n["SPREAD_RESULT"]
        parlay_result = n["PARLAY_RESULT"]

        # ----- OVER vs UNDER -----
        if total_pick == "OVER" and total_result:
            over_results.append(total_result == "WIN")
        if total_pick == "UNDER" and total_result:
            under_results.append(total_result == "WIN")

        # ----- Favorite vs Dog -----
        if spread_pick and spread_home is not None and spread_result:
            home_is_fav = spread_home < 0
            bet_on_home = spread_pick == "HOME"
            is_favorite_pick = (home_is_fav and bet_on_home) or (not home_is_fav and not bet_on_home)
            if is_favorite_pick:
                fav_results.append(spread_result == "WIN")
            else:
                dog_results.append(spread_result == "WIN")

        # ----- Fatigue Bias (NBA-style; NCAAM may have no flags) -----
        if parlay_result:
            if n.get("home_fatigue_flag") or n.get("away_fatigue_flag"):
                fatigue_results.append(parlay_result == "WIN")
            else:
                non_fatigue_results.append(parlay_result == "WIN")

        # ----- 3PT Diff Bias (NBA-style; NCAAM may have no field) -----
        diff = n.get("home_away_3pt_pct_diff")
        if diff is not None and parlay_result:
            if abs(diff) > 0.05:
                high_3pt_diff_results.append(parlay_result == "WIN")
            else:
                low_3pt_diff_results.append(parlay_result == "WIN")

    backtest_dir = get_latest_backtest_dir(league)
    print(f"\nLeague:        {league.upper()}")
    print(f"Backtest dir:  {backtest_dir}")
    print(f"Games loaded:  {len(games)}")

    print("\n=== OVER vs UNDER ===")
    print(f"OVER WinRate:  {win_rate(over_results):.3f}  Count={len(over_results)}")
    print(f"UNDER WinRate: {win_rate(under_results):.3f}  Count={len(under_results)}")

    print("\n=== FAVORITES vs DOGS ===")
    print(f"Favorite WinRate: {win_rate(fav_results):.3f}  Count={len(fav_results)}")
    print(f"Dog WinRate:      {win_rate(dog_results):.3f}  Count={len(dog_results)}")

    print("\n=== FATIGUE vs NON-FATIGUE ===")
    if fatigue_results or non_fatigue_results:
        print(f"Fatigue WinRate:     {win_rate(fatigue_results):.3f}  Count={len(fatigue_results)}")
        print(f"Non-Fatigue WinRate: {win_rate(non_fatigue_results):.3f}  Count={len(non_fatigue_results)}")
    else:
        print("(No fatigue flags in backtest data — NBA-only or missing field)")

    print("\n=== HIGH 3PT DIFF vs LOW ===")
    if high_3pt_diff_results or low_3pt_diff_results:
        print(f"High Diff WinRate: {win_rate(high_3pt_diff_results):.3f}  Count={len(high_3pt_diff_results)}")
        print(f"Low Diff WinRate:  {win_rate(low_3pt_diff_results):.3f}  Count={len(low_3pt_diff_results)}")
    else:
        print("(No 3PT diff in backtest data — NBA-only or missing field)")


if __name__ == "__main__":
    main()
