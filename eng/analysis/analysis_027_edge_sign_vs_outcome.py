# prj_BookieX/eng/analysis/analysis_027_edge_sign_vs_outcome.py

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

    correct = total = 0
    skipped = 0

    for g in games:

        edge = g.get("Spread Edge")
        spread_home = g.get("spread_home")
        actual_margin = g.get("actual_margin")

        if None in (edge, spread_home, actual_margin):
            skipped += 1
            continue

        # Determine actual outcome
        home_covers = actual_margin > spread_home
        away_covers = actual_margin < spread_home

        # Test inverted mapping hypothesis
        if edge < 0:
            predicted_correct = away_covers
        elif edge > 0:
            predicted_correct = home_covers
        else:
            skipped += 1
            continue

        total += 1
        if predicted_correct:
            correct += 1

    print("\n=== EDGE SIGN VS ACTUAL OUTCOME (INVERSION TEST) ===\n")
    print("Games Checked:", total)
    print("Correct (Inverted Hypothesis):", correct)
    print("Skipped:", skipped)

    if total > 0:
        print("Accuracy:", round(correct / total, 3))
    else:
        print("No eligible games found.")


if __name__ == "__main__":
    main()