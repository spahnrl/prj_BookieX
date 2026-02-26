# prj_BookieX/eng/analysis/analysis_026_flip_test.py

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

        result = g.get("spread_result")

        if result is None:
            skipped += 1
            continue

        # Flip the result
        if result == "WIN":
            flipped_result = "LOSS"
        elif result == "LOSS":
            flipped_result = "WIN"
        elif result == "PUSH":
            flipped_result = "PUSH"
        else:
            skipped += 1
            continue

        if flipped_result == "WIN":
            wins += 1
            units += WIN_PAYOUT
        elif flipped_result == "LOSS":
            losses += 1
            units += LOSS_PAYOUT
        elif flipped_result == "PUSH":
            pushes += 1

    total_bets = wins + losses + pushes
    resolved_bets = wins + losses

    print("\n=== FLIPPED PERFORMANCE TEST ===\n")
    print("Total Bets:", total_bets)
    print("Wins (Flipped):", wins)
    print("Losses (Flipped):", losses)
    print("Pushes:", pushes)
    print("Skipped:", skipped)

    if resolved_bets > 0:
        win_rate = wins / resolved_bets
        roi = units / resolved_bets
        print("\nFlipped Win Rate:", round(win_rate, 3))
        print("Flipped Net Units:", round(units, 2))
        print("Flipped ROI per Bet:", round(roi, 3))
    else:
        print("\nNo resolved bets.")


if __name__ == "__main__":
    main()