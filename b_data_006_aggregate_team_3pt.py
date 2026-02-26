"""
b_data_006_aggregate_team_3pt.py

Purpose
-------
Aggregate player-level 3-point shooting data into
team-level, per-game 3PT metrics with explicit home/away side.

This is a DERIVED step:
- Reads player boxscores (005 output)
- Resolves home/away side from joined games
- Produces team-level 3PT aggregates for canonical ingestion

Inputs
------
- data/derived/nba_boxscores_player.json
- data/derived/nba_games_joined.json

Outputs
-------
- data/derived/nba_team_3pt_recent.json
- data/derived/nba_team_3pt_recent.csv
"""

import json
import csv
from collections import defaultdict
from pathlib import Path

# =============================
# PATHS
# =============================

# EXTERNAL_DIR = Path("data/external")
DERIVED_DIR = Path("data/derived")
OUT_DIR = Path("data/derived")

PLAYER_BOX = DERIVED_DIR / "nba_boxscores_player.json"
GAMES_JOINED = DERIVED_DIR / "nba_games_joined.json"

OUT_JSON = OUT_DIR / "nba_team_3pt_recent.json"
OUT_CSV = OUT_DIR / "nba_team_3pt_recent.csv"

# =============================
# LOADERS
# =============================

def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# =============================
# CORE LOGIC
# =============================

def build_game_side_index(games):
    """
    Build lookup:
    (game_id, team_id) -> side ("home" / "away")
    """
    idx = {}
    for g in games:
        gid = g["game_id"]
        idx[(gid, g["home_team_id"])] = "home"
        idx[(gid, g["away_team_id"])] = "away"
    return idx


def aggregate_team_3pt(players, side_idx):
    """
    Aggregate player-level 3PT into team-level stats
    keyed by (game_id, team_id, side)
    """
    agg = defaultdict(lambda: {"team_3pm": 0, "team_3pa": 0})

    for p in players:
        game_id = p["game_id"]
        team_id = p["team_id"]

        side = side_idx.get((game_id, team_id))
        if not side:
            # Should not happen, but we fail safely
            continue

        key = (game_id, team_id, side)

        agg[key]["team_3pm"] += p.get("fg3m") or 0
        agg[key]["team_3pa"] += p.get("fg3a") or 0

    rows = []
    for (game_id, team_id, side), vals in agg.items():
        attempts = vals["team_3pa"]
        made = vals["team_3pm"]

        rows.append({
            "game_id": game_id,
            "team_id": team_id,
            "side": side,
            "team_3pm": made,
            "team_3pa": attempts,
            "team_3pt_pct": round(made / attempts, 4) if attempts > 0 else None,
        })

    return rows

# =============================
# MAIN
# =============================

def main():
    players = load_json(PLAYER_BOX)
    games = load_json(GAMES_JOINED)

    side_idx = build_game_side_index(games)
    rows = aggregate_team_3pt(players, side_idx)

    if not rows:
        print("ℹ️ No team 3PT data produced.")
        return

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"✅ Team 3PT rows written: {len(rows)}")
    print(f"📄 JSON → {OUT_JSON}")
    print(f"📊 CSV  → {OUT_CSV}")

if __name__ == "__main__":
    main()
