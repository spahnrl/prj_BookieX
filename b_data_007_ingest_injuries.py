"""
b_data_007_ingest_injuries.py

Append-only historical injury archive.
Deterministic. No overwrite.
"""

import requests
import json
import csv
from pathlib import Path
from datetime import datetime, timezone

OUT_DIR = Path("data/derived")
HISTORY_JSON = OUT_DIR / "nba_injuries_history.json"
HISTORY_CSV = OUT_DIR / "nba_injuries_history.csv"

ESPN_INJURY_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/"
    "basketball/nba/injuries"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}

# =============================
# FETCH
# =============================

def fetch_injuries():
    r = requests.get(ESPN_INJURY_URL, headers=HEADERS, timeout=(5, 10))
    r.raise_for_status()
    return r.json()


def normalize_rows(raw: dict) -> list[dict]:
    rows = []
    snapshot_date = datetime.now(timezone.utc).date().isoformat()

    teams = raw.get("injuries", [])
    if not teams:
        return rows

    for team_block in teams:
        team_name = team_block.get("displayName")

        for injury in team_block.get("injuries", []):
            status = injury.get("status")
            athlete = injury.get("athlete", {})

            if not status:
                continue

            rows.append({
                "snapshot_date": snapshot_date,
                "team_name": team_name,
                "player_name": athlete.get("displayName"),
                "status": status.upper(),
            })

    return rows


# =============================
# APPEND LOGIC
# =============================

def load_history():
    if not HISTORY_JSON.exists():
        return []
    with open(HISTORY_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def write_history(history_rows):
    with open(HISTORY_JSON, "w", encoding="utf-8") as f:
        json.dump(history_rows, f, indent=2)

    with open(HISTORY_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=history_rows[0].keys())
        writer.writeheader()
        writer.writerows(history_rows)


def run():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    raw = fetch_injuries()
    new_rows = normalize_rows(raw)

    if not new_rows:
        print("ℹ️ No injuries returned from ESPN.")
        return

    snapshot_date = new_rows[0]["snapshot_date"]

    history = load_history()

    existing_dates = {row["snapshot_date"] for row in history}

    if snapshot_date in existing_dates:
        print(f"ℹ️ Snapshot for {snapshot_date} already recorded. Skipping append.")
        return

    history.extend(new_rows)

    write_history(history)

    print(f"✅ Appended snapshot for {snapshot_date}")
    print(f"📄 JSON → {HISTORY_JSON}")
    print(f"📊 CSV  → {HISTORY_CSV}")


if __name__ == "__main__":
    run()