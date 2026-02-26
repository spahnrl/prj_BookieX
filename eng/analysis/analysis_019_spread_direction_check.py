# eng/analysis/analysis_019_spread_direction_check.py

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

FINAL_PATH = PROJECT_ROOT / "data/view/final_game_view.json"
BACKTEST_ROOT = PROJECT_ROOT / "eng/outputs/backtests"


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_backtest():
    subdirs = [d for d in BACKTEST_ROOT.iterdir() if d.is_dir()]
    latest = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest / "backtest_games.json"


def main():

    games = load_json(FINAL_PATH)
    backtest = load_json(get_latest_backtest())

    backtest_lookup = {g["game_id"]: g for g in backtest}

    pos_wins = 0
    pos_total = 0
    neg_wins = 0
    neg_total = 0

    for g in games:

        game_id = g["game_id"]

        if game_id not in backtest_lookup:
            continue

        edge = g.get("Spread Edge")
        if edge is None:
            continue

        result = backtest_lookup[game_id].get("spread_result")

        if edge > 0:
            pos_total += 1
            if result == "WIN":
                pos_wins += 1

        if edge < 0:
            neg_total += 1
            if result == "WIN":
                neg_wins += 1

    print("\n=== SPREAD DIRECTIONAL CHECK (BACKTEST FILTERED) ===\n")

    print("Positive Edge")
    print("  Games:", pos_total)
    print("  Win Rate:", round(pos_wins / pos_total, 3))
    print()

    print("Negative Edge")
    print("  Games:", neg_total)
    print("  Win Rate:", round(neg_wins / neg_total, 3))
    print()


if __name__ == "__main__":
    main()