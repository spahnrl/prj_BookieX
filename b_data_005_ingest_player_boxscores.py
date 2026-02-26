"""
b_data_005_ingest_player_boxscores.py

Ingest per-player NBA boxscore data and extract
3-point shooting statistics.

Writes:
  data/derived/nba_boxscores_player.json
  data/derived/nba_boxscores_player.csv
"""

import requests
import json
import csv
from pathlib import Path
import time
from datetime import datetime, timedelta, timezone




# =============================
# PATHS
# =============================

SCHEDULE_PATH = Path("data/derived/nba_games_joined.json")
OUT_DIR = Path("data/derived")

OUT_JSON = OUT_DIR / "nba_boxscores_player.json"
OUT_CSV = OUT_DIR / "nba_boxscores_player.csv"

NBA_BOX_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.nba.com/",
}

# =============================
# LOADERS
# =============================

def load_games():
    with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)



# =============================
# HELPERS
# ==============================

def load_existing_game_ids() -> set[str]:
    if not OUT_JSON.exists():
        return set()

    with open(OUT_JSON, "r", encoding="utf-8") as f:
        rows = json.load(f)

    return {r["game_id"] for r in rows}

def is_within_refresh_window(game_date: str, days_back=3, days_forward=1) -> bool:
    game_day = datetime.fromisoformat(game_date[:10])

    today = datetime.now(timezone.utc).date()

    return (
        today - timedelta(days=days_back)
        <= game_day.date()
        <= today + timedelta(days=days_forward)
    )

def load_existing_rows() -> list[dict]:
    if not OUT_JSON.exists():
        return []
    with open(OUT_JSON, "r", encoding="utf-8") as f:
        return json.load(f)
# =============================
# CORE LOGIC
# =============================

def fetch_boxscore(game_id: str) -> dict | None:
    url = NBA_BOX_URL.format(game_id=game_id)
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=(5, 10)  # connect timeout, read timeout
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"⚠️  Skipped game {game_id} ({type(e).__name__})")
        return None



# def extract_players(game_id: str, box: dict) -> list[dict]:
#     rows = []
#
#     game = box.get("game", {})
#     for side in ("homeTeam", "awayTeam"):
#         team = game.get(side, {})
#         team_id = team.get("teamId")
#         team_abbr = team.get("teamTricode")
#
#         for p in team.get("players", []):
#             fg3a = p.get("statistics", {}).get("threePointersAttempted")
#             fg3m = p.get("statistics", {}).get("threePointersMade")
#
#             if fg3a is None:
#                 continue
#
#             rows.append({
#                 "game_id": game_id,
#                 "team_id": team_id,
#                 "team_abbr": team_abbr,
#                 "player_id": p.get("personId"),
#                 "player_name": p.get("name"),
#                 "fg3m": fg3m,
#                 "fg3a": fg3a,
#                 "fg3_pct": round(fg3m / fg3a, 3) if fg3a > 0 else None,
#                 "minutes": p.get("statistics", {}).get("minutes"),
#             })
#
#     return rows

def extract_players(game_id: str, box: dict) -> list[dict]:
    rows = []

    game = box.get("game", {})
    for side in ("homeTeam", "awayTeam"):
        team = game.get(side, {})
        team_id = team.get("teamId")
        team_abbr = team.get("teamTricode")

        for p in team.get("players", []):
            stats = p.get("statistics", {})

            ftm = stats.get("freeThrowsMade")
            fta = stats.get("freeThrowsAttempted")

            fgm = stats.get("fieldGoalsMade")
            fga = stats.get("fieldGoalsAttempted")

            fg3m = stats.get("threePointersMade")
            fg3a = stats.get("threePointersAttempted")

            # Guard: require all core shooting stats
            if None in (ftm, fta, fgm, fga, fg3m, fg3a):
                continue

            fg2m = fgm - fg3m
            fg2a = fga - fg3a

            rows.append({
                "game_id": game_id,
                "team_id": team_id,
                "team_abbr": team_abbr,
                "player_id": p.get("personId"),
                "player_name": p.get("name"),

                # Free Throws
                "ftm": ftm,
                "fta": fta,
                "ftm_pct": round(ftm / fta, 3) if fta > 0 else None,

                # 2PT
                "fg2m": fg2m,
                "fg2a": fg2a,
                "fg2_pct": round(fg2m / fg2a, 3) if fg2a > 0 else None,

                # 3PT
                "fg3m": fg3m,
                "fg3a": fg3a,
                "fg3_pct": round(fg3m / fg3a, 3) if fg3a > 0 else None,

                "minutes": stats.get("minutes"),
            })

    return rows


# =============================
# MAIN
# =============================

# def run():
#     OUT_DIR.mkdir(parents=True, exist_ok=True)
#
#     games = load_games()
#     print(f"Loaded games: {len(games)}")
#
#     existing_game_ids = load_existing_game_ids()
#     print(f"Existing games with boxscores: {len(existing_game_ids)}")
#
#     total = len(games)
#     processed = 0
#     skipped = 0
#     all_rows = []
#
#     for i, g in enumerate(games, start=1):
#         if g.get("status") != 3:
#             continue
#
#         game_id = g["game_id"]
#
#         # ---- Incremental guards ----
#         if game_id in existing_game_ids:
#             continue
#
#         box = fetch_boxscore(game_id)
#
#         if not box:
#             skipped += 1
#             continue
#
#         rows = extract_players(game_id, box)
#         all_rows.extend(rows)
#         processed += 1
#
#         if i % 25 == 0:
#             print(
#                 f"⏳ {i}/{total} games | "
#                 f"processed={processed} | skipped={skipped} | "
#                 f"rows={len(all_rows)}"
#             )
#
#         time.sleep(0.15)
#
#     if not all_rows:
#         print("ℹ️  No new games to ingest — keeping existing data.")
#         return
#
#     # ---- Write JSON ----
#     with open(OUT_JSON, "w", encoding="utf-8") as f:
#         json.dump(all_rows, f, indent=2)
#
#     # ---- Write CSV ----
#     with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
#         writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
#         writer.writeheader()
#         writer.writerows(all_rows)
#
#     print(f"✅ Player rows written: {len(all_rows)}")
#     print(f"📄 JSON → {OUT_JSON}")
#     print(f"📊 CSV  → {OUT_CSV}")

def run():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    games = load_games()
    print(f"Loaded games: {len(games)}")

    existing_rows = load_existing_rows()
    existing_game_ids = {r["game_id"] for r in existing_rows}

    print(f"Existing games with player boxscores: {len(existing_game_ids)}")

    new_rows = []
    processed = 0
    skipped = 0

    for i, g in enumerate(games, start=1):
        if g.get("status") != 3:
            continue

        game_id = g["game_id"]

        # ---- Incremental guard ----
        if game_id in existing_game_ids:
            continue

        box = fetch_boxscore(game_id)
        if not box:
            skipped += 1
            continue

        rows = extract_players(game_id, box)
        new_rows.extend(rows)
        processed += 1

        if i % 25 == 0:
            print(
                f"⏳ {i}/{len(games)} | "
                f"new_games={processed} | skipped={skipped} | "
                f"new_rows={len(new_rows)}"
            )

        time.sleep(0.15)

    if not new_rows:
        print("ℹ️  No new games found. Nothing to append.")
        return

    all_rows = existing_rows + new_rows

    sorted_rows = sorted(
        all_rows,
        key=lambda r: (
            r["game_id"],
            r["team_id"],
            r["player_id"],
        )
    )

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(sorted_rows, f, indent=2)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"✅ Added games: {processed}")
    print(f"📊 Total player rows: {len(all_rows)}")

if __name__ == "__main__":
    run()
