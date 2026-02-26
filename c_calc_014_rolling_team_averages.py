"""
c_calc_014_rolling_team_averages.py

Purpose
-------
Compute strict prior-game rolling averages for each team,
separately for home and away games.

Design Rules
------------
- One row per TEAM per GAME (2 rows per game)
- Rolling averages are computed BEFORE updating history
- Only status == 3 (final games) update the accumulator
- Preseason games excluded
- No leakage
- No rest bucket grouping
- Home and away tracked independently

Output
------
data/derived/nba_team_rolling_averages.json
"""

import json
from pathlib import Path

# =============================
# PATHS
# =============================

INPUT_PATH = Path("data/derived/nba_games_joined.json")
OUTPUT_PATH = Path("data/derived/nba_team_rolling_averages.json")


# =============================
# HELPERS
# =============================

def load_games():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"Missing file: {INPUT_PATH}")

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        games = json.load(f)

    # Sort strictly by game_date to guarantee chronological order
    games.sort(key=lambda g: g["game_date"])
    return games


# =============================
# CORE LOGIC
# =============================

def build_rolling_averages():
    games = load_games()

    # Keyed by (team_id, side)
    history = {}

    output_rows = []

    for g in games:
        game_id = g["game_id"]
        status = g.get("status")
        is_playoff = g.get("is_playoff", False)

        # Skip preseason entirely
        if g.get("season_year") is None:
            continue

        for side in ("home", "away"):

            team_id = g[f"{side}_team_id"]
            key = (team_id, side)

            hist = history.get(key, {
                "points_for": 0,
                "points_against": 0,
                "games": 0
            })

            # ---- Compute rolling BEFORE updating ----
            if hist["games"] > 0:
                avg_for = hist["points_for"] / hist["games"]
                avg_against = hist["points_against"] / hist["games"]
            else:
                avg_for = None
                avg_against = None

            output_rows.append({
                "game_id": game_id,
                "team_id": team_id,
                "side": side,
                "rolling_avg_points_for": avg_for,
                "rolling_avg_points_against": avg_against,
                "games_in_sample": hist["games"]
            })

        # ---- Update accumulator ONLY if final regular-season game ----
        if status == 3 and not is_playoff:

            for side in ("home", "away"):

                team_id = g[f"{side}_team_id"]
                key = (team_id, side)

                points_for = g[f"{side}_score"]
                points_against = (
                    g["away_score"] if side == "home" else g["home_score"]
                )

                hist = history.setdefault(key, {
                    "points_for": 0,
                    "points_against": 0,
                    "games": 0
                })

                hist["points_for"] += points_for
                hist["points_against"] += points_against
                hist["games"] += 1

    return output_rows


# =============================
# MAIN
# =============================

def main():
    rows = build_rolling_averages()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    print(f"✅ Rows written: {len(rows)}")
    print(f"📄 Output → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()