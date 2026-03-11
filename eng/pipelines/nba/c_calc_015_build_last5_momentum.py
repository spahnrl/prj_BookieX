"""
c_calc_015_rolling_last5.py

Strict prior-game rolling LAST 5 averages
Location agnostic
Full universe safe
"""

import json
from pathlib import Path
from collections import deque

from configs.leagues.league_nba import DERIVED_DIR, SCHEDULE_JOINED_PATH

# =============================
# PATHS
# =============================

INPUT_PATH = SCHEDULE_JOINED_PATH
OUTPUT_PATH = DERIVED_DIR / "nba_team_last5.json"


# =============================
# LOAD
# =============================

def load_games():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"Missing file: {INPUT_PATH}")

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        games = json.load(f)

    # Deterministic chronological ordering
    games.sort(key=lambda g: (g["game_date"], g["game_id"]))

    return games


# =============================
# CORE
# =============================

def build_last5():

    games = load_games()

    # Keyed by team_id
    history = {}

    output_rows = []

    for g in games:

        game_id = g["game_id"]
        status = g.get("status")
        is_playoff = g.get("is_playoff", False)

        if g.get("season_year") is None:
            continue

        for side in ("home", "away"):

            team_id = g[f"{side}_team_id"]

            # Ensure history exists
            if team_id not in history:
                history[team_id] = deque(maxlen=5)

            hist = history[team_id]

            # ---- Compute BEFORE updating ----
            if len(hist) == 5:
                avg_for = round(sum(x["pf"] for x in hist) / 5, 3)
                avg_against = round(sum(x["pa"] for x in hist) / 5, 3)
            else:
                avg_for = None
                avg_against = None

            output_rows.append({
                "game_id": game_id,
                "team_id": team_id,
                "side": side,
                "last5_points_for": avg_for,
                "last5_points_against": avg_against,
                "games_in_sample": len(hist)
            })

        # ---- Update ONLY if final regular-season game ----
        if status == 3 and not is_playoff:

            for side in ("home", "away"):

                team_id = g[f"{side}_team_id"]

                points_for = g.get(f"{side}_score")
                points_against = (
                    g.get("away_score") if side == "home"
                    else g.get("home_score")
                )

                # Guard incomplete score cases
                if points_for is None or points_against is None:
                    continue

                history[team_id].append({
                    "pf": points_for,
                    "pa": points_against
                })

    return output_rows


# =============================
# MAIN
# =============================

def main():

    rows = build_last5()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    print(f"[OK] Rows written: {len(rows)}")
    print(f"Output -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
