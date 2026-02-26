"""
b_data_003_join_schedule_teams.py

Join NBA schedule data with team metadata.
Produces a human-readable game table.

Reads:
  data/raw/nba_schedule.json
  data/static/nba_team_map.json

Writes:
  data/derived/nba_games_joined.json
  data/derived/nba_games_joined.csv
"""

import json
import csv
from pathlib import Path


SCHEDULE_PATH = Path("data/raw/nba_schedule.json")
TEAM_MAP_PATH = Path("data/static/nba_team_map.json")
OUTPUT_DIR = Path("data/derived")


def canonical_game_day(game_date: str) -> str:
    """
    Canonical NBA game day (YYYY-MM-DD).
    Used for joins across odds, injuries, refs, etc.
    """
    return game_date[:10]


def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_team_lookup(teams: list[dict]) -> dict:
    """
    Build lookup: team_id (string) -> team record
    """
    return {str(t["team_id"]): t for t in teams}


def join_schedule(schedule: list[dict], team_lookup: dict) -> list[dict]:
    joined = []

    for g in schedule:
        home = team_lookup.get(str(g["home_team_id"]))
        away = team_lookup.get(str(g["away_team_id"]))

        if home is None or away is None:
            continue

        game_date = g["game_date"]

        game_start_date_utc = g.get("game_start_date_utc")
        game_start_time_utc = g.get("game_start_time_utc")

        joined.append({
            "game_id": g["game_id"],

            # calendar + canonical
            "game_date": game_date,
            "canonical_game_day": canonical_game_day(game_date),

            # authoritative UTC start
            "game_start_date_utc": game_start_date_utc,
            "game_start_time_utc": game_start_time_utc,
            "game_start_datetime_utc": (
                f"{game_start_date_utc}T{game_start_time_utc}"
                if game_start_date_utc and game_start_time_utc else None
            ),

            # metadata
            "season_year": g["season_year"],
            "status": g["status"],

            # home
            "home_team_id": g["home_team_id"],
            "home_team": home["team_name"],
            "home_abbr": home["abbreviation"],
            "home_conference": home["conference"],
            "home_division": home["division"],
            "home_score": g["home_team_score"],

            # away
            "away_team_id": g["away_team_id"],
            "away_team": away["team_name"],
            "away_abbr": away["abbreviation"],
            "away_conference": away["conference"],
            "away_division": away["division"],
            "away_score": g["away_team_score"],

            "is_playoff": g["is_playoff"],
        })

    return joined

def write_outputs(records: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "nba_games_joined.json"
    csv_path = OUTPUT_DIR / "nba_games_joined.csv"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    if not records:
        print("WARNING: No joined records produced.")
        print(f"Empty JSON written to: {json_path}")
        return

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)

    print(f"Joined games JSON saved to: {json_path}")
    print(f"Joined games CSV  saved to: {csv_path}")


def run():
    schedule = load_json(SCHEDULE_PATH)
    teams = load_json(TEAM_MAP_PATH)

    print(f"Schedule rows: {len(schedule)}")
    print(f"Team map rows: {len(teams)}")

    team_lookup = build_team_lookup(teams)
    joined = join_schedule(schedule, team_lookup)

    print(f"Joined rows: {len(joined)}")

    write_outputs(joined)


if __name__ == "__main__":
    run()
