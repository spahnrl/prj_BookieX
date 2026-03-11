"""
tools/fetch_missing_raw.py

Staged Recovery – Pull: Build true 3-season universe, deep audit, fetch Missing/Empty, save to temp.

Task 1 – Build the True Universe:
  NBA: MUST open data/nba/raw/nba_schedule.json, filter season_year 2023, 2024, 2025 (~3,600+ games).
  NCAAM: MUST crawl data/ncaam/raw/ and parse every ncaam_schedule_raw_*.json; dedupe by game_id.
  Validation: Print League | Season | Game Count; raise if any NBA season has 0 or < 800.

Task 2 – Deep Audit:
  Cross-reference universe against data/external/odds_api_raw.json (NBA) and NCAAM market folder.
  Identify Missing (no entry) or Empty (entry exists but bookmakers/outcomes empty).

Task 3 – Staged Execution:
  NBA: Fetch Missing/Empty, save to data/temp_historical_odds.json.
  NCAAM: Fetch Missing/Empty, save to data/temp_ncaam_historical_odds.json. Use --limit to cap fetches (e.g. 500) for API token control.

Usage:
  python tools/fetch_missing_raw.py [--limit N] [--league nba|ncaam|all]
  python tools/fetch_missing_raw.py --limit 200 --league nba   # NBA only, cap 200 fetches

  # Historical odds (v4/historical/sports/.../odds). Token guard: only skip date if >= 5 non-empty games.
  python tools/fetch_missing_raw.py --historical-date 2025-10-22
  python tools/fetch_missing_raw.py --historical-start 2025-10-20 --historical-end 2026-01-20
  # NCAAM wide-angle crawl (Tip-off Tuesday 2025-11-04), 1,000-game sprint:
  python tools/fetch_missing_raw.py --league ncaam --historical-start 2025-11-04 --historical-end 2026-03-01 --limit 1000

Requires: ODDS_API_KEY in environment.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

TARGET_SEASON_YEARS = (2023, 2024, 2025)
CURRENT_SEASON = 2025  # Only this season triggers validation failure if missing
NBA_MIN_GAMES_PER_SEASON = 800
MASTER_ODDS_PATH = PROJECT_ROOT / "data" / "external" / "odds_api_raw.json"
NCAAM_MARKET_RAW_DIR = PROJECT_ROOT / "data" / "ncaam" / "market" / "raw"
TEMP_OUTPUT_PATH = PROJECT_ROOT / "data" / "temp_historical_odds.json"
TEMP_NCAAM_OUTPUT_PATH = PROJECT_ROOT / "data" / "temp_ncaam_historical_odds.json"

BASE_URL = "https://api.the-odds-api.com/v4/sports"
HISTORICAL_BASE_URL = "https://api.the-odds-api.com/v4/historical/sports"
MARKETS = "spreads,totals,h2h"
REGIONS = "us"
ODDS_FORMAT = "american"

API_KEY = os.getenv("ODDS_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing ODDS_API_KEY. Set in .env or environment.")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _normalize_team(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s).strip()).upper()


def _normalize_date(d: str) -> str:
    if not d:
        return ""
    d = str(d).strip()[:10]
    return d.replace("-", "") if len(d) == 10 else ""


def _date_adjacent(ymd: str, delta_days: int) -> str:
    """Return YYYYMMDD for ymd + delta_days (e.g. +/- 1 for 24h window). ymd is YYYYMMDD."""
    if not ymd or len(ymd) != 8:
        return ""
    try:
        dt = datetime(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))
        adj = dt + timedelta(days=delta_days)
        return adj.strftime("%Y%m%d")
    except Exception:
        return ""


def _lookup_nba_event_id(
    event_key_to_id: dict[tuple[str, str, str], str],
    dt: str,
    home: str,
    away: str,
) -> str | None:
    """Match schedule game to API event_id. Tries exact date then +/- 1 day (fuzzy 24h window)."""
    if not dt or not (home or away):
        return None
    key = (dt, home, away)
    if key in event_key_to_id:
        return event_key_to_id[key]
    for delta in (-1, 1):
        adj = _date_adjacent(dt, delta)
        if adj and (adj, home, away) in event_key_to_id:
            return event_key_to_id[(adj, home, away)]
    return None


def _derive_season_year_from_game_date(game_date: str) -> int | None:
    if not game_date or len(str(game_date).strip()) < 7:
        return None
    try:
        s = str(game_date).strip()[:10]
        y = int(s[:4])
        m = int(s[5:7]) if len(s) >= 7 else 1
        if m >= 8:
            return y
        return y - 1
    except Exception:
        return None


def is_game_empty(game: dict) -> bool:
    """True if no bookmakers or no spreads/totals outcomes."""
    if not game or not isinstance(game, dict):
        return True
    bookmakers = game.get("bookmakers") or []
    if not bookmakers:
        return True
    has_spread_or_total = False
    for b in bookmakers:
        if not isinstance(b, dict):
            continue
        for m in b.get("markets") or []:
            if not isinstance(m, dict):
                continue
            if m.get("key") not in ("spreads", "totals"):
                continue
            outcomes = m.get("outcomes") or []
            if outcomes:
                has_spread_or_total = True
                break
        if has_spread_or_total:
            break
    return not has_spread_or_total


# -----------------------------------------------------------------------------
# Task 1: Build the True Universe (aggregate all sources)
# -----------------------------------------------------------------------------

def _load_nba_universe_aggregated() -> list[dict]:
    """
    Glob all data/nba/raw/nba_schedule*.json. Filter season_year 2023, 2024, 2025.
    Resolve team names via team map for API matching. Dedupe by game_id.
    """
    from utils.io_helpers import get_schedule_raw_path, get_team_map_path

    raw_dir = get_schedule_raw_path("nba").parent
    if not raw_dir.exists():
        return []

    team_map_path = get_team_map_path("nba")
    team_by_id = {}
    if team_map_path.exists():
        with open(team_map_path, "r", encoding="utf-8") as f:
            tm = json.load(f)
        for t in tm if isinstance(tm, list) else [tm]:
            tid = t.get("team_id") or t.get("id")
            if tid is not None:
                team_by_id[str(tid)] = (t.get("team_name") or t.get("full_name") or "").strip()

    seen = set()
    out = []
    for path in sorted(raw_dir.glob("nba_schedule*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                rows = json.load(f)
        except Exception:
            continue
        if not isinstance(rows, list):
            continue
        for g in rows:
            sy = g.get("season_year")
            if sy not in TARGET_SEASON_YEARS:
                continue
            gdate = (g.get("game_date") or "")[:10] if g.get("game_date") else ""
            gid = str(g.get("game_id") or "").strip()
            if not gid or gid in seen:
                continue
            seen.add(gid)
            hid = str(g.get("home_team_id") or "")
            aid = str(g.get("away_team_id") or "")
            out.append({
                "game_id": gid,
                "game_date": gdate or (str(g.get("game_date") or "")[:10]),
                "season_year": int(sy) if sy is not None else None,
                "home_team": team_by_id.get(hid, ""),
                "away_team": team_by_id.get(aid, ""),
            })
    return out


def _load_ncaam_universe_aggregated() -> list[dict]:
    """
    Glob all data/ncaam/raw/ncaam_schedule_raw_*.json and load master ncaam_schedule_raw.json.
    Parse each file; deduplicate by game_id. Include season_year for validation.
    """
    raw_dir = PROJECT_ROOT / "data" / "ncaam" / "raw"
    if not raw_dir.exists():
        return []

    seen = set()
    out = []

    # Master flat list (merged output from build_historical_schedules / b_gen_001)
    master_path = raw_dir / "ncaam_schedule_raw.json"
    if master_path.exists():
        try:
            with open(master_path, "r", encoding="utf-8") as f:
                rows = json.load(f)
            if isinstance(rows, list):
                for ev in rows:
                    if not isinstance(ev, dict):
                        continue
                    gid = str(ev.get("game_id") or ev.get("id") or "").strip()
                    if not gid or gid in seen:
                        continue
                    sy = ev.get("season_year")
                    if sy is not None and sy not in TARGET_SEASON_YEARS and sy != 2026:
                        continue
                    gdate = (ev.get("game_date") or ev.get("date") or "")[:10]
                    if sy is None and gdate:
                        _y = int(gdate[:4]) if len(gdate) >= 4 else None
                        _m = int(gdate[5:7]) if len(gdate) >= 7 else None
                        if _y is not None and _m is not None:
                            sy = _y if _m >= 8 else _y - 1
                    if sy is not None and sy not in (2023, 2024, 2025, 2026):
                        continue
                    seen.add(gid)
                    home = (ev.get("home_team_raw") or ev.get("home_team") or "").strip()
                    away = (ev.get("away_team_raw") or ev.get("away_team") or "").strip()
                    out.append({"game_id": gid, "game_date": gdate, "season_year": int(sy) if sy is not None else None, "home_team": home, "away_team": away})
        except Exception:
            pass

    # All ncaam_schedule_raw_*.json (date-stamped or date-range payloads)
    for path in sorted(raw_dir.glob("ncaam_schedule_raw_*.json")):
        if path.name == "ncaam_schedule_raw_latest.json":
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        leagues = data.get("leagues") or []
        file_season_year = None
        if leagues and isinstance(leagues[0], dict):
            s = (leagues[0].get("season") or {})
            if isinstance(s, dict):
                file_season_year = s.get("year")
        events = data.get("events") or []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            eid = str(ev.get("id") or ev.get("game_id") or "").strip()
            if not eid or eid in seen:
                continue
            gdate = (ev.get("date") or ev.get("game_date") or "")[:10]
            sy = (ev.get("season") or {})
            if isinstance(sy, dict):
                sy = sy.get("year")
            sy = sy or file_season_year
            if sy is not None and sy not in TARGET_SEASON_YEARS and sy != 2026:
                continue
            if sy is None and gdate:
                _y = int(gdate[:4]) if len(gdate) >= 4 else None
                _m = int(gdate[5:7]) if len(gdate) >= 7 else None
                if _y is not None and _m is not None:
                    sy = _y if _m >= 8 else _y - 1
            if sy is not None and sy not in (2023, 2024, 2025, 2026):
                continue
            seen.add(eid)
            home = away = ""
            for comp in (ev.get("competitions") or [])[:1]:
                for c in comp.get("competitors") or []:
                    ha = str(c.get("homeAway") or "").lower()
                    team = c.get("team") or {}
                    name = (team.get("displayName") or team.get("name") or "").strip()
                    if ha == "home":
                        home = name
                    elif ha == "away":
                        away = name
            out.append({
                "game_id": eid,
                "game_date": gdate,
                "season_year": int(sy) if sy is not None else None,
                "home_team": home,
                "away_team": away,
            })
    return out


def _season_counts(games: list[dict], league_label: str) -> dict[int, int]:
    """Return {season_year: count} for 2023, 2024, 2025."""
    counts = {y: 0 for y in TARGET_SEASON_YEARS}
    for g in games:
        sy = g.get("season_year")
        if sy in TARGET_SEASON_YEARS:
            counts[sy] = counts.get(sy, 0) + 1
        elif sy == 2026 and league_label == "NCAAM":
            counts[2025] = counts.get(2025, 0) + 1
    return counts


def _print_validation_table(nba_games: list, ncaam_games: list) -> None:
    print("\n  League | Season | Game Count")
    print("  -------+--------+-----------")
    nba_counts = _season_counts(nba_games, "NBA")
    for sy in TARGET_SEASON_YEARS:
        c = nba_counts.get(sy, 0)
        print(f"  NBA    | {sy}     | {c}")
    ncaam_counts = _season_counts(ncaam_games, "NCAAM")
    for sy in TARGET_SEASON_YEARS:
        c = ncaam_counts.get(sy, 0)
        print(f"  NCAAM  | {sy}     | {c}")
    print("  -------+--------+-----------\n")


def _validate_universe(nba_games: list, ncaam_games: list, league: str = "all") -> None:
    """
    Only raise if current season (2025) is missing games for the league(s) being run.
    NBA 2023/2024 with 0 games: print warning and continue (backlog).
    """
    nba_counts = _season_counts(nba_games, "NBA")
    ncaam_counts = _season_counts(ncaam_games, "NCAAM")
    for sy in TARGET_SEASON_YEARS:
        nba_c = nba_counts.get(sy, 0)
        ncaam_c = ncaam_counts.get(sy, 0)
        if sy == CURRENT_SEASON:
            if league in ("nba", "all"):
                if nba_c == 0:
                    raise SystemExit(
                        f"Validation failed: NBA season {sy} (current) has 0 games. "
                        f"Ensure data/nba/raw/nba_schedule*.json includes season_year {sy}."
                    )
                if nba_c < NBA_MIN_GAMES_PER_SEASON:
                    raise SystemExit(
                        f"Validation failed: NBA season {sy} (current) has {nba_c} games "
                        f"(minimum {NBA_MIN_GAMES_PER_SEASON}). Check data/nba/raw/nba_schedule*.json."
                    )
            if league in ("ncaam", "all"):
                if ncaam_c == 0 and ncaam_games:
                    raise SystemExit(
                        f"Validation failed: NCAAM season {sy} (current) has 0 games. "
                        "Crawl data/ncaam/raw/ncaam_schedule_raw_*.json for that season."
                    )
        else:
            # Backlog seasons (2023, 2024): warn only, do not exit
            if nba_c == 0:
                print(f"  [Backlog] NBA season {sy} has 0 games (skipped; will not fetch).")
            elif nba_c < NBA_MIN_GAMES_PER_SEASON:
                print(f"  [Backlog] NBA season {sy} has {nba_c} games (below {NBA_MIN_GAMES_PER_SEASON}); skipped.")
            if ncaam_c == 0 and ncaam_games:
                print(f"  [Backlog] NCAAM season {sy} has 0 games (skipped).")


# -----------------------------------------------------------------------------
# Task 2: Deep Audit (NBA master + NCAAM market folder)
# -----------------------------------------------------------------------------

def _load_nba_master_snapshots() -> list[dict]:
    if not MASTER_ODDS_PATH.exists():
        return []
    try:
        with open(MASTER_ODDS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _audit_nba(snapshots: list) -> tuple[set[str], set[str]]:
    """Returns (all_ids_in_master, empty_ids). empty_ids = in master but every occurrence is empty."""
    all_ids = set()
    non_empty_ids = set()
    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        for g in snap.get("data") or []:
            gid = (g.get("id") or "").strip()
            if not gid:
                continue
            all_ids.add(gid)
            if not is_game_empty(g):
                non_empty_ids.add(gid)
    need_fetch = all_ids - non_empty_ids
    return all_ids, need_fetch


def _load_ncaam_existing() -> tuple[list[dict], set[str], set[str]]:
    """Load all NCAAM raw JSONs; return (snapshots, all_event_ids, non_empty_event_ids)."""
    snapshots = []
    all_ids = set()
    non_empty_ids = set()
    paths = list(NCAAM_MARKET_RAW_DIR.glob("*.json")) if NCAAM_MARKET_RAW_DIR.exists() else []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                snap = json.load(f)
        except Exception:
            continue
        if not isinstance(snap, dict):
            continue
        snapshots.append(snap)
        for g in snap.get("data") or []:
            eid = (g.get("id") or "").strip()
            if not eid:
                continue
            all_ids.add(eid)
            if not is_game_empty(g):
                non_empty_ids.add(eid)
    return snapshots, all_ids, non_empty_ids


def _audit_ncaam(ncaam_games: list, all_ids: set, non_empty_ids: set) -> tuple[set[str], set[str]]:
    """Returns (missing_event_ids, empty_event_ids) that need fetch. Uses game_id from universe = ESPN id."""
    missing = set()
    empty = set()
    for g in ncaam_games:
        gid = (g.get("game_id") or "").strip()
        if not gid:
            continue
        if gid not in all_ids:
            missing.add(gid)
        elif gid not in non_empty_ids:
            empty.add(gid)
    return missing, empty


# -----------------------------------------------------------------------------
# API: events list + fetch event odds
# -----------------------------------------------------------------------------

def _fetch_events_list(sport_key: str) -> list:
    import requests
    url = f"{BASE_URL}/{sport_key}/events"
    params = {"apiKey": API_KEY}
    if sport_key == "basketball_ncaab":
        params["dateFormat"] = "iso"
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        out = r.json()
        return out if isinstance(out, list) else []
    except Exception:
        return []


def _fetch_event_odds(sport_key: str, event_id: str) -> dict | None:
    import requests
    url = f"{BASE_URL}/{sport_key}/events/{event_id}/odds"
    params = {
        "apiKey": API_KEY,
        "markets": MARKETS,
        "regions": REGIONS,
        "oddsFormat": ODDS_FORMAT,
    }
    if sport_key == "basketball_ncaab":
        params["dateFormat"] = "iso"
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _build_event_key_to_id_nba(events: list) -> dict[tuple[str, str, str], str]:
    key_to_id = {}
    for ev in events:
        eid = (ev.get("id") or "").strip()
        if not eid:
            continue
        ct = ev.get("commence_time") or ""
        dt = _normalize_date(ct[:10] if ct else "")
        home = _normalize_team(ev.get("home_team"))
        away = _normalize_team(ev.get("away_team"))
        if dt and (home or away):
            key_to_id[(dt, home, away)] = eid
    return key_to_id


def _build_event_key_to_id_ncaab(events: list) -> dict[tuple[str, str, str], str]:
    """Same as NBA: (date, home, away) -> API event id."""
    return _build_event_key_to_id_nba(events)


# -----------------------------------------------------------------------------
# Historical odds (v4/historical/sports/{sport}/odds)
# -----------------------------------------------------------------------------

# Minimum non-empty games per date to consider that date "covered" (skip fetch)
MIN_GAMES_PER_DATE_TO_SKIP = 5


def _date_from_commence_time(ct: str) -> str | None:
    """Return YYYY-MM-DD from commence_time string, or None."""
    if not ct:
        return None
    ct = (ct or "").strip()[:10]
    if len(ct) == 10 and ct[4] == "-" and ct[7] == "-":
        return ct
    if len(ct) == 8 and ct.isdigit():
        return f"{ct[:4]}-{ct[4:6]}-{ct[6:8]}"
    return None


def _dates_with_data_in_master() -> set[str]:
    """
    Token guard (NBA): Only skip a date if the master has at least MIN_GAMES_PER_DATE_TO_SKIP
    games with at least one active market (spread/total). Dates with 0 or few games are treated as Missing.
    """
    date_counts = {}
    if not MASTER_ODDS_PATH.exists():
        return set()
    try:
        with open(MASTER_ODDS_PATH, "r", encoding="utf-8") as f:
            snapshots = json.load(f)
    except Exception:
        return set()
    if not isinstance(snapshots, list):
        return set()
    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        for g in snap.get("data") or []:
            if is_game_empty(g):
                continue
            d = _date_from_commence_time(g.get("commence_time") or "")
            if d:
                date_counts[d] = date_counts.get(d, 0) + 1
    return {d for d, c in date_counts.items() if c >= MIN_GAMES_PER_DATE_TO_SKIP}


def _dates_with_data_in_master_ncaam() -> set[str]:
    """
    Token guard (NCAAM): Only skip a date if the NCAAM market raw folder has at least
    MIN_GAMES_PER_DATE_TO_SKIP games with at least one active market (spread/total) for that date.
    """
    date_counts = {}
    if not NCAAM_MARKET_RAW_DIR.exists():
        return set()
    for path in NCAAM_MARKET_RAW_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                snap = json.load(f)
        except Exception:
            continue
        if not isinstance(snap, dict):
            continue
        for g in snap.get("data") or []:
            if is_game_empty(g):
                continue
            d = _date_from_commence_time(g.get("commence_time") or "")
            if d:
                date_counts[d] = date_counts.get(d, 0) + 1
    return {d for d, c in date_counts.items() if c >= MIN_GAMES_PER_DATE_TO_SKIP}


def _fetch_historical_odds_for_date(sport_key: str, date_iso: str) -> dict | None:
    """
    Call v4/historical/sports/{sport}/odds for the given date (ISO8601, e.g. 2025-10-22T12:00:00Z).
    Returns the raw response dict (has 'data' array of events) or None on failure.
    """
    import requests
    url = f"{HISTORICAL_BASE_URL}/{sport_key}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
        "date": date_iso,
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def crawl_historical_gap(
    sport_key: str,
    start_date: str,
    end_date: str,
    skip_dates_with_data: bool = True,
    limit_games: int | None = None,
) -> tuple[list[dict], int, int]:
    """
    Fetch historical odds for each day from start_date to end_date (inclusive).
    start_date, end_date: YYYY-MM-DD.
    Returns (list of game dicts from all fetched snapshots, count_skipped_by_guard, count_fetched).
    Token guard: only skips a date if master has >= MIN_GAMES_PER_DATE_TO_SKIP non-empty games (force-heal empty dates).
    limit_games: if set, stop after collecting this many games (e.g. 1000 for sprints).
    """
    try:
        start = datetime.strptime(start_date.strip()[:10], "%Y-%m-%d")
        end = datetime.strptime(end_date.strip()[:10], "%Y-%m-%d")
    except ValueError:
        return [], 0, 0
    if start > end:
        start, end = end, start
    if skip_dates_with_data:
        dates_with_data = (
            _dates_with_data_in_master_ncaam()
            if sport_key == "basketball_ncaab"
            else _dates_with_data_in_master()
        )
    else:
        dates_with_data = set()
    all_games = []
    skipped = 0
    fetched = 0
    current = start
    while current <= end:
        if limit_games is not None and len(all_games) >= limit_games:
            break
        date_str = current.strftime("%Y-%m-%d")
        if date_str in dates_with_data:
            skipped += 1
            current += timedelta(days=1)
            continue
        date_iso = f"{date_str}T12:00:00Z"
        resp = _fetch_historical_odds_for_date(sport_key, date_iso)
        if resp and isinstance(resp.get("data"), list) and len(resp["data"]) > 0:
            all_games.extend(resp["data"])
            fetched += 1
            if limit_games is not None and len(all_games) >= limit_games:
                break
        current += timedelta(days=1)
        time.sleep(0.3)
    return all_games, skipped, fetched


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def _run_historical_nba(
    historical_date: str | None,
    historical_start: str | None,
    historical_end: str | None,
    limit_games: int | None = None,
) -> None:
    """Fetch NBA historical odds for a single date or a date range; write to temp_historical_odds.json."""
    MASTER_ODDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROJECT_ROOT.joinpath("data").mkdir(parents=True, exist_ok=True)
    sport_key = "basketball_nba"
    dates_covered = _dates_with_data_in_master()

    if historical_date:
        d = historical_date.strip()[:10]
        if d in dates_covered:
            print(f"Token guard: already have >= {MIN_GAMES_PER_DATE_TO_SKIP} games for {d}, skipping fetch.")
            return
        date_iso = f"{d}T12:00:00Z"
        resp = _fetch_historical_odds_for_date(sport_key, date_iso)
        if not resp or not isinstance(resp.get("data"), list):
            print(f"No data returned for {d}.")
            return
        all_games = resp["data"]
        print(f"Fetched {len(all_games)} games for {d}.")
    elif historical_start and historical_end:
        all_games, skipped, fetched = crawl_historical_gap(
            sport_key, historical_start, historical_end,
            skip_dates_with_data=True, limit_games=limit_games,
        )
        print(f"Historical gap {historical_start} to {historical_end}: skipped {skipped} dates (token guard), fetched {fetched} dates, {len(all_games)} total games.")
    else:
        return

    payload = {
        "captured_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "sport": sport_key,
        "source": "the_odds_api",
        "description": "fetch_missing_raw_historical",
        "data": all_games,
    }
    TEMP_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TEMP_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Saved {len(all_games)} games to {TEMP_OUTPUT_PATH}. Run tools/merge_and_heal.py next.")


def _run_historical_ncaam(
    historical_start: str,
    historical_end: str,
    limit_games: int | None = None,
) -> None:
    """Fetch NCAAM historical odds for date range; write to temp_ncaam_historical_odds.json. Token guard: skip only dates with >= 5 non-empty games."""
    PROJECT_ROOT.joinpath("data").mkdir(parents=True, exist_ok=True)
    NCAAM_MARKET_RAW_DIR.mkdir(parents=True, exist_ok=True)
    sport_key = "basketball_ncaab"

    all_games, skipped, fetched = crawl_historical_gap(
        sport_key, historical_start, historical_end,
        skip_dates_with_data=True, limit_games=limit_games,
    )
    print(f"NCAAM historical {historical_start} to {historical_end}: skipped {skipped} dates (token guard), fetched {fetched} dates, {len(all_games)} games.")

    payload = {
        "captured_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "sport": sport_key,
        "source": "the_odds_api",
        "description": "fetch_missing_raw_historical",
        "data": all_games,
    }
    TEMP_NCAAM_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TEMP_NCAAM_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Saved {len(all_games)} games to {TEMP_NCAAM_OUTPUT_PATH}. Run tools/merge_and_heal.py next.")


def main(
    limit: int | None = None,
    league: str = "all",
    historical_date: str | None = None,
    historical_start: str | None = None,
    historical_end: str | None = None,
) -> None:
    # Historical path: no live events list, use v4/historical/.../odds only
    if historical_date or (historical_start and historical_end):
        league_hist = (league or "nba").strip().lower()
        if league_hist == "ncaam":
            if not (historical_start and historical_end):
                raise ValueError("NCAAM historical requires --historical-start and --historical-end (no single-date mode).")
            _run_historical_ncaam(historical_start, historical_end, limit_games=limit)
        else:
            _run_historical_nba(historical_date, historical_start, historical_end, limit_games=limit)
        return

    league = (league or "all").strip().lower()
    if league not in ("nba", "ncaam", "all"):
        raise ValueError("--league must be nba, ncaam, or all")

    MASTER_ODDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROJECT_ROOT.joinpath("data").mkdir(parents=True, exist_ok=True)

    # ----- Task 1: Build true universe (aggregate all sources) -----
    nba_universe = _load_nba_universe_aggregated() if league in ("nba", "all") else []
    ncaam_universe = _load_ncaam_universe_aggregated() if league in ("ncaam", "all") else []

    print("Universe (aggregated):")
    print(f"  NBA:   {len(nba_universe)} games (from data/nba/raw/nba_schedule*.json)")
    print(f"  NCAAM: {len(ncaam_universe)} games (from data/ncaam/raw/ncaam_schedule_raw_*.json)")

    _print_validation_table(nba_universe, ncaam_universe)
    _validate_universe(nba_universe, ncaam_universe, league=league)

    # ----- Task 2: Deep audit -----
    nba_snapshots = _load_nba_master_snapshots() if league in ("nba", "all") else []
    nba_all, nba_need_fetch = set(), set()
    if nba_snapshots:
        nba_all, nba_need_fetch = _audit_nba(nba_snapshots)

    ncaam_all, ncaam_non_empty = set(), set()
    ncaam_missing, ncaam_empty = set(), set()
    if league in ("ncaam", "all"):
        if NCAAM_MARKET_RAW_DIR.exists():
            _, ncaam_all, ncaam_non_empty = _load_ncaam_existing()
        ncaam_missing, ncaam_empty = _audit_ncaam(ncaam_universe, ncaam_all, ncaam_non_empty)

    event_key_to_id = {}
    nba_to_fetch = []
    if league in ("nba", "all") and nba_universe:
        events_nba = _fetch_events_list("basketball_nba")
        event_key_to_id = _build_event_key_to_id_nba(events_nba)
        for g in nba_universe:
            dt = _normalize_date(g.get("game_date"))
            home = _normalize_team(g.get("home_team"))
            away = _normalize_team(g.get("away_team"))
            api_id = _lookup_nba_event_id(event_key_to_id, dt, home, away)
            if not api_id:
                continue
            if api_id not in nba_all or api_id in nba_need_fetch:
                nba_to_fetch.append((api_id, g))
        seen_nba = set()
        nba_to_fetch_deduped = []
        for eid, g in nba_to_fetch:
            if eid in seen_nba:
                continue
            seen_nba.add(eid)
            nba_to_fetch_deduped.append((eid, g))
        nba_to_fetch = nba_to_fetch_deduped

    ncaam_to_fetch = []
    if league in ("ncaam", "all"):
        ncaam_need_fetch_ids = ncaam_missing | ncaam_empty
        events_ncaab = _fetch_events_list("basketball_ncaab")
        ncaab_key_to_id = _build_event_key_to_id_ncaab(events_ncaab)
        ncaam_universe_by_gid = {str(g.get("game_id") or "").strip(): g for g in ncaam_universe if (g.get("game_id") or "").strip()}
        for gid in ncaam_need_fetch_ids:
            g = ncaam_universe_by_gid.get(gid)
            if not g:
                continue
            dt = _normalize_date(g.get("game_date"))
            home = _normalize_team(g.get("home_team"))
            away = _normalize_team(g.get("away_team"))
            api_id = ncaab_key_to_id.get((dt, home, away))
            if not api_id:
                continue
            ncaam_to_fetch.append((api_id, g))
        seen_ncaam = set()
        ncaam_to_fetch_deduped = []
        for eid, g in ncaam_to_fetch:
            if eid in seen_ncaam:
                continue
            seen_ncaam.add(eid)
            ncaam_to_fetch_deduped.append((eid, g))
        ncaam_to_fetch = ncaam_to_fetch_deduped

    # Market gap: Oct 2025 - Jan 2026 games in universe vs master (NBA only)
    if league in ("nba", "all") and nba_universe:
        nba_oct_jan = [
            g for g in nba_universe
            if g.get("game_date") and _normalize_date(g.get("game_date"))
            and "20251001" <= _normalize_date(g.get("game_date")) <= "20260131"
        ]
        nba_oct_jan_in_master = sum(
            1 for g in nba_oct_jan
            if _lookup_nba_event_id(event_key_to_id, _normalize_date(g.get("game_date")), _normalize_team(g.get("home_team")), _normalize_team(g.get("away_team"))) in nba_all
        )
        nba_oct_jan_missing = len(nba_oct_jan) - nba_oct_jan_in_master
    else:
        nba_oct_jan_missing = nba_oct_jan_in_master = 0
        nba_oct_jan = []

    print("Deep Audit:")
    if league in ("nba", "all"):
        print(f"  NBA:   Missing or Empty -> {len(nba_to_fetch)} events to fetch")
        if nba_oct_jan:
            print(f"  NBA Oct 2025 - Jan 2026: {len(nba_oct_jan)} in universe, {nba_oct_jan_in_master} in master, {nba_oct_jan_missing} missing (market gap)")
    if league in ("ncaam", "all"):
        print(f"  NCAAM: Missing={len(ncaam_missing)}, Empty={len(ncaam_empty)} -> {len(ncaam_to_fetch)} mappable to API (to fetch)")

    # ----- Task 3: Fetch NBA Missing/Empty, save to temp -----
    pulled = []
    if league in ("nba", "all") and nba_to_fetch:
        nba_batch = nba_to_fetch[:limit] if (league == "nba" and limit is not None) else nba_to_fetch
        if league == "nba" and limit is not None and len(nba_to_fetch) > limit:
            print(f"\nNBA: Applying --limit {limit}; fetching {len(nba_batch)} of {len(nba_to_fetch)}.")
        print(f"\nFetching {len(nba_batch)} NBA events...")
        for i, (eid, _) in enumerate(nba_batch):
            odds = _fetch_event_odds("basketball_nba", eid)
            if odds:
                pulled.append(odds)
            if (i + 1) % 10 == 0:
                print(f"  Fetched {i + 1}/{len(nba_batch)}")
            time.sleep(0.2)
    elif league in ("nba", "all"):
        print("No NBA games to fetch (Missing or Empty); writing empty temp file.")

    if league in ("nba", "all"):
        payload = {
            "captured_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "sport": "basketball_nba",
            "source": "the_odds_api",
            "description": "fetch_missing_raw",
            "data": pulled,
        }
        TEMP_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TEMP_OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"Saved {len(pulled)} games to {TEMP_OUTPUT_PATH}. Run tools/merge_and_heal.py next.")

    # ----- Task 3b: Fetch NCAAM Missing/Empty (optional limit), save to temp_ncaam -----
    if league in ("ncaam", "all") and ncaam_to_fetch:
        ncaam_batch = ncaam_to_fetch[:limit] if limit is not None else ncaam_to_fetch
        if limit is not None and len(ncaam_to_fetch) > limit:
            print(f"\nNCAAM: Applying --limit {limit}; fetching {len(ncaam_batch)} of {len(ncaam_to_fetch)}.")
        print(f"\nFetching {len(ncaam_batch)} NCAAM events...")
        ncaam_pulled = []
        for i, (eid, _) in enumerate(ncaam_batch):
            odds = _fetch_event_odds("basketball_ncaab", eid)
            if odds:
                ncaam_pulled.append(odds)
            if (i + 1) % 50 == 0 or (i + 1) == len(ncaam_batch):
                print(f"  NCAAM fetched {i + 1}/{len(ncaam_batch)}")
            time.sleep(0.2)
        ncaam_payload = {
            "captured_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "sport": "basketball_ncaab",
            "source": "the_odds_api",
            "description": "fetch_missing_raw",
            "data": ncaam_pulled,
        }
        TEMP_NCAAM_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TEMP_NCAAM_OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(ncaam_payload, f, indent=2)
        print(f"Saved {len(ncaam_pulled)} NCAAM games to {TEMP_NCAAM_OUTPUT_PATH}. Run tools/merge_and_heal.py to patch into data/ncaam/market/raw/.")
    elif league in ("ncaam", "all"):
        print("\nNo NCAAM games to fetch (all missing/empty are unmappable or none).")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch missing/empty odds for NBA and NCAAM.")
    p.add_argument("--limit", type=int, default=None, help="Max events to fetch (NBA when --league nba, NCAAM when --league ncaam/all).")
    p.add_argument("--league", choices=["nba", "ncaam", "all"], default="all", help="League to run: nba, ncaam, or all (default).")
    p.add_argument("--historical-date", type=str, default=None, metavar="YYYY-MM-DD", help="Fetch historical NBA odds for this single date (v4/historical/.../odds).")
    p.add_argument("--historical-start", type=str, default=None, metavar="YYYY-MM-DD", help="Start date for historical gap crawl (use with --historical-end).")
    p.add_argument("--historical-end", type=str, default=None, metavar="YYYY-MM-DD", help="End date for historical gap crawl (use with --historical-start).")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(
        limit=args.limit,
        league=args.league,
        historical_date=args.historical_date,
        historical_start=args.historical_start,
        historical_end=args.historical_end,
    )
