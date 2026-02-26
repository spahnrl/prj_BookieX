# prj_BookieX/eng/analysis/analysis_020_spread_projection_validation.py

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

    for g in games:

        proj = g.get("Home Line Projection")
        spread_home = g.get("spread_home")
        actual_margin = g.get("actual_margin")

        if None in (proj, spread_home, actual_margin):
            continue

        # Model says home covers if projection > market line
        model_home_covers = proj > spread_home

        # Reality: home covers if actual margin > market line
        actual_home_covers = actual_margin > spread_home

        total += 1
        if model_home_covers == actual_home_covers:
            correct += 1

    print("\n=== PROJECTION VS REALITY CHECK ===\n")
    print("Games Evaluated:", total)
    print("Directional Accuracy:", round(correct / total, 3))


if __name__ == "__main__":
    main()