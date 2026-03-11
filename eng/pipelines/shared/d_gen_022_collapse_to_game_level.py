"""
d_gen_022_collapse_to_game_level.py

Unified collapse to game level: transform canonical rows into one row per game.

- NBA: canonical = team-game rows (2 per game). Collapse by game_id into one
  game-level row with home_* and away_* fields.
- NCAAM: canonical = already one row per game. Reshape to game-level schema
  (choose box vs schedule scores, compute margin/total, keep needed columns).

Uses utils.io_helpers for paths: get_canonical_games_* (input), get_game_level_* (output).

Usage:
  python d_gen_022_collapse_to_game_level.py --league nba
  python d_gen_022_collapse_to_game_level.py --league ncaam

Forward-only: reads only canonical (021 output); writes only game-level JSON/CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils.io_helpers import (
    get_canonical_games_csv_path,
    get_canonical_games_json_path,
    get_game_level_csv_path,
    get_game_level_json_path,
)
from utils.run_log import set_silent, log_info


# =============================================================================
# SHARED: Write game-level output (JSON where applicable, CSV audit)
# =============================================================================

def write_game_level(league: str, rows: list[dict]) -> None:
    """Write game-level rows to JSON (if league has it) and CSV."""
    if not rows:
        return
    csv_path = get_game_level_csv_path(league)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys(), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    json_path = get_game_level_json_path(league)
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2)


# =============================================================================
# NBA: Team-game rows -> one game-level row (group by game_id, fold home/away)
# =============================================================================

def _nba_load_canonical() -> list[dict]:
    path = get_canonical_games_json_path("nba")
    if not path or not path.exists():
        raise FileNotFoundError(f"Missing canonical JSON: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Canonical JSON must be a list: {path}")
    return data


def _nba_collapse_team_rows_to_game_level(rows: list[dict]) -> list[dict]:
    """Collapse two team-game rows per game into one game-level row with home_* / away_*."""
    games = defaultdict(dict)
    for r in rows:
        gid = r["game_id"]
        side = r["side"]

        if "game_id" not in games[gid]:
            games[gid].update({
                "game_id": r["game_id"],
                "game_date": r["game_date"],
                "nba_game_day_local": (r["game_date"] or "")[:10],
                "season_year": r["season_year"],
                "went_ot": r["went_ot"],
                "ot_minutes": r["ot_minutes"],
                "fatigue_diff_home_minus_away": r.get("fatigue_diff_home_minus_away"),
                f"{side}_injury_impact": r.get("injury_impact"),
                f"{side}_num_out": r.get("num_out"),
                f"{side}_num_questionable": r.get("num_questionable"),
            })

        games[gid].update({
            f"{side}_team_id": r["team_id"],
            f"{side}_team": r["team"],
            f"{side}_abbr": r["abbr"],
            f"{side}_points": r["points_scored"],
            f"{side}_rest_days": r["rest_days"],
            f"{side}_rest_bucket": r["rest_bucket"],
            f"{side}_fatigue_flag": r["fatigue_flag"],
            f"{side}_fatigue_score": r.get("fatigue_score"),
            f"{side}_avg_points_for": r["avg_points_for"],
            f"{side}_avg_points_against": r["avg_points_against"],
            f"{side}_net_rating": r["net_rating"],
            f"{side}_last5_points_for": r.get("last5_points_for"),
            f"{side}_last5_points_against": r.get("last5_points_against"),
            f"{side}_net_rating_last5": r.get("net_rating_last5"),
            f"{side}_team_3pm": r.get("team_3pm"),
            f"{side}_team_3pa": r.get("team_3pa"),
            f"{side}_team_3pt_pct": r.get("team_3pt_pct"),
        })

    return list(games.values())


def run_nba() -> None:
    rows = _nba_load_canonical()
    game_rows = _nba_collapse_team_rows_to_game_level(rows)
    write_game_level("nba", game_rows)

    json_path = get_game_level_json_path("nba")
    csv_path = get_game_level_csv_path("nba")
    log_info(f"Games written: {len(game_rows)}")
    log_info(f"JSON -> {json_path}")
    log_info(f"CSV  -> {csv_path}")


# =============================================================================
# NCAAM: One canonical row per game -> game-level schema (scores, margin, total)
# =============================================================================

def _ncaam_safe_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _ncaam_choose_score(primary_value, fallback_value) -> str:
    primary_num = _ncaam_safe_float(primary_value)
    if primary_num is not None:
        return str(int(primary_num)) if float(primary_num).is_integer() else str(primary_num)
    fallback_num = _ncaam_safe_float(fallback_value)
    if fallback_num is not None:
        return str(int(fallback_num)) if float(fallback_num).is_integer() else str(fallback_num)
    return ""


def _ncaam_compute_margin(home_score: str, away_score: str) -> str:
    home_num = _ncaam_safe_float(home_score)
    away_num = _ncaam_safe_float(away_score)
    if home_num is None or away_num is None:
        return ""
    value = home_num - away_num
    return str(int(value)) if float(value).is_integer() else str(round(value, 4))


def _ncaam_compute_total(home_score: str, away_score: str) -> str:
    home_num = _ncaam_safe_float(home_score)
    away_num = _ncaam_safe_float(away_score)
    if home_num is None or away_num is None:
        return ""
    value = home_num + away_num
    return str(int(value)) if float(value).is_integer() else str(round(value, 4))


def _ncaam_load_canonical() -> list[dict]:
    path = get_canonical_games_csv_path("ncaam")
    if not path.exists():
        raise FileNotFoundError(f"Missing canonical CSV: {path}")
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _ncaam_build_game_level_rows(rows: list[dict]) -> list[dict]:
    """One canonical row per game -> game-level schema (league-specific columns)."""
    out = []
    for row in rows:
        home_score = _ncaam_choose_score(
            row.get("box_home_score"),
            row.get("schedule_home_score"),
        )
        away_score = _ncaam_choose_score(
            row.get("box_away_score"),
            row.get("schedule_away_score"),
        )
        game_total = _ncaam_compute_total(home_score, away_score)
        margin_home = _ncaam_compute_margin(home_score, away_score)

        def _s(k):
            return (row.get(k) or "").strip()

        has_box = (
            _s("box_home_score") != "" and _s("box_away_score") != ""
        )
        has_schedule = (
            _s("schedule_home_score") != "" and _s("schedule_away_score") != ""
        )
        score_source = "boxscore" if has_box else ("schedule" if has_schedule else "")

        out.append({
            "canonical_game_id": _s("canonical_game_id"),
            "game_source_id": _s("game_source_id"),
            "espn_game_id": _s("espn_game_id"),
            "game_date": _s("game_date"),
            "season": _s("season"),
            "season_type": _s("season_type"),
            "status_name": _s("status_name"),
            "status_state": _s("status_state"),
            "completed_flag": _s("completed_flag"),
            "neutral_site_flag": _s("neutral_site_flag"),
            "venue_name": _s("venue_name"),
            "home_team_id": _s("home_team_id"),
            "away_team_id": _s("away_team_id"),
            "home_team_display": _s("home_team_display"),
            "away_team_display": _s("away_team_display"),
            "home_score": home_score,
            "away_score": away_score,
            "home_margin": margin_home,
            "game_total": game_total,
            "market_spread_home": _s("market_spread_home"),
            "market_spread_away": _s("market_spread_away"),
            "market_total": _s("market_total"),
            "market_home_moneyline": _s("market_home_moneyline"),
            "market_away_moneyline": _s("market_away_moneyline"),
            "line_join_status": _s("line_join_status"),
            "bookmaker_key": _s("bookmaker_key"),
            "bookmaker_title": _s("bookmaker_title"),
            "score_source": score_source,
            "mapping_status": _s("mapping_status"),
        })

    out.sort(key=lambda r: (r["game_date"], r["canonical_game_id"]))
    return out


def run_ncaam() -> None:
    from configs.leagues.league_ncaam import ensure_ncaam_dirs
    ensure_ncaam_dirs()

    rows = _ncaam_load_canonical()
    game_level_rows = _ncaam_build_game_level_rows(rows)

    if not game_level_rows:
        raise ValueError("No game-level rows produced")
    seen = set()
    for row in game_level_rows:
        cid = row["canonical_game_id"]
        if cid in seen:
            raise ValueError(f"Duplicate canonical_game_id: {cid}")
        seen.add(cid)

    write_game_level("ncaam", game_level_rows)

    from configs.leagues.league_ncaam import ensure_ncaam_dirs, BOXSCORES_PROCESSED_PATH
    ensure_ncaam_dirs()
    with open(BOXSCORES_PROCESSED_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=game_level_rows[0].keys(), extrasaction="ignore")
        w.writeheader()
        w.writerows(game_level_rows)

    csv_path = get_game_level_csv_path("ncaam")
    rows_with_scores = sum(
        1 for r in game_level_rows
        if (r.get("home_score") or "").strip() != "" and (r.get("away_score") or "").strip() != ""
    )
    rows_with_lines = sum(
        1 for r in game_level_rows
        if (r.get("line_join_status") or "").strip().lower() == "matched"
    )

    log_info(f"Loaded input rows:     {len(rows)}")
    log_info(f"Game-level output:     {csv_path}")
    log_info(f"Game-level rows:       {len(game_level_rows)}")
    log_info(f"Rows with scores:      {rows_with_scores}")
    log_info(f"Rows with matched lines: {rows_with_lines}")


# =============================================================================
# ENTRYPOINT
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Collapse to game level (NBA or NCAAM)")
    parser.add_argument("--league", required=True, choices=["nba", "ncaam"])
    parser.add_argument("--silent", action="store_true", help="Only print critical errors")
    args = parser.parse_args()
    set_silent(args.silent)
    if args.league == "nba":
        run_nba()
    else:
        run_ncaam()


if __name__ == "__main__":
    main()
