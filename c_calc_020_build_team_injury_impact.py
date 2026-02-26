"""
c_calc_020_build_team_injury_impact.py

Build per-game team injury impact from historical injury archive.

Reads:
  data/derived/nba_injuries_history.json
  data/derived/nba_games_joined.json
  data/derived/nba_boxscores_player.json

Writes:
  data/derived/nba_team_injury_impact.json
"""

import json
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent

INJURY_HISTORY = PROJECT_ROOT / "data/derived/nba_injuries_history.json"
GAMES_PATH = PROJECT_ROOT / "data/derived/nba_games_joined.json"
OUT_PATH = PROJECT_ROOT / "data/derived/nba_team_injury_impact.json"
PLAYER_BOX_PATH = PROJECT_ROOT / "data/derived/nba_boxscores_player.json"


STATUS_WEIGHTS = {
    "OUT": 1.0,
    "DOUBTFUL": 0.75,
    "QUESTIONABLE": 0.5,
    "PROBABLE": 0.25,
}


# ------------------------------------------------------------
# Utilities
# ------------------------------------------------------------

def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_minutes_iso(min_str: str) -> float:
    """
    Converts ISO duration like 'PT34M17.00S' → decimal minutes
    """
    if not min_str or not min_str.startswith("PT"):
        return 0.0

    min_part = 0.0
    sec_part = 0.0

    if "M" in min_str:
        min_part = float(min_str.split("PT")[1].split("M")[0])

    if "S" in min_str:
        sec_part = float(min_str.split("M")[1].replace("S", ""))

    return min_part + sec_part / 60.0


# ------------------------------------------------------------
# Rolling Average Minutes (EXCLUDING ZERO-MINUTE GAMES)
# ------------------------------------------------------------

def build_player_avg_minutes(player_rows, window=5):

    player_games = defaultdict(list)

    # Collect minutes per player
    for row in player_rows:
        minutes = parse_minutes_iso(row.get("minutes"))
        player_games[row["player_id"]].append(minutes)

    player_avg = {}

    for pid, mins in player_games.items():

        # Take last N recorded games
        recent = mins[-window:]

        # Exclude zero-minute games
        non_zero_recent = [m for m in recent if m > 0]

        if non_zero_recent:
            player_avg[pid] = sum(non_zero_recent) / len(non_zero_recent)
        else:
            player_avg[pid] = 0.0

    return player_avg


# ------------------------------------------------------------
# Main Execution
# ------------------------------------------------------------

def main():

    injuries = load_json(INJURY_HISTORY)
    games = load_json(GAMES_PATH)
    player_rows = load_json(PLAYER_BOX_PATH)

    # -----------------------------------------
    # Build rolling player averages
    # -----------------------------------------
    player_avg = build_player_avg_minutes(player_rows, window=5)

    # Map name → player_id
    name_to_player_id = {
        row["player_name"]: row["player_id"]
        for row in player_rows
    }

    # -----------------------------------------
    # Group injuries by (snapshot_date, team_name)
    # -----------------------------------------
    grouped = defaultdict(list)

    for row in injuries:
        key = (row["snapshot_date"], row["team_name"])
        grouped[key].append(row)

    output = []

    for game in games:

        # 🔥 FIX: Normalize game_date to YYYY-MM-DD
        game_date = game["game_date"][:10]
        game_id = game["game_id"]

        for side in ["home", "away"]:

            team_name = game[f"{side}_team"]
            team_id = game[f"{side}_team_id"]

            key = (game_date, team_name)
            injury_rows = grouped.get(key, [])

            impact = 0.0
            num_out = 0
            num_questionable = 0

            for row in injury_rows:

                status = row["status"].upper()
                weight = STATUS_WEIGHTS.get(status, 0.0)

                player_name = row["player_name"]
                player_id = name_to_player_id.get(player_name)

                avg_minutes = player_avg.get(player_id, 0.0)

                # 30-minute baseline scaling
                injury_value = weight * (avg_minutes / 30.0)

                impact += injury_value

                if status == "OUT":
                    num_out += 1
                if status == "QUESTIONABLE":
                    num_questionable += 1

            output.append({
                "game_id": game_id,
                "team_id": team_id,
                "injury_impact": round(impact, 4),
                "num_out": num_out,
                "num_questionable": num_questionable
            })

    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print("✅ Injury impact file built (player-weighted).")
    print("Output:", OUT_PATH)


if __name__ == "__main__":
    main()