"""
b_data_001_nba_schedule.py

Deterministic NBA schedule loader using the official NBA CDN endpoint.
SSL-safe for Python 3.12+ (Windows).
No API key required.

Outputs a normalized, flat schedule file for BookieX MVP.
"""

from __future__ import annotations

import json
import requests
from pathlib import Path
from datetime import datetime
from typing import List, Dict


NBA_SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"


def fetch_nba_schedule() -> Dict:
    """
    Fetch raw NBA schedule JSON from NBA CDN.
    """
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.nba.com/",
    }

    response = requests.get(
        NBA_SCHEDULE_URL,
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


from datetime import datetime


def derive_season_year(game_date_est: str) -> int:
    """
    Derive NBA season year from game date.
    Handles both:
      - YYYY-MM-DD
      - YYYY-MM-DDTHH:MM:SSZ
    """
    date_str = game_date_est.split("T")[0]
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.year if dt.month >= 10 else dt.year - 1


def normalize_schedule(raw: Dict) -> List[Dict]:
    """
    Normalize NBA schedule JSON into a deterministic, flat structure.
    """
    records: List[Dict] = []

    for game_date in raw["leagueSchedule"]["gameDates"]:
        for game in game_date["games"]:
            season_year = derive_season_year(game["gameDateEst"])

            records.append({
                "game_id": game["gameId"],
                "game_date": game["gameDateEst"],
                "game_time_utc": game["gameTimeUTC"],
                "status": game["gameStatus"],
                "season_year": season_year,
                "home_team_id": game["homeTeam"]["teamId"],
                "home_team_score": game["homeTeam"]["score"],
                "away_team_id": game["awayTeam"]["teamId"],
                "away_team_score": game["awayTeam"]["score"],
                "is_playoff": game.get("playoffGame", False),
            })

    return records


def save_schedule(records: List[Dict], output_dir: Path) -> Path:
    """
    Persist normalized schedule to disk.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    path = output_dir / "nba_schedule.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    return path


def run(output_dir: str = "data/raw") -> Path:
    """
    End-to-end schedule pull + normalization + save.
    """
    raw = fetch_nba_schedule()
    normalized = normalize_schedule(raw)
    return save_schedule(normalized, Path(output_dir))


if __name__ == "__main__":
    path = run()
    print(f"NBA schedule saved to: {path}")
