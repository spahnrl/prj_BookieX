"""
analysis_030_projection_math_validation.py

PROJECTION MATH VALIDATION

This script verifies whether spread_edge is defined as:

A) projection - vegas_line
or
B) vegas_line - projection

It recomputes both and measures which one matches stored spread_edge.
"""

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

MULTI_MODEL_PATH = PROJECT_ROOT / "data/view/nba_games_multi_model_v1.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def almost_equal(a, b, tol=1e-6):
    return abs(a - b) < tol


def main():

    payload = load_json(MULTI_MODEL_PATH)
    games = payload["games"]

    projection_minus_line_matches = 0
    line_minus_projection_matches = 0
    total_checked = 0

    for g in games:

        joel = g.get("models", {}).get("Joel_Baseline_v1", {})
        if not joel:
            continue

        proj = joel.get("home_line_proj")
        stored_edge = joel.get("spread_edge")
        spread_home = g.get("spread_home_last")

        if None in (proj, stored_edge, spread_home):
            continue

        calc_a = proj - spread_home
        calc_b = spread_home - proj

        if almost_equal(calc_a, stored_edge):
            projection_minus_line_matches += 1

        if almost_equal(calc_b, stored_edge):
            line_minus_projection_matches += 1

        total_checked += 1

    print("\n=== PROJECTION MATH VALIDATION ===\n")
    print("Games Checked:", total_checked)
    print("Matches (projection - line):", projection_minus_line_matches)
    print("Matches (line - projection):", line_minus_projection_matches)

    if line_minus_projection_matches > projection_minus_line_matches:
        print("\nCONCLUSION: spread_edge = vegas_line - projection")
    elif projection_minus_line_matches > line_minus_projection_matches:
        print("\nCONCLUSION: spread_edge = projection - vegas_line")
    else:
        print("\nCONCLUSION: Inconclusive or mixed definition")


if __name__ == "__main__":
    main()