"""
c_ncaam_015_build_last5_momentum.py

Purpose
-------
Build NCAA last-5 momentum features from the NCAA game-level table.

Features produced
-----------------
For each game, using only PRIOR games for each team:

- home_last5_points_for
- home_last5_points_against
- home_last5_avg_margin
- home_last5_win_pct

- away_last5_points_for
- away_last5_points_against
- away_last5_avg_margin
- away_last5_win_pct

Design goals
------------
- No leakage: current game is never included in its own features
- Uses one row per game from ncaam_game_level.csv
- Writes a feature-enriched table for downstream modeling
"""

import csv
from collections import defaultdict
from pathlib import Path

from configs.leagues.league_ncaam import CANONICAL_DIR, MODEL_DIR, ensure_ncaam_dirs

INPUT_PATH = CANONICAL_DIR / "ncaam_game_level.csv"
OUTPUT_PATH = MODEL_DIR / "ncaam_game_level_with_last5_momentum.csv"


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
# BUILD TEAM-GAME VIEW
# =====================================================

def build_team_game_rows(game_rows: list[dict]) -> list[dict]:
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
        if home_score is None or away_score is None:
            continue

        home_margin = home_score - away_score
        away_margin = away_score - home_score

        out.append({
            "canonical_game_id": canonical_game_id,
            "game_date": game_date,
            "team_id": home_team_id,
            "opponent_team_id": away_team_id,
            "is_home": 1,
            "points_for": home_score,
            "points_against": away_score,
            "margin": home_margin,
            "win_flag": 1 if home_margin > 0 else 0,
        })

        out.append({
            "canonical_game_id": canonical_game_id,
            "game_date": game_date,
            "team_id": away_team_id,
            "opponent_team_id": home_team_id,
            "is_home": 0,
            "points_for": away_score,
            "points_against": home_score,
            "margin": away_margin,
            "win_flag": 1 if away_margin > 0 else 0,
        })

    out.sort(key=lambda r: (r["team_id"], r["game_date"], r["canonical_game_id"]))
    return out


# =====================================================
# BUILD PRIOR LAST-5 LOOKUP
# =====================================================

def build_last5_lookup(team_game_rows: list[dict]) -> dict[tuple[str, str], dict]:
    """
    Returns:
      (canonical_game_id, team_id) -> prior last-5 momentum stats
    """
    history_pf = defaultdict(list)
    history_pa = defaultdict(list)
    history_margin = defaultdict(list)
    history_win = defaultdict(list)

    lookup = {}

    for row in team_game_rows:
        canonical_game_id = row["canonical_game_id"]
        team_id = row["team_id"]

        prior_pf = history_pf[team_id][-5:]
        prior_pa = history_pa[team_id][-5:]
        prior_margin = history_margin[team_id][-5:]
        prior_win = history_win[team_id][-5:]

        lookup[(canonical_game_id, team_id)] = {
            "last5_points_for": avg(prior_pf),
            "last5_points_against": avg(prior_pa),
            "last5_avg_margin": avg(prior_margin),
            "last5_win_pct": avg(prior_win),
            "last5_games_in_history": len(prior_pf),
        }

        history_pf[team_id].append(row["points_for"])
        history_pa[team_id].append(row["points_against"])
        history_margin[team_id].append(row["margin"])
        history_win[team_id].append(row["win_flag"])

    return lookup


# =====================================================
# MERGE BACK TO GAME GRAIN
# =====================================================

def add_last5_features_to_games(game_rows: list[dict], last5_lookup: dict[tuple[str, str], dict]) -> list[dict]:
    out = []

    for row in game_rows:
        canonical_game_id = (row.get("canonical_game_id") or "").strip()
        home_team_id = (row.get("home_team_id") or "").strip()
        away_team_id = (row.get("away_team_id") or "").strip()

        home_last5 = last5_lookup.get((canonical_game_id, home_team_id), {})
        away_last5 = last5_lookup.get((canonical_game_id, away_team_id), {})

        joined = dict(row)

        joined["home_last5_points_for"] = fmt_num(home_last5.get("last5_points_for"))
        joined["home_last5_points_against"] = fmt_num(home_last5.get("last5_points_against"))
        joined["home_last5_avg_margin"] = fmt_num(home_last5.get("last5_avg_margin"))
        joined["home_last5_win_pct"] = fmt_num(home_last5.get("last5_win_pct"))
        joined["home_last5_games_in_history"] = home_last5.get("last5_games_in_history", 0)

        joined["away_last5_points_for"] = fmt_num(away_last5.get("last5_points_for"))
        joined["away_last5_points_against"] = fmt_num(away_last5.get("last5_points_against"))
        joined["away_last5_avg_margin"] = fmt_num(away_last5.get("last5_avg_margin"))
        joined["away_last5_win_pct"] = fmt_num(away_last5.get("last5_win_pct"))
        joined["away_last5_games_in_history"] = away_last5.get("last5_games_in_history", 0)

        out.append(joined)

    out.sort(key=lambda r: (r.get("game_date", ""), r.get("canonical_game_id", "")))
    return out


# =====================================================
# VALIDATION
# =====================================================

def validate_rows(rows: list[dict]) -> None:
    if not rows:
        raise ValueError("No momentum rows produced")

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
    last5_lookup = build_last5_lookup(team_game_rows)
    momentum_rows = add_last5_features_to_games(game_rows, last5_lookup)

    validate_rows(momentum_rows)
    write_rows(momentum_rows)

    rows_with_home_last5 = sum(1 for r in momentum_rows if str(r.get("home_last5_points_for", "")).strip() != "")
    rows_with_away_last5 = sum(1 for r in momentum_rows if str(r.get("away_last5_points_for", "")).strip() != "")

    print(f"Loaded game-level rows:      {len(game_rows)}")
    print(f"Built team-game rows:        {len(team_game_rows)}")
    print(f"Momentum output written to:  {OUTPUT_PATH}")
    print(f"Momentum rows:               {len(momentum_rows)}")
    print(f"Rows with home last5:        {rows_with_home_last5}")
    print(f"Rows with away last5:        {rows_with_away_last5}")


if __name__ == "__main__":
    run()
