"""
d_nba_021_build_canonical_games.py

Purpose
-------
Build a canonical, team-level NBA games dataset by linking:
- Joined schedule (scores live here)
- OT flags
- Rest days
- Fatigue flags
- Team averages
- OPTIONAL: Team 3-point shooting aggregates (derived)
- OPTIONAL: Recent injury impact signals (derived)

Design Notes
------------
- Canonical is an integration layer, NOT a raw merge layer
- Player-level and injury-level raw data are never joined here
- All optional inputs are additive and non-blocking
- Missing optional data defaults to None / 0 and does NOT break pipeline

Outputs
-------
- data/view/nba_games_canonical.json
- data/view/nba_games_canonical.csv
"""

import json
import csv
from collections import defaultdict
from pathlib import Path

# =============================
# PATHS
# =============================

DATA_DIR = Path("data/derived")
OUT_DIR = Path("data/view")
OUT_JSON = OUT_DIR / "nba_games_canonical.json"
OUT_CSV = OUT_DIR / "nba_games_canonical.csv"

FILES = {
    "games": "nba_games_joined.json",
    "ot": "nba_boxscores_team.json",
    "rest": "nba_games_with_rest.json",
    "fatigue": "nba_games_with_fatigue.json",
    # "team_avgs": "nba_team_averages.json",
    "team_rolling": "nba_team_rolling_averages.json",

    # OPTIONAL / DERIVED SIGNALS
    # These files may or may not exist depending on pipeline stage
    "team_3pt": "nba_team_3pt_recent.json",
    "injuries": "nba_team_injury_impact.json",
}

# =============================
# HELPERS
# =============================

def load_json(filename):
    """
    Load a REQUIRED derived file.
    """
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_optional_json(filename):
    """
    Load an OPTIONAL derived file.
    Returns empty list if file does not exist.
    """
    path = DATA_DIR / filename
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def rest_bucket_from_days(rest_days):
    if rest_days == 0:
        return "b2b"
    if rest_days == 1:
        return "1_day"
    if rest_days == 2:
        return "2_days"
    if rest_days is not None and rest_days >= 3:
        return "3_plus_days"
    return "unknown"


def index_team_avgs(rows):
    """
    Keyed by (team_id, location, rest_bucket)
    """
    idx = defaultdict(dict)
    for r in rows:
        key = (r["team_id"], r["location"], r["rest_bucket"])
        idx[key] = r
    return idx


def write_csv(rows, path):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

# =============================
# CORE BUILD
# =============================

def build_canonical():
    # # ---- Required inputs ----
    # games = load_json(FILES["games"])
    # ot_map = {g["game_id"]: g for g in load_json(FILES["ot"])}
    # rest_map = {g["game_id"]: g for g in load_json(FILES["rest"])}
    # fatigue_map = {g["game_id"]: g for g in load_json(FILES["fatigue"])}
    # # team_avg_idx = index_team_avgs(load_json(FILES["team_avgs"]))

    # ---- Required inputs ----
    games = load_json(FILES["games"])
    ot_map = {g["game_id"]: g for g in load_json(FILES["ot"])}
    rest_map = {g["game_id"]: g for g in load_json(FILES["rest"])}
    fatigue_map = {g["game_id"]: g for g in load_json(FILES["fatigue"])}

    # ---- NEW: Rolling team averages (game-specific) ----
    rolling_rows = load_json(FILES["team_rolling"])
    rolling_map = {
        (r["game_id"], r["team_id"], r["side"]): r
        for r in rolling_rows
    }

    # ---- Optional derived inputs ----
    team_3pt_rows = load_optional_json(FILES["team_3pt"])
    injury_rows = load_optional_json(FILES["injuries"])

    # Index optional data for fast lookup
    # Team 3PT keyed by (game_id, team_id, side)
    team_3pt_idx = {
        (r["game_id"], r["team_id"], r["side"]): r
        for r in team_3pt_rows
    }

    # Injury impact keyed by (game_id, team_id)
    injury_idx = {
        (r["game_id"], r["team_id"]): r
        for r in injury_rows
    }

    canonical = []

    for g in games:
        game_id = g["game_id"]

        # Scores LIVE on joined games
        home_score = g.get("home_score")
        away_score = g.get("away_score")

        for side in ("home", "away"):
            opp_side = "away" if side == "home" else "home"

            team_id = g[f"{side}_team_id"]
            rest_days = rest_map.get(game_id, {}).get(f"{side}_rest_days")
            rest_bucket = rest_bucket_from_days(rest_days)

            # team_avg = team_avg_idx.get((team_id, side, rest_bucket), {})
            rolling = rolling_map.get((game_id, team_id, side), {})

            # Explicit score mapping
            if side == "home":
                points_scored = home_score
                points_allowed = away_score
            else:
                points_scored = away_score
                points_allowed = home_score

            # Optional lookups
            team_3pt = team_3pt_idx.get((game_id, team_id, side), {})
            injury = injury_idx.get((game_id, team_id), {})

            fatigue_record = fatigue_map.get(game_id, {})

            avg_points_for = rolling.get("rolling_avg_points_for")
            avg_points_against = rolling.get("rolling_avg_points_against")

            if avg_points_for is not None and avg_points_against is not None:
                net_rating = avg_points_for - avg_points_against
            else:
                net_rating = None

            canonical.append({
                # -------------------------
                # Game
                # -------------------------
                "game_id": game_id,
                "game_date": g["game_date"],
                "season_year": g["season_year"],

                # -------------------------
                # Team
                # -------------------------
                "side": side,
                "team_id": team_id,
                "team": g[f"{side}_team"],
                "abbr": g[f"{side}_abbr"],

                # -------------------------
                # Opponent
                # -------------------------
                "opponent_side": opp_side,
                "opponent_team_id": g[f"{opp_side}_team_id"],
                "opponent": g[f"{opp_side}_team"],
                "opponent_abbr": g[f"{opp_side}_abbr"],

                # -------------------------
                # Scoring (authoritative)
                # -------------------------
                "points_scored": points_scored,
                "points_allowed": points_allowed,

                # -------------------------
                # Overtime
                # -------------------------
                "went_ot": ot_map.get(game_id, {}).get("went_ot", False),
                "ot_minutes": ot_map.get(game_id, {}).get("ot_minutes", 0),

                # -------------------------
                # Rest / Fatigue
                # -------------------------
                "rest_days": rest_days,
                "rest_bucket": rest_bucket,

                # Boolean flag derived from score (non-breaking)
                "fatigue_flag": fatigue_record.get(f"{side}_fatigue_score", 0.0) > 0,

                # NEW — score passthrough
                "fatigue_score": fatigue_record.get(f"{side}_fatigue_score", 0.0),

                # NEW — game-level diff (same for both rows)
                "fatigue_diff_home_minus_away": fatigue_record.get(
                    "fatigue_diff_home_minus_away", 0.0
                ),

                # -------------------------
                # Team averages (contextual)
                # -------------------------
                # "avg_points_for": team_avg.get("avg_points_for"),
                # "avg_points_against": team_avg.get("avg_points_against"),
                # "net_rating": team_avg.get("net_rating"),

                "avg_points_for": avg_points_for,
                "avg_points_against": avg_points_against,
                "net_rating": net_rating,

                # -------------------------
                # OPTIONAL: Team 3PT shooting
                # -------------------------
                "team_3pm": team_3pt.get("team_3pm"),
                "team_3pa": team_3pt.get("team_3pa"),
                "team_3pt_pct": team_3pt.get("team_3pt_pct"),

                # -------------------------
                # OPTIONAL: Injury signal
                # -------------------------
                "injury_impact": injury.get("injury_impact", 0.0),
                "num_out": injury.get("num_out", 0),
                "num_questionable": injury.get("num_questionable", 0),
            })

    return canonical

# =============================
# MAIN
# =============================

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    data = build_canonical()

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    write_csv(data, OUT_CSV)

    print(f"✅ Rows written: {len(data)}")
    print(f"📄 JSON → {OUT_JSON}")
    print(f"📊 CSV  → {OUT_CSV}")


if __name__ == "__main__":
    main()
