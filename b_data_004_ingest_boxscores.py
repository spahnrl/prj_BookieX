"""
b_data_004_ingest_boxscores.py

Ingest NBA boxscores to detect overtime and minutes played.
FREE endpoint, no API key required.

Reads:
  data/derived/nba_games_with_b2b.json

Writes:
  data/derived/nba_boxscores_team.json
  data/derived/nba_boxscores_team.csv
"""

from __future__ import annotations

import json
import csv
import requests
from pathlib import Path
from datetime import datetime, date
from time import sleep
from utils.datetime_bridge import derive_game_day_local
import os
print("CWD:", os.getcwd())


INPUT_PATH = Path("data/derived/nba_games_joined.json")
OUTPUT_DIR = Path("data/derived")

NBA_BOXSCORE_URL = (
    "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
}


# =========================================
# HELPER
# =========================================
def load_existing_enriched(path: Path) -> list[dict]:
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return []


def is_eligible_game_day(record: dict) -> bool:
    """
    Authoritative eligibility check using datetime_bridge.
    """
    try:
        derived_day = derive_game_day_local(
            commence_time_utc=record["odds_commence_time_utc"],
            league="NBA",
        )
        return date.fromisoformat(derived_day) <= date.today()
    except Exception:
        # Fail safe: do NOT poll
        return False

# =========================================
# LOADER
# =========================================

def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def fetch_boxscore(game_id: str) -> dict | None:
    url = NBA_BOXSCORE_URL.format(game_id=game_id)

    try:
        resp = requests.get(
            url,
            headers=HEADERS,
            timeout=(5, 8),  # (connect, read)
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None



def extract_ot_info(box: dict) -> tuple[bool, int]:
    """
    Returns:
      went_ot (bool)
      ot_minutes (int)
    """
    try:
        periods = box["game"]["period"]
        if periods <= 4:
            return False, 0

        ot_periods = periods - 4
        return True, ot_periods * 5

    except Exception:
        return False, 0

def is_final(box: dict) -> bool:
    """
    NBA gameStatus:
      1 = Scheduled
      2 = In Progress
      3 = Final
    """
    try:
        return box["game"]["gameStatus"] == 3
    except Exception:
        return False

# def enrich_with_boxscores(games: list[dict]) -> list[dict]:
#     enriched = []
#
#     for i, g in enumerate(games):
#         record = dict(g)
#         game_id = record["game_id"]
#
#         box = fetch_boxscore(game_id)
#         if box:
#             went_ot, ot_minutes = extract_ot_info(box)
#         else:
#             went_ot, ot_minutes = False, 0
#
#         record["went_ot"] = went_ot
#         record["ot_minutes"] = ot_minutes
#         record["home_went_ot"] = went_ot
#         record["away_went_ot"] = went_ot
#
#         enriched.append(record)
#
#         # Gentle rate limiting
#         if i % 10 == 0:
#             sleep(0.4)
#         if i % 25 == 0:
#             print(f"Processed {i}/{len(games)} games")
#
#     return enriched

def enrich_with_boxscores(games: list[dict]) -> list[dict]:
    enriched = []

    for i, g in enumerate(games):
        record = dict(g)
        game_id = record["game_id"]

        box = fetch_boxscore(game_id)

        if box and is_final(box):
            went_ot, ot_minutes = extract_ot_info(box)
            record["_boxscore_status"] = "FINAL"
        else:
            # Preserve existing values if not final yet
            went_ot = record.get("went_ot", False)
            ot_minutes = record.get("ot_minutes", 0)
            record["_boxscore_status"] = "SKIPPED_NOT_FINAL"

        record["went_ot"] = went_ot
        record["ot_minutes"] = ot_minutes
        record["home_went_ot"] = went_ot
        record["away_went_ot"] = went_ot

        enriched.append(record)

        if i % 10 == 0:
            sleep(0.4)
        if i % 25 == 0:
            print(f"Processed {i}/{len(games)} games")

    return enriched

def write_outputs(records: list[dict]):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "nba_boxscores_team.json"
    csv_path = OUTPUT_DIR / "nba_boxscores_team.csv"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    try:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=records[0].keys())
            writer.writeheader()
            writer.writerows(records)
        print(f"Wrote CSV: {csv_path}")
    except PermissionError:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback = OUTPUT_DIR / f"nba_games_with_ot_{ts}.csv"
        with fallback.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=records[0].keys())
            writer.writeheader()
            writer.writerows(records)
        print(f"CSV locked — wrote fallback: {fallback}")

    print(f"Wrote JSON: {json_path}")


def run():
    OUTPUT_JSON = OUTPUT_DIR / "nba_boxscores_team.json"

    # Load full input
    games = load_json(INPUT_PATH)
    print(f"Loaded games: {len(games)}")

    # Load existing enriched output (if any)
    existing = load_existing_enriched(OUTPUT_JSON)

    # processed_ids = {g["game_id"] for g in existing}
    #
    # # Only process NEW games
    # new_games = [g for g in games if g["game_id"] not in processed_ids]
    # print(f"New games to process: {len(new_games)}")
    #
    # if not new_games:
    #     print("No new games found. Nothing to do.")
    #     return
    #
    # # Enrich only new games
    # new_enriched = enrich_with_boxscores(new_games)
    #
    # # Append + write once
    # all_enriched = existing + new_enriched
    # write_outputs(all_enriched)

    existing_by_id = {g["game_id"]: g for g in existing}

    to_process = []
    for g in games:
        prev = existing_by_id.get(g["game_id"])
        if not prev:
            to_process.append(g)
        elif (
                prev.get("_boxscore_status", "FINAL") != "FINAL"
                and is_eligible_game_day(g)
        ):
            to_process.append(g)

    print(f"Games to process (new or refresh): {len(to_process)}")

    if not to_process:
        print("Nothing to do.")
        return

    refreshed = enrich_with_boxscores(to_process)

    merged = dict(existing_by_id)
    for r in refreshed:
        merged[r["game_id"]] = r

    sorted_records = sorted(
        merged.values(),
        key=lambda g: (
            g["season_year"],
            g["game_date"],
            g["game_id"],
        )
    )

    write_outputs(sorted_records)





if __name__ == "__main__":
    run()
