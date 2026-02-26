# prj_BookieX/eng/analysis/analysis_021_spread_result_inversion_test.py

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_ROOT = PROJECT_ROOT / "eng/outputs/backtests"


def get_latest_backtest_file():
    subdirs = [d for d in BACKTEST_ROOT.iterdir() if d.is_dir()]
    latest_dir = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest_dir / "backtest_games.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():

    games = load_json(get_latest_backtest_file())

    correct = incorrect = skipped = 0

    for g in games:

        pick = g.get("Line Bet")
        spread_home = g.get("spread_home")
        actual_margin = g.get("actual_margin")
        spread_result = g.get("spread_result")

        if None in (pick, spread_home, actual_margin, spread_result):
            skipped += 1
            continue

        # Determine if HOME covered
        home_covers = actual_margin > spread_home

        # Determine if AWAY covered
        away_covers = actual_margin < spread_home

        # Determine if the PICKED side covered
        if pick == "HOME":
            picked_side_won = home_covers
        elif pick == "AWAY":
            picked_side_won = away_covers
        else:
            skipped += 1
            continue

        # Compare to stored backtest result
        stored_win = (spread_result == "WIN")

        if picked_side_won == stored_win:
            correct += 1
        else:
            incorrect += 1

    total = correct + incorrect

    print("\n=== SPREAD RESULT VALIDATION (PICK-AWARE) ===\n")
    print("Games Checked:", total)
    print("Correctly Labeled:", correct)
    print("Incorrectly Labeled:", incorrect)
    print("Skipped:", skipped)

    if total > 0:
        print("Backtest Label Accuracy:", round(correct / total, 3))
    else:
        print("No eligible games found.")


if __name__ == "__main__":
    main()