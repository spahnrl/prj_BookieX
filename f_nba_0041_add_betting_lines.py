"""
f_nba_0041_add_betting_lines.py

JOIN ONLY (NON-DESTRUCTIVE)
- Preserve ALL existing fields
- Append NEW flattened odds fields only
- NEVER rename
- NEVER remove
- NEVER recompute

JOIN KEY (LOCKED):
(home_team, away_team, nba_game_day_local)
"""

import json
import csv
from pathlib import Path

# =============================
# PATHS
# =============================

VIEW_DIR = Path("data/view")
DERIVED_DIR = Path("data/derived")

GAMES_IN = VIEW_DIR / "nba_games_game_level.json"
ODDS_IN  = DERIVED_DIR / "nba_betlines_flattened.json"

OUT_JSON = VIEW_DIR / "nba_games_game_level_with_odds.json"
OUT_CSV  = VIEW_DIR / "nba_games_game_level_with_odds.csv"

# =============================
# LOAD DATA
# =============================

with open(GAMES_IN, "r", encoding="utf-8") as f:
    games = json.load(f)

with open(ODDS_IN, "r", encoding="utf-8") as f:
    odds_rows = json.load(f)

# =============================
# BUILD ODDS LOOKUP (TRUE ID)
# =============================

odds_index = {
    (
        o["home_team"],
        o["away_team"],
        o["nba_game_day_local"],
    ): o
    for o in odds_rows
}

# =============================
# NON-DESTRUCTIVE ATTACH
# =============================

attached = 0
missing = 0

for g in games:
    join_key = (
        g.get("home_team"),
        g.get("away_team"),
        g.get("nba_game_day_local"),
    )

    odds = odds_index.get(join_key)
    if not odds:
        missing += 1
        continue

    # Append ONLY fields that do not already exist
    for k, v in odds.items():
        if k not in g:
            g[k] = v

    # Transparency (new, safe)
    if "odds_join_method" not in g:
        g["odds_join_method"] = "home_away_nba_game_day_local"

    attached += 1

# =============================
# WRITE OUTPUTS
# =============================

OUT_JSON.parent.mkdir(parents=True, exist_ok=True)

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(games, f, indent=2)

# CSV — union of ALL fields
rows = []
all_fields = set()

for g in games:
    rows.append(g)
    all_fields.update(g.keys())

with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=sorted(all_fields),
        extrasaction="ignore"
    )
    writer.writeheader()
    writer.writerows(rows)

print("✅ Non-destructive odds enrichment complete")
print(f"🔗 Joined rows: {attached}")
print(f"⚠️ Missing odds: {missing}")