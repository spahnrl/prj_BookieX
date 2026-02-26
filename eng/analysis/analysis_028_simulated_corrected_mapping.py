# prj_BookieX/eng/analysis/analysis_028_simulated_corrected_mapping.py

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_ROOT = PROJECT_ROOT / "eng/outputs/backtests"

WIN_PAYOUT = 0.909
LOSS_PAYOUT = -1.0


def get_latest_backtest_file():
    subdirs = [d for d in BACKTEST_ROOT.iterdir() if d.is_dir()]
    latest_dir = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest_dir / "backtest_games.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():

    games = load_json(get_latest_backtest_file())

    wins = losses = pushes = skipped = 0
    units = 0.0

    for g in games:

        edge = g.get("Spread Edge")
        spread_home = g.get("spread_home")
        actual_margin = g.get("actual_margin")

        if None in (edge, spread_home, actual_margin):
            skipped += 1
            continue

        # Simulated corrected pick mapping
        if edge < 0:
            simulated_pick = "AWAY"
        elif edge > 0:
            simulated_pick = "HOME"
        else:
            skipped += 1
            continue

        # Determine actual cover
        home_covers = actual_margin > spread_home
        away_covers = actual_margin < spread_home

        if simulated_pick == "HOME":
            won = home_covers
        else:
            won = away_covers

        if won:
            wins += 1
            units += WIN_PAYOUT
        else:
            losses += 1
            units += LOSS_PAYOUT

    total = wins + losses

    print("\n=== SIMULATED CORRECTED EDGE MAPPING ===\n")
    print("Total Bets:", total)
    print("Wins:", wins)
    print("Losses:", losses)

    if total > 0:
        win_rate = wins / total
        roi = units / total
        print("\nWin Rate:", round(win_rate, 3))
        print("Net Units:", round(units, 2))
        print("ROI per Bet:", round(roi, 3))
    else:
        print("\nNo eligible games found.")


if __name__ == "__main__":
    main()