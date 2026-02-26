"""
analysis_035_projection_component_breakdown.py

JOEL BASELINE PROJECTION COMPONENT BREAKDOWN

This script inspects:

- proj_home
- proj_away
- home_line_proj
- actual_margin

Goal:
Determine whether projected margin is computed correctly
or inverted at the source.
"""

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MULTI_MODEL_PATH = PROJECT_ROOT / "data/view/nba_games_multi_model_v1.json"
BACKTEST_ROOT = PROJECT_ROOT / "eng/outputs/backtests"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_backtest():
    subdirs = [d for d in BACKTEST_ROOT.iterdir() if d.is_dir()]
    latest = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest / "backtest_games.json"


def sign(x):
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def main():

    multi_payload = load_json(MULTI_MODEL_PATH)
    multi_games = {g["game_id"]: g for g in multi_payload["games"]}

    backtest_games = load_json(get_latest_backtest())

    correct_margin_sign = 0
    inverted_margin_sign = 0
    total = 0

    for g in backtest_games:

        game_id = g["game_id"]
        multi_game = multi_games.get(game_id)

        if not multi_game:
            continue

        joel = multi_game.get("models", {}).get("Joel_Baseline_v1", {})
        if not joel:
            continue

        proj_home = joel.get("context_flags", {}).get("proj_home")
        proj_away = joel.get("context_flags", {}).get("proj_away")
        home_line_proj = joel.get("home_line_proj")
        actual_margin = g.get("actual_margin")

        if None in (proj_home, proj_away, home_line_proj, actual_margin):
            continue

        # Recompute projected margin explicitly
        computed_margin = proj_home - proj_away

        # Compare signs
        if sign(computed_margin) == sign(actual_margin):
            correct_margin_sign += 1

        if sign(computed_margin) == -sign(actual_margin):
            inverted_margin_sign += 1

        total += 1

    print("\n=== JOEL BASELINE MARGIN SIGN TEST ===\n")
    print("Games Checked:", total)
    print("Projected Margin Sign Correct:", correct_margin_sign)
    print("Projected Margin Sign Inverted:", inverted_margin_sign)

    if inverted_margin_sign > correct_margin_sign:
        print("\nCONCLUSION: proj_home and proj_away margin is inverted.")
    else:
        print("\nCONCLUSION: proj_home - proj_away sign is correct.")


if __name__ == "__main__":
    main()