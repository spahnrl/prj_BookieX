"""
d_nba_022_collapse_to_game_level.py

Purpose
-------
Collapse team-level canonical NBA game rows (home + away)
into a single game-level record WITHOUT losing data.

Inputs
------
- data/view/nba_games_canonical.json

Outputs
-------
- data/view/nba_games_game_level.json
- data/view/nba_games_game_level.csv
"""

import json
import csv
from pathlib import Path
from collections import defaultdict

# =============================
# PATHS
# =============================

IN_DIR = Path("data/view")
OUT_DIR = Path("data/view")

IN_FILE = IN_DIR / "nba_games_canonical.json"
OUT_JSON = OUT_DIR / "nba_games_game_level.json"
OUT_CSV = OUT_DIR / "nba_games_game_level.csv"

# =============================
# LOAD
# =============================

with open(IN_FILE, "r", encoding="utf-8") as f:
    rows = json.load(f)

# =============================
# COLLAPSE
# =============================

games = defaultdict(dict)

for r in rows:
    gid = r["game_id"]
    side = r["side"]

    # initialize game-level once
    if "game_id" not in games[gid]:
        games[gid].update({
            "game_id": r["game_id"],
            "game_date": r["game_date"],
            "nba_game_day_local": r["game_date"][:10],
            "season_year": r["season_year"],
            "went_ot": r["went_ot"],
            "ot_minutes": r["ot_minutes"],

            # NEW — fatigue diff passthrough
            "fatigue_diff_home_minus_away": r.get("fatigue_diff_home_minus_away"),

            # NEW: injury passthrough
            f"{side}_injury_impact": r.get("injury_impact"),
            f"{side}_num_out": r.get("num_out"),
            f"{side}_num_questionable": r.get("num_questionable"),
        })

    # fold team data
    games[gid].update({
        # team identity & score
        f"{side}_team_id": r["team_id"],
        f"{side}_team": r["team"],
        f"{side}_abbr": r["abbr"],
        f"{side}_points": r["points_scored"],

        # rest / fatigue
        f"{side}_rest_days": r["rest_days"],
        f"{side}_rest_bucket": r["rest_bucket"],
        f"{side}_fatigue_flag": r["fatigue_flag"],
        f"{side}_fatigue_score": r.get("fatigue_score"),

        # team averages
        f"{side}_avg_points_for": r["avg_points_for"],
        f"{side}_avg_points_against": r["avg_points_against"],
        f"{side}_net_rating": r["net_rating"],

        # NEW: team 3PT shooting (from b_data_006)
        f"{side}_team_3pm": r.get("team_3pm"),
        f"{side}_team_3pa": r.get("team_3pa"),
        f"{side}_team_3pt_pct": r.get("team_3pt_pct"),
    })

# =============================
# FINAL LIST
# =============================

game_rows = list(games.values())

# =============================
# WRITE JSON
# =============================

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(game_rows, f, indent=2)

# =============================
# WRITE CSV
# =============================

with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=game_rows[0].keys())
    writer.writeheader()
    writer.writerows(game_rows)

print(f"✅ Games written: {len(game_rows)}")
print(f"📄 JSON → {OUT_JSON}")
print(f"📊 CSV  → {OUT_CSV}")
