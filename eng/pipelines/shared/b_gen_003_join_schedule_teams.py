"""
b_gen_003_join_schedule_teams.py

Unified join schedule with team metadata for NBA and NCAAM.

- Reads normalized schedule (001 output) and league-specific team map via io_helpers.
- NBA: direct team_id lookup; emits only rows where both home and away match.
- NCAAM: name resolution (norm_key + state semantics); preserves all rows,
  adds home_team_id, away_team_id, mapping_status; writes unmatched audit.

Usage:
  python b_gen_003_join_schedule_teams.py --league nba
  python b_gen_003_join_schedule_teams.py --league ncaam

Forward-only: reads only schedule raw JSON and team map; writes joined JSON + legacy CSV audit.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from collections import Counter

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from configs.leagues.league_nba import DERIVED_DIR
from utils.io_helpers import (
    get_schedule_joined_path,
    get_schedule_raw_path,
    get_team_map_path,
    load_schedule_raw,
    save_schedule_joined,
)
from utils.run_log import set_silent, log_info


# =============================================================================
# SHARED: LEGACY CSV WRITE
# =============================================================================

def write_legacy_csv(rows: list[dict], csv_path: Path) -> None:
    """Audit CSV: same rows as JSON."""
    if not rows:
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys(), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    log_info(f"Legacy audit CSV: {csv_path}")


# =============================================================================
# NBA: TEAM LOOKUP BY ID, JOIN (both must match)
# =============================================================================

def _nba_canonical_game_day(game_date: str) -> str:
    return (game_date or "")[:10]


def _nba_load_team_lookup() -> dict:
    path = get_team_map_path("nba")
    if not path.exists():
        raise FileNotFoundError(f"Missing team map: {path}")
    with open(path, "r", encoding="utf-8") as f:
        teams = json.load(f)
    return {str(t["team_id"]): t for t in teams}


def _nba_join_schedule(schedule: list[dict], team_lookup: dict) -> list[dict]:
    joined = []
    for g in schedule:
        home = team_lookup.get(str(g.get("home_team_id")))
        away = team_lookup.get(str(g.get("away_team_id")))
        if home is None or away is None:
            continue
        game_date = g.get("game_date")
        game_start_date_utc = g.get("game_start_date_utc")
        game_start_time_utc = g.get("game_start_time_utc")
        joined.append({
            "game_id": g["game_id"],
            "game_date": game_date,
            "canonical_game_day": _nba_canonical_game_day(game_date),
            "game_start_date_utc": game_start_date_utc,
            "game_start_time_utc": game_start_time_utc,
            "game_start_datetime_utc": (
                f"{game_start_date_utc}T{game_start_time_utc}"
                if game_start_date_utc and game_start_time_utc else None
            ),
            "season_year": g.get("season_year"),
            "status": g.get("status"),
            "home_team_id": g.get("home_team_id"),
            "home_team": home.get("team_name"),
            "home_abbr": home.get("abbreviation"),
            "home_conference": home.get("conference"),
            "home_division": home.get("division"),
            "home_score": g.get("home_team_score"),
            "away_team_id": g.get("away_team_id"),
            "away_team": away.get("team_name"),
            "away_abbr": away.get("abbreviation"),
            "away_conference": away.get("conference"),
            "away_division": away.get("division"),
            "away_score": g.get("away_team_score"),
            "is_playoff": g.get("is_playoff"),
        })
    return joined


def run_nba() -> None:
    schedule = load_schedule_raw("nba")
    team_lookup = _nba_load_team_lookup()
    joined = _nba_join_schedule(schedule, team_lookup)

    save_schedule_joined("nba", joined)
    csv_path = DERIVED_DIR / "nba_games_joined.csv"
    write_legacy_csv(joined, csv_path)

    log_info(f"Schedule JSON: {get_schedule_joined_path('nba')}")
    log_info(f"Schedule rows: {len(schedule)}; team map entries: {len(team_lookup)}; joined: {len(joined)}")


# =============================================================================
# NCAAM: TEAM LOOKUP BY NORM KEY, RESOLVE NAME, MAP ALL ROWS
# =============================================================================

def _ncaam_has_state_suffix_semantics(norm_key: str) -> bool:
    v = (norm_key or "").strip().lower()
    return v.endswith("state") or v.endswith("st")


def _ncaam_normalize_name(value: str) -> str:
    text = (value or "").strip().lower()
    text = text.replace("&", " and ").replace("'", "").replace(".", " ").replace("-", " ").replace("/", " ").replace(",", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _ncaam_build_team_norm_key(value: str) -> str:
    return _ncaam_normalize_name(value).replace(" ", "")


def _ncaam_load_team_lookup() -> list[dict]:
    path = get_team_map_path("ncaam")
    if not path.exists():
        raise FileNotFoundError(f"Missing team map: {path}")
    with open(path, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    lookup_rows = []
    for row in rows:
        team_id = (row.get("team_id") or "").strip()
        team_display = (row.get("team_display") or "").strip()
        team_name_norm_key = (row.get("team_name_norm_key") or "").strip()
        if not team_id or not team_name_norm_key:
            continue
        lookup_rows.append({
            "mapped_team_id": team_id,
            "mapped_team_display": team_display,
            "team_name_norm_key": team_name_norm_key,
            "lookup_source": "ncaam_team_map_norm_key_contains",
        })
    lookup_rows.sort(key=lambda r: len(r["team_name_norm_key"]), reverse=True)
    return lookup_rows


def _ncaam_resolve_team_name(raw_name: str, team_lookup: list[dict]) -> dict | None:
    if not raw_name:
        return None
    raw_norm_key = _ncaam_build_team_norm_key(raw_name)
    if not raw_norm_key:
        return None
    raw_has_state = _ncaam_has_state_suffix_semantics(raw_norm_key)
    matches = []
    for candidate in team_lookup:
        map_key = (candidate.get("team_name_norm_key") or "").strip().lower()
        if not map_key:
            continue
        map_has_state = _ncaam_has_state_suffix_semantics(map_key)
        if map_has_state != raw_has_state:
            continue
        if map_key in raw_norm_key:
            matches.append(candidate)
    if not matches:
        return None
    exact = [m for m in matches if m["team_name_norm_key"] == raw_norm_key]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    matches.sort(key=lambda m: len(m["team_name_norm_key"]), reverse=True)
    top_len = len(matches[0]["team_name_norm_key"])
    top = [m for m in matches if len(m["team_name_norm_key"]) == top_len]
    if len(top) == 1:
        return top[0]
    return None


def _ncaam_map_schedule_rows(schedule_rows: list[dict], team_lookup: list[dict]) -> list[dict]:
    out = []
    for row in schedule_rows:
        home_team_raw = (row.get("home_team_raw") or "").strip()
        away_team_raw = (row.get("away_team_raw") or "").strip()
        home_match = _ncaam_resolve_team_name(home_team_raw, team_lookup)
        away_match = _ncaam_resolve_team_name(away_team_raw, team_lookup)

        joined = dict(row)
        joined["home_team_id"] = home_match["mapped_team_id"] if home_match else ""
        joined["away_team_id"] = away_match["mapped_team_id"] if away_match else ""
        joined["home_team_display"] = home_match["mapped_team_display"] if home_match else ""
        joined["away_team_display"] = away_match["mapped_team_display"] if away_match else ""
        joined["home_lookup_source"] = home_match["lookup_source"] if home_match else "unmatched"
        joined["away_lookup_source"] = away_match["lookup_source"] if away_match else "unmatched"

        game_id = (joined.get("game_id") or "").strip()
        joined["espn_game_id"] = game_id
        joined["game_source_id"] = game_id

        if home_match and away_match:
            joined["mapping_status"] = "matched"
        elif home_match or away_match:
            joined["mapping_status"] = "partial"
        else:
            joined["mapping_status"] = "unmatched"
        out.append(joined)
    return out


def _ncaam_build_unmatched_audit(mapped_rows: list[dict]) -> list[dict]:
    counter = Counter()
    for row in mapped_rows:
        home_raw = (row.get("home_team_raw") or "").strip()
        away_raw = (row.get("away_team_raw") or "").strip()
        if (row.get("home_team_id") or "").strip() == "" and home_raw:
            counter[("home", home_raw)] += 1
        if (row.get("away_team_id") or "").strip() == "" and away_raw:
            counter[("away", away_raw)] += 1
    audit = []
    for (source_side, team_name), times_seen in sorted(counter.items(), key=lambda x: (x[0][1], x[0][0])):
        audit.append({
            "source_side": source_side,
            "team_name_raw": team_name,
            "team_name_normalized": _ncaam_normalize_name(team_name),
            "team_name_norm_key": _ncaam_build_team_norm_key(team_name),
            "times_seen": times_seen,
            "notes": "",
        })
    return audit


def run_ncaam() -> None:
    from configs.leagues.league_ncaam import SCHEDULE_MAPPED_PATH, MARKET_AUDIT_DIR, ensure_ncaam_dirs

    ensure_ncaam_dirs()
    schedule_rows = load_schedule_raw("ncaam")
    team_lookup = _ncaam_load_team_lookup()
    mapped_rows = _ncaam_map_schedule_rows(schedule_rows, team_lookup)
    unmatched_audit = _ncaam_build_unmatched_audit(mapped_rows)

    save_schedule_joined("ncaam", mapped_rows)
    write_legacy_csv(mapped_rows, SCHEDULE_MAPPED_PATH)

    unmatched_path = MARKET_AUDIT_DIR / "ncaam_schedule_unmatched_teams.csv"
    unmatched_path.parent.mkdir(parents=True, exist_ok=True)
    with open(unmatched_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["source_side", "team_name_raw", "team_name_normalized", "team_name_norm_key", "times_seen", "notes"])
        w.writeheader()
        w.writerows(unmatched_audit)

    matched = sum(1 for r in mapped_rows if (r.get("mapping_status") or "") == "matched")
    partial = sum(1 for r in mapped_rows if (r.get("mapping_status") or "") == "partial")
    unmatched = sum(1 for r in mapped_rows if (r.get("mapping_status") or "") == "unmatched")

    log_info(f"Schedule JSON: {get_schedule_joined_path('ncaam')}")
    log_info(f"Legacy CSV:   {SCHEDULE_MAPPED_PATH}")
    log_info(f"Unmatched audit: {unmatched_path}")
    log_info(f"Schedule rows: {len(schedule_rows)}; team map: {len(team_lookup)}; matched: {matched}; partial: {partial}; unmatched: {unmatched}")


# =============================================================================
# ENTRYPOINT
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Join schedule with team map (NBA or NCAAM)")
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
