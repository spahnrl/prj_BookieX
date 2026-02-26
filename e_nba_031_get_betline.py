"""
e_nba_031_get_betline.py

Purpose
-------
Ingest current NBA betting market prices from The Odds API.

Design guarantees:
- One API call per run (bulk NBA odds)
- No inference or normalization
- Deterministic output
- Audit-safe (raw snapshot preserved)
- Outputs both JSON and CSV

Environment
-----------
Requires:
    ODDS_API_KEY=<your_api_key>

Outputs
-------
data/external/odds_api_raw.json
data/external/odds_api_current.csv
"""

import os
import json
import csv
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path

# =====================================================
# LOAD ENVIROMENT
# =====================================================

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)



# =====================================================
# CONFIG
# =====================================================

SPORT_KEY = "basketball_nba"
MARKETS = "spreads,totals,h2h"
REGIONS = "us"
ODDS_FORMAT = "american"

BASE_URL = "https://api.the-odds-api.com/v4/sports"

API_KEY = os.getenv("ODDS_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing required environment variable: ODDS_API_KEY")



OUTPUT_DIR = Path("data/external")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

JSON_OUT = OUTPUT_DIR / "odds_api_raw.json"
CSV_OUT = OUTPUT_DIR / "odds_api_current.csv"

# =====================================================
# INGEST
# =====================================================

def fetch_current_odds():
    url = f"{BASE_URL}/{SPORT_KEY}/odds"
    params = {
        "apiKey": API_KEY,
        "markets": MARKETS,
        "regions": REGIONS,
        "oddsFormat": ODDS_FORMAT,
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()

# =====================================================
# FLATTEN
# =====================================================

def flatten_odds(raw_data):
    """
    Produces one row per:
      game x bookmaker x market x outcome
    """
    captured_at = datetime.now(timezone.utc).isoformat()
    rows = []

    for game in raw_data:
        game_id = game.get("id")
        game_date = game.get("commence_time")
        home_team = game.get("home_team")
        away_team = game.get("away_team")

        for bookmaker in game.get("bookmakers", []):
            book_key = bookmaker.get("key")
            book_title = bookmaker.get("title")

            for market in bookmaker.get("markets", []):
                market_key = market.get("key")

                for outcome in market.get("outcomes", []):
                    rows.append({
                        "game_id": game_id,
                        "game_date": game_date,
                        "home_team": home_team,
                        "away_team": away_team,
                        "bookmaker": book_title,
                        "bookmaker_key": book_key,
                        "market": market_key,
                        "outcome_name": outcome.get("name"),
                        "price": outcome.get("price"),
                        "point": outcome.get("point"),
                        "source": "the_odds_api",
                        "captured_at_utc": captured_at,
                    })

    return rows

# =====================================================
# WRITE OUTPUTS
# =====================================================

# def write_json(data):
#     with open(JSON_OUT, "w", encoding="utf-8") as f:
#         json.dump(data, f, indent=2)

def write_json_append(raw_data):
    captured_at = datetime.now(timezone.utc).isoformat()

    snapshot = {
        "captured_at_utc": captured_at,
        "sport": SPORT_KEY,
        "source": "the_odds_api",
        "data": raw_data
    }

    if JSON_OUT.exists():
        with open(JSON_OUT, "r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = []
    else:
        existing = []

    existing.append(snapshot)

    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)

def write_csv(rows):
    if not rows:
        return

    with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

# =====================================================
# MAIN
# =====================================================

def run():
    print("📡 Fetching NBA odds from The Odds API...")
    raw_data = fetch_current_odds()

    print(f"✅ Retrieved {len(raw_data)} games")
    write_json_append(raw_data)


    rows = flatten_odds(raw_data)
    write_csv(rows)

    print(f"📄 JSON written to: {JSON_OUT}")
    print(f"📄 CSV written to:  {CSV_OUT}")
    print(f"📊 Rows written:   {len(rows)}")

if __name__ == "__main__":
    run()
