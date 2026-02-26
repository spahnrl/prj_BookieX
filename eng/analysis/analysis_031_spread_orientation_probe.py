"""
analysis_031_spread_orientation_probe.py

SPREAD ORIENTATION PROBE

This script determines whether spread_home is aligned
with home margin convention or inverted.

It evaluates two possible cover definitions:

Definition A:
    Home covers if actual_margin > spread_home

Definition B:
    Home covers if actual_margin + spread_home > 0

We compare both against actual spread_result labels
to determine which orientation matches reality.
"""

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_ROOT = PROJECT_ROOT / "eng/outputs/backtests"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_backtest():
    subdirs = [d for d in BACKTEST_ROOT.iterdir() if d.is_dir()]
    latest = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest / "backtest_games.json"


def main():

    games = load_json(get_latest_backtest())

    total = 0
    match_A = 0
    match_B = 0

    for g in games:

        actual_margin = g.get("actual_margin")
        spread_home = g.get("spread_home")
        spread_result = g.get("spread_result")

        if None in (actual_margin, spread_home, spread_result):
            continue

        total += 1

        # Definition A
        home_covers_A = actual_margin > spread_home

        # Definition B
        home_covers_B = (actual_margin + spread_home) > 0

        # Determine true home cover from result
        if spread_result == "WIN":
            true_home_cover = (g.get("Line Bet") == "HOME")
        elif spread_result == "LOSS":
            true_home_cover = (g.get("Line Bet") != "HOME")
        else:
            continue  # skip pushes

        if home_covers_A == true_home_cover:
            match_A += 1

        if home_covers_B == true_home_cover:
            match_B += 1

    print("\n=== SPREAD ORIENTATION PROBE ===\n")
    print("Games Checked:", total)
    print("Definition A Matches:", match_A)
    print("Definition B Matches:", match_B)

    if match_A > match_B:
        print("\nCONCLUSION: spread_home aligned with margin (actual_margin > spread_home)")
    elif match_B > match_A:
        print("\nCONCLUSION: spread_home requires sign inversion (actual_margin + spread_home > 0)")
    else:
        print("\nCONCLUSION: Inconclusive or identical match rates")


if __name__ == "__main__":
    main()