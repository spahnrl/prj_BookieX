"""
analysis_032_projection_direction_probe.py

PROJECTION DIRECTION PROBE

This determines whether home_line_proj is aligned
or inverted relative to actual game margin.

If projection is correct:
    sign(home_line_proj - spread_home) should align
    with sign(actual_margin - spread_home)

If projection is inverted:
    it will align in the opposite direction.
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


def sign(x):
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def main():

    games = load_json(get_latest_backtest())

    aligned = 0
    inverted = 0
    total = 0

    for g in games:

        proj = g.get("Home Line Projection")
        spread_home = g.get("spread_home")
        actual_margin = g.get("actual_margin")

        if None in (proj, spread_home, actual_margin):
            continue

        proj_edge = proj - spread_home
        actual_edge = actual_margin - spread_home

        if sign(proj_edge) == sign(actual_edge):
            aligned += 1

        if sign(proj_edge) == -sign(actual_edge):
            inverted += 1

        total += 1

    print("\n=== PROJECTION DIRECTION PROBE ===\n")
    print("Games Checked:", total)
    print("Aligned with Reality:", aligned)
    print("Inverted vs Reality:", inverted)

    if inverted > aligned:
        print("\nCONCLUSION: Projection direction is inverted.")
    elif aligned > inverted:
        print("\nCONCLUSION: Projection direction is correctly aligned.")
    else:
        print("\nCONCLUSION: Inconclusive.")


if __name__ == "__main__":
    main()