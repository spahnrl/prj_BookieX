"""
c_calc_010_add_team_rest_days.py

Compute rest days for each team based on game schedule.
Rest is calculated as days since the team's previous game.

Reads:
  data/derived/nba_games_joined.json

Writes:
  data/derived/nba_games_with_rest.json
  data/derived/nba_games_with_rest.csv
"""

import json
import csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict


INPUT_PATH = Path("data/derived/nba_boxscores_team.json")
OUTPUT_DIR = Path("data/derived")


def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_datetime(game_date: str, game_time_utc: str | None) -> datetime:
    """
    Parse game datetime safely from mixed NBA formats.
    Handles:
      - game_date as YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ
      - game_time_utc as HH:MM:SSZ or 1900-01-01THH:MM:SS
    """
    # Normalize game_date to YYYY-MM-DD
    date_part = game_date.split("T")[0]

    if game_time_utc:
        # Extract time only
        time_part = game_time_utc.split("T")[-1].replace("Z", "")
        return datetime.fromisoformat(f"{date_part}T{time_part}")

    return datetime.fromisoformat(date_part)



def compute_rest_days(games: list[dict]) -> list[dict]:
    """
    Compute rest days for home and away teams.
    """
    # games_sorted = sorted(
    #     games,
    #     key=lambda g: (
    #         g["season_year"],
    #         g["game_datetime_utc"] or g["game_date"]
    #     )
    # )

    games_sorted = sorted(
        games,
        key=lambda g: (
            g["season_year"],
            parse_datetime(
                g["game_date"],
                g.get("game_time_utc")
            ),
            g["game_id"]  # deterministic tie-breaker
        )
    )

    last_game_by_team = defaultdict(lambda: None)
    enriched = []

    for g in games_sorted:
        game_dt = parse_datetime(g["game_date"], g.get("game_time_utc"))

        record = dict(g)

        for side in ("home", "away"):
            team_id = g[f"{side}_team_id"]
            last_dt = last_game_by_team[team_id]

            if last_dt is None:
                rest_days = None
            else:
                rest_days = (game_dt.date() - last_dt.date()).days - 1
                if rest_days < 0:
                    rest_days = 0

            record[f"{side}_rest_days"] = rest_days
            last_game_by_team[team_id] = game_dt

        enriched.append(record)

    return enriched


def write_outputs(records: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "nba_games_with_rest.json"
    csv_path = OUTPUT_DIR / "nba_games_with_rest.csv"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    if not records:
        print("WARNING: No records to write.")
        return

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)

    print(f"Games with rest JSON saved to: {json_path}")
    print(f"Games with rest CSV  saved to: {csv_path}")


def run():
    games = load_json(INPUT_PATH)
    print(f"Loaded games: {len(games)}")

    enriched = compute_rest_days(games)
    write_outputs(enriched)


if __name__ == "__main__":
    run()
