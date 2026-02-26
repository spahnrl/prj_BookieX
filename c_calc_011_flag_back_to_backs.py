"""
c_calc_011_flag_back_to_backs.py

Flag back-to-back and back-to-back-to-back games using rest days.

Reads:
  data/derived/nba_games_with_rest.json

Writes:
  data/derived/nba_games_with_b2b.json
  data/derived/nba_games_with_b2b.csv
"""

import json
import csv
from pathlib import Path
from collections import defaultdict


# INPUT_PATH = Path("data/derived/nba_boxscores_team.json")
INPUT_PATH = Path("data/derived/nba_games_with_rest.json")
OUTPUT_DIR = Path("data/derived")



def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# def flag_back_to_backs(games: list[dict]) -> list[dict]:
#     """
#     Adds:
#       - home_back_to_back
#       - away_back_to_back
#       - home_back_to_back_to_back
#       - away_back_to_back_to_back
#     """
#     last_rest_by_team = defaultdict(lambda: None)
#     enriched = []
#
#     # Sort games chronologically first
#     games_sorted = sorted(
#         games,
#         key=lambda g: (g["game_date"], g["game_id"])
#     )
#
#     for g in games_sorted:
#
#         for side in ("home", "away"):
#             team_id = g[f"{side}_team_id"]
#             rest_days = g.get(f"{side}_rest_days")
#
#             # Back-to-back
#             is_b2b = (rest_days == 0)
#
#             # Back-to-back-to-back
#             was_b2b_last_game = (last_rest_by_team[team_id] == 0)
#             is_b2b2b = is_b2b and was_b2b_last_game
#
#             record[f"{side}_back_to_back"] = is_b2b
#             record[f"{side}_back_to_back_to_back"] = is_b2b2b
#
#             # Track for next game
#             last_rest_by_team[team_id] = rest_days
#
#         # Combined convenience flags
#         record["any_back_to_back"] = (
#             record["home_back_to_back"] or record["away_back_to_back"]
#         )
#
#         record["any_back_to_back_to_back"] = (
#             record["home_back_to_back_to_back"]
#             or record["away_back_to_back_to_back"]
#         )
#
#         enriched.append(record)
#
#     return enriched


def flag_back_to_backs(games: list[dict]) -> list[dict]:
    """
    Adds:
      - home_back_to_back
      - away_back_to_back
      - home_back_to_back_to_back
      - away_back_to_back_to_back
    """
    last_rest_by_team = defaultdict(lambda: None)
    enriched = []

    # Sort games chronologically first
    games_sorted = sorted(
        games,
        key=lambda g: (g["game_date"], g["game_id"])
    )

    for g in games_sorted:
        record = dict(g)  # <-- YOU WERE MISSING THIS

        for side in ("home", "away"):
            team_id = g[f"{side}_team_id"]
            rest_days = g.get(f"{side}_rest_days")

            # Back-to-back
            is_b2b = (rest_days == 0)

            # Back-to-back-to-back
            was_b2b_last_game = (last_rest_by_team[team_id] == 0)
            is_b2b2b = is_b2b and was_b2b_last_game

            record[f"{side}_back_to_back"] = is_b2b
            record[f"{side}_back_to_back_to_back"] = is_b2b2b

            # Track for next game
            last_rest_by_team[team_id] = rest_days

        # Combined convenience flags
        record["any_back_to_back"] = (
            record["home_back_to_back"] or record["away_back_to_back"]
        )

        record["any_back_to_back_to_back"] = (
            record["home_back_to_back_to_back"]
            or record["away_back_to_back_to_back"]
        )

        enriched.append(record)

    return enriched

def write_outputs(records: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "nba_games_with_b2b.json"
    csv_path = OUTPUT_DIR / "nba_games_with_b2b.csv"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    if not records:
        print("WARNING: No records to write.")
        return

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)

    print(f"B2B JSON saved to: {json_path}")
    print(f"B2B CSV  saved to: {csv_path}")


def run():
    games = load_json(INPUT_PATH)
    print(f"Loaded games: {len(games)}")

    enriched = flag_back_to_backs(games)
    write_outputs(enriched)


if __name__ == "__main__":
    run()
