"""
b_gen_004_ingest_boxscores.py

Unified boxscore ingestion for NBA and NCAAM.

Behavior (same for both leagues):
- Finalized protection: if a boxscore for a game is already saved and marked
  final, do not re-request or overwrite it.
- Merge logic: never overwrite a previous row that is finalized; new rows
  overwrite non-final previous for the same game id.
- JSON-first: primary output via utils.io_helpers (save_boxscores, get_boxscore_path).
- Legacy CSV: audit only; same data, CSV for downstream/audit compat.

Usage:
  python b_gen_004_ingest_boxscores.py --league nba
  python b_gen_004_ingest_boxscores.py --league ncaam

Forward-only: reads only prior artifacts (schedule/games input + previous
boxscore output); writes only boxscore JSON + CSV. No circular dependencies.
"""

from __future__ import annotations

import argparse
import csv
import json
import requests
import sys
from pathlib import Path
from datetime import date
from time import sleep

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from configs.leagues.league_nba import BOXSCORES_TEAM_CSV_PATH, SCHEDULE_JOINED_PATH
from utils.io_helpers import (
    get_boxscore_path,
    load_previous_boxscores_by_id,
    save_boxscores,
)
from utils.run_log import set_silent, log_info, log_error


# =============================================================================
# SHARED: FINALIZED PROTECTION + MERGE (identical logic for both leagues)
# =============================================================================

def merge_with_previous(
    previous_by_id: dict[str, dict],
    new_results: list[dict],
    *,
    get_id: callable,
    is_boxscore_final: callable,
) -> list[dict]:
    """
    Merge new boxscore rows with previous. Never overwrite a previous row
    that is finalized. New rows overwrite non-final previous for same game id.
    get_id: callable(row) -> game id string.
    """
    by_id = dict(previous_by_id)
    for row in new_results:
        gid = get_id(row)
        if gid is None:
            continue
        gid = str(gid).strip() if not isinstance(gid, str) else gid.strip()
        if not gid:
            continue
        if gid in by_id and is_boxscore_final(by_id[gid]):
            continue
        by_id[gid] = row
    return list(by_id.values())


def write_legacy_csv(rows: list[dict], csv_path: Path) -> None:
    """Legacy CSV for audit; omit list-like fields if present."""
    if not rows:
        return
    # Exclude keys that are not CSV-friendly (e.g. nested lists)
    exclude = {"odds_history"}
    fieldnames = [k for k in rows[0].keys() if k not in exclude]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# =============================================================================
# NBA: INPUT, FETCH, PARSE, FINALIZED, PATHS
# =============================================================================

NBA_INPUT_PATH = SCHEDULE_JOINED_PATH
NBA_CSV_PATH = BOXSCORES_TEAM_CSV_PATH
NBA_BOXSCORE_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"
NBA_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
}


def _nba_is_boxscore_final(row: dict) -> bool:
    """True if this record has final boxscore (do not re-fetch or overwrite)."""
    return (row.get("_boxscore_status") or "").strip() == "FINAL"


def _nba_is_final_from_api(box: dict) -> bool:
    """NBA gameStatus: 1=Scheduled, 2=In Progress, 3=Final."""
    try:
        return box["game"]["gameStatus"] == 3
    except Exception:
        return False


def _nba_extract_ot_info(box: dict) -> tuple[bool, int]:
    """Returns (went_ot, ot_minutes)."""
    try:
        periods = box["game"]["period"]
        if periods <= 4:
            return False, 0
        ot_periods = periods - 4
        return True, ot_periods * 5
    except Exception:
        return False, 0


def _nba_fetch_boxscore(game_id: str) -> dict | None:
    url = NBA_BOXSCORE_URL.format(game_id=game_id)
    try:
        resp = requests.get(url, headers=NBA_HEADERS, timeout=(5, 8))
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _nba_is_eligible_game_day(record: dict) -> bool:
    """Only process games on or before today (avoid polling future)."""
    try:
        from utils.datetime_bridge import derive_game_day_local
        derived_day = derive_game_day_local(
            commence_time_utc=record.get("odds_commence_time_utc") or record.get("commence_time_utc") or "",
            league="NBA",
        )
        return date.fromisoformat(derived_day) <= date.today()
    except Exception:
        return False


def _nba_enrich_one(g: dict, box: dict | None) -> dict:
    """Build one enriched record from game + box (or defaults)."""
    record = dict(g)
    if box and _nba_is_final_from_api(box):
        went_ot, ot_minutes = _nba_extract_ot_info(box)
        record["_boxscore_status"] = "FINAL"
    else:
        went_ot = record.get("went_ot", False)
        ot_minutes = record.get("ot_minutes", 0)
        record["_boxscore_status"] = "SKIPPED_NOT_FINAL"
    record["went_ot"] = went_ot
    record["ot_minutes"] = ot_minutes
    record["home_went_ot"] = went_ot
    record["away_went_ot"] = went_ot
    return record


def run_nba() -> None:
    if not NBA_INPUT_PATH.exists():
        raise FileNotFoundError(f"Missing NBA games input: {NBA_INPUT_PATH}")

    with open(NBA_INPUT_PATH, "r", encoding="utf-8") as f:
        games = json.load(f)
    previous_by_id = load_previous_boxscores_by_id("nba", "game_id")

    to_process = []
    skipped_final = 0
    for g in games:
        game_id = (g.get("game_id") or "").strip()
        if isinstance(game_id, (int, float)):
            game_id = str(game_id).strip()
        if not game_id:
            continue
        prev = previous_by_id.get(game_id)
        if prev and _nba_is_boxscore_final(prev):
            skipped_final += 1
            continue
        if prev:
            # Existing but not final: re-fetch only if eligible (game day <= today)
            if not _nba_is_eligible_game_day(g):
                continue
        to_process.append(g)

    new_results = []
    for i, g in enumerate(to_process):
        game_id = (g.get("game_id") or "").strip()
        if isinstance(game_id, (int, float)):
            game_id = str(game_id)
        log_info(f"Fetching game_id={game_id}")
        box = _nba_fetch_boxscore(game_id)
        record = _nba_enrich_one(g, box)
        new_results.append(record)
        if i % 10 == 0:
            sleep(0.4)
        if i % 25 == 0 and to_process:
            log_info(f"Processed {i}/{len(to_process)} games")

    # Merge: previous + new, never overwrite final (shared logic)
    merged = merge_with_previous(
        previous_by_id,
        new_results,
        get_id=lambda r: r.get("game_id"),
        is_boxscore_final=_nba_is_boxscore_final,
    )
    merged.sort(key=lambda g: (
        str(g.get("season_year", "")),
        str(g.get("game_date", "")),
        str(g.get("game_id", "")),
    ))

    if not merged:
        log_info("No boxscores to write.")
        return

    save_boxscores("nba", merged)
    write_legacy_csv(merged, NBA_CSV_PATH)

    log_info(f"Boxscores JSON written: {get_boxscore_path('nba')}")
    log_info(f"Boxscores CSV (audit):  {NBA_CSV_PATH}")
    log_info(f"Total rows:            {len(merged)}")
    log_info(f"Skipped (already final): {skipped_final}")
    log_info(f"New/refreshed this run: {len(new_results)}")


# =============================================================================
# NCAAM: INPUT, FETCH, PARSE, FINALIZED, PATHS
# =============================================================================

NCAAM_ESPN_URL = (
    "https://site.web.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={}"
)


def _ncaam_is_boxscore_final(row: dict) -> bool:
    """True if this boxscore row has final scores (do not re-fetch or overwrite)."""
    home = row.get("home_score")
    away = row.get("away_score")
    if home is None or away is None:
        return False
    if isinstance(home, str) and home.strip() == "":
        return False
    if isinstance(away, str) and away.strip() == "":
        return False
    return True


def _ncaam_fetch_boxscore(event_id: str) -> dict | None:
    try:
        r = requests.get(NCAAM_ESPN_URL.format(event_id), timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log_error(f"Failed to fetch {event_id}: {e}")
        return None


def _ncaam_parse_boxscore(game: dict, data: dict) -> dict | None:
    try:
        competitions = data.get("header", {}).get("competitions", [])
        if not competitions:
            return None
        competitors = competitions[0].get("competitors", [])
        if len(competitors) < 2:
            return None
        home = away = None
        for comp in competitors:
            side = str(comp.get("homeAway", "")).lower()
            if side == "home":
                home = comp
            elif side == "away":
                away = comp
        if not home or not away:
            return None
        return {
            "game_source_id": game.get("game_source_id", ""),
            "espn_game_id": game.get("espn_game_id", ""),
            "game_date": game.get("game_date", ""),
            "home_team_id": game.get("home_team_id", ""),
            "away_team_id": game.get("away_team_id", ""),
            "home_team_display": game.get("home_team_display", ""),
            "away_team_display": game.get("away_team_display", ""),
            "home_score": home.get("score"),
            "away_score": away.get("score"),
            "home_winner": int(bool(home.get("winner", False))),
            "away_winner": int(bool(away.get("winner", False))),
            "source_system": "espn_summary",
        }
    except Exception as e:
        log_error(f"Parse failed for event_id={game.get('espn_game_id')}: {e}")
        return None


def run_ncaam() -> None:
    from configs.leagues.league_ncaam import SCHEDULE_MAPPED_PATH, INTERIM_DIR, ensure_ncaam_dirs
    ncaam_csv_path = INTERIM_DIR / "ncaam_boxscores_raw.csv"

    ensure_ncaam_dirs()
    if not SCHEDULE_MAPPED_PATH.exists():
        raise FileNotFoundError(f"Missing schedule: {SCHEDULE_MAPPED_PATH}")

    with open(SCHEDULE_MAPPED_PATH, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    schedule = [r for r in rows if r.get("mapping_status") == "matched"]
    log_info(f"Total schedule rows: {len(rows)}; matched: {len(schedule)}")

    previous_by_id = load_previous_boxscores_by_id("ncaam", "espn_game_id")
    new_results = []
    skipped_final = 0

    for game in schedule:
        event_id = (game.get("espn_game_id") or "").strip()
        if not event_id:
            continue
        if event_id in previous_by_id and _ncaam_is_boxscore_final(previous_by_id[event_id]):
            skipped_final += 1
            continue
        log_info(f"Fetching event_id={event_id}")
        data = _ncaam_fetch_boxscore(event_id)
        if not data:
            continue
        parsed = _ncaam_parse_boxscore(game, data)
        if parsed:
            new_results.append(parsed)

    merged = merge_with_previous(
        previous_by_id,
        new_results,
        get_id=lambda r: r.get("espn_game_id"),
        is_boxscore_final=_ncaam_is_boxscore_final,
    )
    merged.sort(key=lambda r: (str(r.get("game_date", "")), str(r.get("espn_game_id", ""))))

    if not merged:
        log_info("No boxscores to write.")
        return

    save_boxscores("ncaam", merged)
    write_legacy_csv(merged, ncaam_csv_path)

    log_info(f"Boxscores JSON written: {get_boxscore_path('ncaam')}")
    log_info(f"Boxscores CSV (audit):  {ncaam_csv_path}")
    log_info(f"Total rows:             {len(merged)}")
    log_info(f"Skipped (already final): {skipped_final}")
    log_info(f"New this run:           {len(new_results)}")


# =============================================================================
# ENTRYPOINT
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest boxscores (NBA or NCAAM)")
    parser.add_argument("--league", required=True, choices=["nba", "ncaam"], help="League to process")
    parser.add_argument("--silent", action="store_true", help="Only print critical errors")
    args = parser.parse_args()
    set_silent(args.silent)
    if args.league == "nba":
        run_nba()
    else:
        run_ncaam()


if __name__ == "__main__":
    main()
