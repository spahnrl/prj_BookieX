# prj_BookieX/eng/analysis/analysis_022B_spread_edge_pick_consistency.py

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

    consistent = inconsistent = skipped = 0

    for g in games:

        edge = g.get("Spread Edge")
        pick = g.get("Line Bet")

        if edge is None or pick is None:
            skipped += 1
            continue

        if edge == 0:
            skipped += 1
            continue

        expected_pick = "HOME" if edge < 0 else "AWAY"

        if pick == expected_pick:
            consistent += 1
        else:
            inconsistent += 1

    total = consistent + inconsistent

    print("\n=== SPREAD EDGE ↔ PICK CONSISTENCY AUDIT ===\n")
    print("Games Checked:", total)
    print("Consistent:", consistent)
    print("Inconsistent:", inconsistent)
    print("Skipped:", skipped)

    if total > 0:
        print("Consistency Rate:", round(consistent / total, 3))
    else:
        print("No eligible games found.")


if __name__ == "__main__":
    main()