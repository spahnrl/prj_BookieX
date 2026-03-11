"""
d_gen_021_build_canonical_games.py

Unified build canonical games for NBA and NCAAM.

Pairs scheduled games with boxscore results using a shared lookup:
schedule + boxscore list -> keyed by game id (game_id for NBA, espn_game_id for NCAAM).

Uses utils.io_helpers for:
- load_schedule_joined(league)
- load_boxscores(league)
- get_canonical_games_csv_path(league), get_canonical_games_json_path(league)

Usage:
  python d_gen_021_build_canonical_games.py --league nba
  python d_gen_021_build_canonical_games.py --league ncaam

Forward-only: reads only joined schedule and boxscores (and NBA-derived rest/fatigue/rolling/last5).
Output paths unchanged so model runners (0051) do not break.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from configs.leagues.league_nba import DERIVED_DIR
from utils.io_helpers import (
    load_schedule_joined,
    load_boxscores,
    get_canonical_games_csv_path,
    get_canonical_games_json_path,
)
from utils.run_log import set_silent, log_info


# =============================================================================
# SHARED: Pair schedule with boxscore — single lookup by game id
# =============================================================================

def build_boxscore_lookup(box_rows: list[dict], id_key: str) -> dict[str, dict]:
    """
    Build lookup: game_id -> boxscore row.
    id_key: 'game_id' for NBA, 'espn_game_id' for NCAAM.
    Used to pair each scheduled game with its boxscore result.
    """
    lookup = {}
    for row in box_rows:
        gid = (row.get(id_key) or "").strip() if isinstance(row, dict) else ""
        if isinstance(gid, (int, float)):
            gid = str(gid).strip()
        if gid:
            lookup[gid] = row
    return lookup


# =============================================================================
# NBA: Join games + OT (boxscore) + rest + fatigue + rolling + last5 -> canonical rows
# =============================================================================

NBA_DATA_DIR = DERIVED_DIR
NBA_FILES = {
    "ot": "nba_boxscores_team.json",
    "rest": "nba_games_with_rest.json",
    "fatigue": "nba_games_with_fatigue.json",
    "team_rolling": "nba_team_rolling_averages.json",
    "team_last5": "nba_team_last5.json",
    "team_3pt": "nba_team_3pt_recent.json",
    "injuries": "nba_team_injury_impact.json",
}


def _nba_load_json(filename: str, required: bool = True) -> list:
    path = NBA_DATA_DIR / filename
    if not path.exists():
        if not required:
            return []
        raise FileNotFoundError(f"Missing: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _nba_rest_bucket(rest_days) -> str:
    if rest_days == 0:
        return "b2b"
    if rest_days == 1:
        return "1_day"
    if rest_days == 2:
        return "2_days"
    if rest_days is not None and rest_days >= 3:
        return "3_plus_days"
    return "unknown"


def _nba_build_canonical(
    games: list[dict],
    ot_map: dict[str, dict],
    rest_map: dict,
    fatigue_map: dict,
    rolling_map: dict,
    last5_map: dict,
    team_3pt_idx: dict,
    injury_idx: dict,
) -> list[dict]:
    canonical = []
    for g in games:
        game_id = g["game_id"]
        home_score = g.get("home_score")
        away_score = g.get("away_score")

        for side in ("home", "away"):
            opp_side = "away" if side == "home" else "home"
            team_id = g[f"{side}_team_id"]
            rest_days = rest_map.get(game_id, {}).get(f"{side}_rest_days")
            rest_bucket = _nba_rest_bucket(rest_days)

            rolling = rolling_map.get((game_id, team_id, side), {})
            last5 = last5_map.get((game_id, team_id, side), {})
            last5_points_for = last5.get("last5_points_for")
            last5_points_against = last5.get("last5_points_against")
            net_rating_last5 = (
                last5_points_for - last5_points_against
                if last5_points_for is not None and last5_points_against is not None
                else None
            )

            if side == "home":
                points_scored = home_score
                points_allowed = away_score
            else:
                points_scored = away_score
                points_allowed = home_score

            team_3pt = team_3pt_idx.get((game_id, team_id, side), {})
            injury = injury_idx.get((game_id, team_id), {})
            fatigue_record = fatigue_map.get(game_id, {})
            avg_points_for = rolling.get("rolling_avg_points_for")
            avg_points_against = rolling.get("rolling_avg_points_against")
            net_rating = (
                avg_points_for - avg_points_against
                if avg_points_for is not None and avg_points_against is not None
                else None
            )

            canonical.append({
                "game_id": game_id,
                "game_date": g["game_date"],
                "season_year": g["season_year"],
                "side": side,
                "team_id": team_id,
                "team": g[f"{side}_team"],
                "abbr": g[f"{side}_abbr"],
                "opponent_side": opp_side,
                "opponent_team_id": g[f"{opp_side}_team_id"],
                "opponent": g[f"{opp_side}_team"],
                "opponent_abbr": g[f"{opp_side}_abbr"],
                "points_scored": points_scored,
                "points_allowed": points_allowed,
                "went_ot": ot_map.get(game_id, {}).get("went_ot", False),
                "ot_minutes": ot_map.get(game_id, {}).get("ot_minutes", 0),
                "rest_days": rest_days,
                "rest_bucket": rest_bucket,
                "fatigue_flag": fatigue_record.get(f"{side}_fatigue_score", 0.0) > 0,
                "fatigue_score": fatigue_record.get(f"{side}_fatigue_score", 0.0),
                "fatigue_diff_home_minus_away": fatigue_record.get("fatigue_diff_home_minus_away", 0.0),
                "avg_points_for": avg_points_for,
                "avg_points_against": avg_points_against,
                "net_rating": net_rating,
                "last5_points_for": last5_points_for,
                "last5_points_against": last5_points_against,
                "net_rating_last5": net_rating_last5,
                "team_3pm": team_3pt.get("team_3pm"),
                "team_3pa": team_3pt.get("team_3pa"),
                "team_3pt_pct": team_3pt.get("team_3pt_pct"),
                "injury_impact": injury.get("injury_impact", 0.0),
                "num_out": injury.get("num_out", 0),
                "num_questionable": injury.get("num_questionable", 0),
            })
    return canonical


def run_nba() -> None:
    games = load_schedule_joined("nba")
    box_rows = load_boxscores("nba")
    ot_map = build_boxscore_lookup(box_rows, "game_id")

    rest_list = _nba_load_json(NBA_FILES["rest"])
    fatigue_list = _nba_load_json(NBA_FILES["fatigue"])
    rolling_list = _nba_load_json(NBA_FILES["team_rolling"])
    last5_list = _nba_load_json(NBA_FILES["team_last5"])
    team_3pt_list = _nba_load_json(NBA_FILES["team_3pt"], required=False)
    injury_list = _nba_load_json(NBA_FILES["injuries"], required=False)

    rest_map = {r["game_id"]: r for r in rest_list}
    fatigue_map = {f["game_id"]: f for f in fatigue_list}
    rolling_map = {(r["game_id"], r["team_id"], r["side"]): r for r in rolling_list}
    last5_map = {(r["game_id"], r["team_id"], r["side"]): r for r in last5_list}
    team_3pt_idx = {(r["game_id"], r["team_id"], r["side"]): r for r in team_3pt_list}
    injury_idx = {(r["game_id"], r["team_id"]): r for r in injury_list}

    canonical = _nba_build_canonical(
        games, ot_map, rest_map, fatigue_map,
        rolling_map, last5_map, team_3pt_idx, injury_idx,
    )

    csv_path = get_canonical_games_csv_path("nba")
    json_path = get_canonical_games_json_path("nba")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(canonical, f, indent=2)
    if canonical:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=canonical[0].keys())
            w.writeheader()
            w.writerows(canonical)

    log_info(f"Canonical rows: {len(canonical)}")
    log_info(f"CSV  -> {csv_path}")
    if json_path:
        log_info(f"JSON -> {json_path}")


# =============================================================================
# NCAAM: Schedule + boxscore by espn_game_id -> one row per game
# =============================================================================

def _ncaam_build_canonical_games(
    schedule_rows: list[dict],
    box_lookup: dict[str, dict],
) -> tuple[list[dict], dict[str, int]]:
    """One canonical row per espn_game_id; backfill team ids from boxscore when needed."""
    out = []
    seen_espn_ids: set[str] = set()
    diagnostics = {
        "skip_no_espn_game_id": 0,
        "skip_no_team_ids_no_backfill": 0,
        "backfilled_from_boxscore": 0,
    }

    for row in schedule_rows:
        mapping_status = (row.get("mapping_status") or "").strip().lower()
        home_team_id = (row.get("home_team_id") or "").strip()
        away_team_id = (row.get("away_team_id") or "").strip()
        espn_game_id = (row.get("espn_game_id") or "").strip()

        if not espn_game_id:
            diagnostics["skip_no_espn_game_id"] += 1
            continue
        if espn_game_id in seen_espn_ids:
            continue

        has_both_ids = bool(home_team_id and away_team_id)
        row_is_usable = mapping_status == "matched" or has_both_ids

        if not row_is_usable:
            box = box_lookup.get(espn_game_id, {})
            box_home = (box.get("home_team_id") or "").strip()
            box_away = (box.get("away_team_id") or "").strip()
            if box_home and box_away:
                home_team_id = home_team_id or box_home
                away_team_id = away_team_id or box_away
                if home_team_id and away_team_id:
                    row_is_usable = True
                    diagnostics["backfilled_from_boxscore"] += 1
                    if not (row.get("home_team_display") or "").strip():
                        row["home_team_display"] = (box.get("home_team_display") or "").strip()
                    if not (row.get("away_team_display") or "").strip():
                        row["away_team_display"] = (box.get("away_team_display") or "").strip()
            if not row_is_usable:
                diagnostics["skip_no_team_ids_no_backfill"] += 1
                continue

        seen_espn_ids.add(espn_game_id)
        box = box_lookup.get(espn_game_id, {})
        canonical_game_id = f"ncaam_{espn_game_id}"

        def _s(key):
            v = row.get(key)
            if v is None:
                return ""
            if isinstance(v, (int, float)):
                return str(v)
            return str(v).strip()

        def _b(key):
            v = box.get(key)
            return str(v).strip() if v is not None else ""

        out.append({
            "canonical_game_id": canonical_game_id,
            "game_source_id": _s("game_source_id"),
            "espn_game_id": espn_game_id,
            "game_date": _s("game_date"),
            "season": _s("season"),
            "season_type": _s("season_type"),
            "status_name": _s("status_name"),
            "status_state": _s("status_state"),
            "completed_flag": _s("completed_flag"),
            "neutral_site_flag": _s("neutral_site_flag"),
            "venue_name": _s("venue_name"),
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "home_team_display": _s("home_team_display"),
            "away_team_display": _s("away_team_display"),
            "schedule_home_team_raw": _s("home_team_raw"),
            "schedule_away_team_raw": _s("away_team_raw"),
            "schedule_home_score": _s("home_score"),
            "schedule_away_score": _s("away_score"),
            "box_home_score": _b("home_score"),
            "box_away_score": _b("away_score"),
            "box_home_winner": _b("home_winner"),
            "box_away_winner": _b("away_winner"),
            "source_system_schedule": _s("source_system"),
            "source_system_boxscore": _b("source_system"),
            "mapping_status": mapping_status or "matched",
        })

    out.sort(key=lambda r: (r["game_date"], r["espn_game_id"]))
    return out, diagnostics


def run_ncaam() -> None:
    from configs.leagues.league_ncaam import ensure_ncaam_dirs

    ensure_ncaam_dirs()
    schedule_rows = load_schedule_joined("ncaam")
    box_rows = load_boxscores("ncaam")
    box_lookup = build_boxscore_lookup(box_rows, "espn_game_id")

    canonical_rows, diagnostics = _ncaam_build_canonical_games(schedule_rows, box_lookup)

    if not canonical_rows:
        raise ValueError("No canonical game rows produced")
    seen = set()
    for row in canonical_rows:
        cid = row["canonical_game_id"]
        if cid in seen:
            raise ValueError(f"Duplicate canonical_game_id: {cid}")
        seen.add(cid)

    csv_path = get_canonical_games_csv_path("ncaam")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=canonical_rows[0].keys())
        w.writeheader()
        w.writerows(canonical_rows)

    with_boxscore = sum(
        1 for r in canonical_rows
        if (r.get("box_home_score") or "").strip() != "" or (r.get("box_away_score") or "").strip() != ""
    )
    without_boxscore = len(canonical_rows) - with_boxscore

    log_info(f"Loaded schedule rows:        {len(schedule_rows)}")
    log_info(f"Loaded boxscore rows:        {len(box_rows)}")
    log_info(f"Canonical games written to:  {csv_path}")
    log_info(f"Canonical rows:              {len(canonical_rows)}")
    log_info(f"Rows with boxscore data:     {with_boxscore}")
    log_info(f"Rows without boxscore data:  {without_boxscore}")
    log_info("---")
    log_info("Diagnostics (schedule rows skipped):")
    log_info(f"  No espn_game_id:           {diagnostics['skip_no_espn_game_id']}")
    log_info(f"  No team ids, no backfill:  {diagnostics['skip_no_team_ids_no_backfill']}")
    log_info(f"  Rows backfilled from box:  {diagnostics['backfilled_from_boxscore']}")


# =============================================================================
# ENTRYPOINT
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Build canonical games (NBA or NCAAM)")
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
