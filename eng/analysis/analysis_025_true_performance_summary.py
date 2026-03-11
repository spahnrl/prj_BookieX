# prj_BookieX/eng/analysis/analysis_025_true_performance_summary.py

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.io_helpers import get_backtest_output_root

WIN_PAYOUT = 0.909  # assuming -110
LOSS_PAYOUT = -1.0


def get_latest_backtest_file():
    backtest_root = get_backtest_output_root("nba")
    subdirs = [d for d in backtest_root.iterdir() if d.is_dir()]
    latest_dir = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest_dir / "backtest_games.json"


def _spread_result(g: dict) -> str:
    return (g.get("selected_spread_result") or g.get("spread_result") or "").strip()


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():

    games = load_json(get_latest_backtest_file())

    wins = losses = pushes = skipped = 0
    units = 0.0

    for g in games:

        result = _spread_result(g) or None

        if result is None:
            skipped += 1
            continue

        if result == "WIN":
            wins += 1
            units += WIN_PAYOUT
        elif result == "LOSS":
            losses += 1
            units += LOSS_PAYOUT
        elif result == "PUSH":
            pushes += 1
        else:
            skipped += 1

    total_bets = wins + losses + pushes
    resolved_bets = wins + losses

    print("\n=== TRUE PERFORMANCE SUMMARY (SPREAD ONLY) ===\n")
    print("Total Bets:", total_bets)
    print("Wins:", wins)
    print("Losses:", losses)
    print("Pushes:", pushes)
    print("Skipped:", skipped)

    if resolved_bets > 0:
        win_rate = wins / resolved_bets
        roi = units / resolved_bets
        print("\nWin Rate:", round(win_rate, 3))
        print("Net Units:", round(units, 2))
        print("ROI per Bet:", round(roi, 3))
    else:
        print("\nNo resolved bets.")


if __name__ == "__main__":
    main()