"""
c_ncaam_001_build_avg_score_features.py

Purpose
-------
Build first-pass NCAA average score features from the NCAA game-level table.

Features produced
-----------------
For each game, using only PRIOR games for each team:

- home_avg_points_for
- home_avg_points_against
- away_avg_points_for
- away_avg_points_against

Design goals
------------
- No leakage: current game is never included in its own averages
- Uses one row per game from ncaam_game_level.csv
- Writes a new feature-enriched table for downstream modeling
"""

import csv
from collections import defaultdict
from pathlib import Path

from configs.leagues.league_ncaam import CANONICAL_DIR, MODEL_DIR, ensure_ncaam_dirs

INPUT_PATH = CANONICAL_DIR / "ncaam_game_level.csv"
OUTPUT_PATH = MODEL_DIR / "ncaam_game_level_with_avg_features.csv"


# =====================================================
# READ
# =====================================================

def load_rows() -> list[dict]:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"Missing game-level file: {INPUT_PATH}")

    with open(INPUT_PATH, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# =====================================================
# HELPERS
# =====================================================

def safe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def fmt_num(value):
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return str(round(value, 4))


def avg(values: list[float]):
    if not values:
        return None
    return sum(values) / len(values)


# =====================================================
# BUILD TEAM HISTORY VIEW
# =====================================================

def build_team_game_rows(game_rows: list[dict]) -> list[dict]:
    """
    Explode game rows to team-game rows for prior-history calculations.

    One game becomes:
      - one home team row
      - one away team row
    """
    out = []

    for row in game_rows:
        canonical_game_id = (row.get("canonical_game_id") or "").strip()
        game_date = (row.get("game_date") or "").strip()

        home_team_id = (row.get("home_team_id") or "").strip()
        away_team_id = (row.get("away_team_id") or "").strip()

        home_score = safe_float(row.get("home_score"))
        away_score = safe_float(row.get("away_score"))

        if not canonical_game_id or not game_date:
            continue

        # home team perspective
        if home_team_id:
            out.append({
                "canonical_game_id": canonical_game_id,
                "game_date": game_date,
                "team_id": home_team_id,
                "opponent_team_id": away_team_id,
                "is_home": 1,
                "points_for": home_score,
                "points_against": away_score,
            })

        # away team perspective
        if away_team_id:
            out.append({
                "canonical_game_id": canonical_game_id,
                "game_date": game_date,
                "team_id": away_team_id,
                "opponent_team_id": home_team_id,
                "is_home": 0,
                "points_for": away_score,
                "points_against": home_score,
            })

    out.sort(key=lambda r: (r["team_id"], r["game_date"], r["canonical_game_id"]))
    return out


# =====================================================
# BUILD PRIOR AVERAGE FEATURES
# =====================================================

def build_prior_avg_lookup(team_game_rows: list[dict]) -> dict[tuple[str, str], dict]:
    """
    Returns:
      (canonical_game_id, team_id) -> prior average stats
    """
    history_points_for = defaultdict(list)
    history_points_against = defaultdict(list)

    lookup = {}

    for row in team_game_rows:
        canonical_game_id = row["canonical_game_id"]
        team_id = row["team_id"]
        points_for = row["points_for"]
        points_against = row["points_against"]

        prior_for = avg(history_points_for[team_id])
        prior_against = avg(history_points_against[team_id])

        lookup[(canonical_game_id, team_id)] = {
            "avg_points_for": prior_for,
            "avg_points_against": prior_against,
            "games_in_history": len(history_points_for[team_id]),
        }

        if points_for is not None:
            history_points_for[team_id].append(points_for)
        if points_against is not None:
            history_points_against[team_id].append(points_against)

    return lookup


# =====================================================
# MERGE BACK TO GAME GRAIN
# =====================================================

def add_avg_features_to_games(game_rows: list[dict], prior_lookup: dict[tuple[str, str], dict]) -> list[dict]:
    out = []

    for row in game_rows:
        canonical_game_id = (row.get("canonical_game_id") or "").strip()
        home_team_id = (row.get("home_team_id") or "").strip()
        away_team_id = (row.get("away_team_id") or "").strip()

        home_prior = prior_lookup.get((canonical_game_id, home_team_id), {})
        away_prior = prior_lookup.get((canonical_game_id, away_team_id), {})

        joined = dict(row)

        joined["home_avg_points_for"] = fmt_num(home_prior.get("avg_points_for"))
        joined["home_avg_points_against"] = fmt_num(home_prior.get("avg_points_against"))
        joined["home_games_in_history"] = home_prior.get("games_in_history", 0)

        joined["away_avg_points_for"] = fmt_num(away_prior.get("avg_points_for"))
        joined["away_avg_points_against"] = fmt_num(away_prior.get("avg_points_against"))
        joined["away_games_in_history"] = away_prior.get("games_in_history", 0)

        out.append(joined)

    out.sort(key=lambda r: (r.get("game_date", ""), r.get("canonical_game_id", "")))
    return out


# =====================================================
# VALIDATION
# =====================================================

def validate_rows(rows: list[dict]) -> None:
    if not rows:
        raise ValueError("No feature rows produced")

    seen = set()
    for row in rows:
        cid = (row.get("canonical_game_id") or "").strip()
        if not cid:
            raise ValueError("Blank canonical_game_id found")
        if cid in seen:
            raise ValueError(f"Duplicate canonical_game_id found: {cid}")
        seen.add(cid)


# =====================================================
# WRITE
# =====================================================

def write_rows(rows: list[dict]) -> None:
    if not rows:
        raise ValueError("No rows to write")

    fieldnames = list(rows[0].keys())

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# =====================================================
# MAIN
# =====================================================

def run() -> None:
    ensure_ncaam_dirs()

    game_rows = load_rows()
    team_game_rows = build_team_game_rows(game_rows)
    prior_lookup = build_prior_avg_lookup(team_game_rows)
    feature_rows = add_avg_features_to_games(game_rows, prior_lookup)

    validate_rows(feature_rows)
    write_rows(feature_rows)

    rows_with_home_avg = sum(1 for r in feature_rows if str(r.get("home_avg_points_for", "")).strip() != "")
    rows_with_away_avg = sum(1 for r in feature_rows if str(r.get("away_avg_points_for", "")).strip() != "")

    print(f"Loaded game-level rows:      {len(game_rows)}")
    print(f"Built team-game rows:        {len(team_game_rows)}")
    print(f"Feature output written to:   {OUTPUT_PATH}")
    print(f"Feature rows:                {len(feature_rows)}")
    print(f"Rows with home avg features: {rows_with_home_avg}")
    print(f"Rows with away avg features: {rows_with_away_avg}")


if __name__ == "__main__":
    run()
