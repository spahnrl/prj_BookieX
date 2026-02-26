"""
data_006_calculate_team_averages.py

Calculate team averages based on:
- Rest days
- Home vs Away
- Games that have been played
- Explicit handling of PRESEASON vs NON-PRESEASON games

IMPORTANT DESIGN NOTES
----------------------
1. We intentionally DO NOT remove or rename any existing fields.
2. Existing aggregate fields are UPDATED to exclude preseason games
   (i.e., they now represent **played games that are NOT preseason**,
   which includes regular season + playoffs).
3. New *_all fields preserve the original behavior (ALL games,
   including preseason).
4. No downstream scripts need to change.

Reads:
  data/derived/nba_games_with_b2b.json

Writes:
  data/derived/nba_team_averages.json
  data/derived/nba_team_averages.csv
"""

import json
import csv
from pathlib import Path
from collections import defaultdict


# =============================
# PATHS
# =============================

INPUT_PATH = Path("data/derived/nba_games_with_b2b.json")
OUTPUT_DIR = Path("data/derived")


# =============================
# LOADERS
# =============================

def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# =============================
# HELPERS
# =============================

def bucket_rest(rest_days):
    """
    Bucket rest days into stable categories used across the pipeline.
    """
    if rest_days is None:
        return "season_opener"
    if rest_days == 0:
        return "b2b"
    if rest_days == 1:
        return "1_day"
    if rest_days == 2:
        return "2_days"
    return "3_plus_days"


def derive_season_type(game: dict) -> str:
    """
    Derive season_type from NBA game_id.

    NBA game_id convention:
      001xxxxxxx → preseason
      002xxxxxxx → regular season
      004xxxxxxx → playoffs
    """
    gid = str(game.get("game_id", ""))

    if gid.startswith("001"):
        return "preseason"
    if gid.startswith("004"):
        return "playoffs"
    if gid.startswith("002"):
        return "regular"

    return "unknown"



# =============================
# CORE LOGIC
# =============================

def calculate_team_averages(games: list[dict]) -> list[dict]:
    """
    Compute per-team averages by:
    - home/away
    - rest bucket

    TWO PARALLEL AGGREGATIONS ARE MAINTAINED:

    1. CURRENT FIELDS (UPDATED BEHAVIOR)
       - games_played
       - avg_points_for
       - avg_points_against
       - net_rating

       These now mean:
       → Games that have been played AND are NOT preseason
         (regular season + playoffs)

    2. *_all FIELDS (LEGACY / PRESENTATION SAFE)
       - games_played_all
       - avg_points_for_all
       - avg_points_against_all
       - net_rating_all

       These preserve the prior behavior:
       → ALL games, including preseason
    """

    # Stats excluding preseason (new model-safe behavior)
    stats_non_pre = defaultdict(lambda: {
        "games": 0,
        "points_for": 0,
        "points_against": 0,
    })

    # Stats including all games (legacy behavior)
    stats_all = defaultdict(lambda: {
        "games": 0,
        "points_for": 0,
        "points_against": 0,
    })

    for g in games:
        # Only games that have been completed
        if g.get("status") != 3:
            continue

        season_type = derive_season_type(g)

        for side in ("home", "away"):
            team_id = g[f"{side}_team_id"]
            team_name = g[f"{side}_team"]
            location = side

            rest_days = g.get(f"{side}_rest_days")
            rest_bucket = bucket_rest(rest_days)

            points_for = g[f"{side}_score"]
            points_against = g["away_score"] if side == "home" else g["home_score"]

            key = (
                team_id,
                team_name,
                location,
                rest_bucket,
            )

            # ---- ALL GAMES (legacy behavior) ----
            stats_all[key]["games"] += 1
            stats_all[key]["points_for"] += points_for
            stats_all[key]["points_against"] += points_against

            # ---- NON-PRESEASON GAMES (new default behavior) ----
            if season_type != "preseason":
                stats_non_pre[key]["games"] += 1
                stats_non_pre[key]["points_for"] += points_for
                stats_non_pre[key]["points_against"] += points_against

    # =============================
    # BUILD OUTPUT ROWS
    # =============================

    results = []

    for key in stats_all.keys():
        team_id, team_name, location, rest_bucket = key

        s_all = stats_all[key]
        s_np = stats_non_pre[key]

        # Skip rows with no games at all (should be rare)
        if s_all["games"] == 0:
            continue

        row = {
            # Identity
            "team_id": team_id,
            "team": team_name,
            "location": location,
            "rest_bucket": rest_bucket,

            # -------------------------
            # UPDATED DEFAULT FIELDS
            # (played games, NOT preseason)
            # -------------------------
            "games_played": s_np["games"],
            "avg_points_for": (
                round(s_np["points_for"] / s_np["games"], 2)
                if s_np["games"] > 0 else None
            ),
            "avg_points_against": (
                round(s_np["points_against"] / s_np["games"], 2)
                if s_np["games"] > 0 else None
            ),
            "net_rating": (
                round(
                    (s_np["points_for"] - s_np["points_against"]) / s_np["games"], 2
                ) if s_np["games"] > 0 else None
            ),

            # -------------------------
            # LEGACY / ALL GAMES FIELDS
            # -------------------------
            "games_played_all": s_all["games"],
            "avg_points_for_all": round(
                s_all["points_for"] / s_all["games"], 2
            ),
            "avg_points_against_all": round(
                s_all["points_against"] / s_all["games"], 2
            ),
            "net_rating_all": round(
                (s_all["points_for"] - s_all["points_against"]) / s_all["games"], 2
            ),
        }

        results.append(row)

    return results


# =============================
# OUTPUTS
# =============================

def write_outputs(records: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "nba_team_averages.json"
    csv_path = OUTPUT_DIR / "nba_team_averages.csv"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    if not records:
        print("WARNING: No averages calculated.")
        return

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)

    print(f"Team averages JSON saved to: {json_path}")
    print(f"Team averages CSV  saved to: {csv_path}")


# =============================
# MAIN
# =============================

def run():
    games = load_json(INPUT_PATH)
    print(f"Loaded games: {len(games)}")

    averages = calculate_team_averages(games)
    write_outputs(averages)


if __name__ == "__main__":
    run()
