"""
tools/sync_historical_odds.py

Historical odds backfill for 2023-24, 2024-25, and 2025-26 seasons (NBA + NCAAM).

Step 1 (Universe): Filter raw schedule files for games with season_type or season_year
  matching these three cycles.
Step 2 (Audit): Use Token Guard to find games in those seasons that are missing from
  data/external/odds_api_raw.json (NBA) or data/ncaam/market/raw/ (NCAAM).
Step 3 (Historical Fetch): Fetch missing events via paid API and append to existing
  JSON ledgers (no overwrite).

Usage:
  python tools/sync_historical_odds.py --league nba
  python tools/sync_historical_odds.py --league ncaam
  python tools/sync_historical_odds.py --league both

Requires: ODDS_API_KEY in environment (paid key for historical event-odds calls).
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Project root: tools/ -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# Target seasons: 2023-24, 2024-25, 2025-26 (season start year)
TARGET_SEASON_YEARS = (2023, 2024, 2025)

BASE_URL = "https://api.the-odds-api.com/v4/sports"
MARKETS = "spreads,totals,h2h"
REGIONS = "us"
ODDS_FORMAT = "american"

API_KEY = os.getenv("ODDS_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing ODDS_API_KEY. Set in .env or environment.")


# -----------------------------------------------------------------------------
# Helpers: parse commence, token guard, fetch
# -----------------------------------------------------------------------------

def _parse_commence(commence_time: str | None) -> datetime | None:
    if not commence_time:
        return None
    try:
        s = (commence_time or "").replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_team(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s).strip()).upper()


def _normalize_date(d: str) -> str:
    if not d:
        return ""
    d = str(d).strip()[:10]
    return d.replace("-", "") if len(d) == 10 else ""


def _derive_season_year_from_game_date(game_date: str) -> int | None:
    """Derive season start year from game_date (YYYY-MM-DD). NBA/NCAAM: Oct/Nov start."""
    if not game_date or len(str(game_date).strip()) < 7:
        return None
    try:
        s = str(game_date).strip()[:10]
        y = int(s[:4])
        m = int(s[5:7]) if len(s) >= 7 else 1
        # Season 2024-25 starts in late 2024; games in Jan 2025 are still 2024-25.
        if m >= 8:  # Aug onward -> current calendar year is season start
            return y
        return y - 1  # Jan–Jul -> previous year is season start
    except Exception:
        return None


def _in_target_seasons(season_year, season_type, game_date: str) -> bool:
    """True if game belongs to 2023-24, 2024-25, or 2025-26."""
    sy = None
    if season_year is not None and str(season_year).strip() != "":
        try:
            sy = int(season_year)
        except Exception:
            pass
    if sy is None and game_date:
        sy = _derive_season_year_from_game_date(game_date)
    if sy is None:
        return False
    return sy in TARGET_SEASON_YEARS


# -----------------------------------------------------------------------------
# Step 1: Universe (filter raw schedules by target seasons)
# -----------------------------------------------------------------------------

def _load_nba_universe() -> list[dict]:
    """Load NBA games in target seasons. Prefer joined (has team names); else raw + team map."""
    from utils.io_helpers import get_schedule_joined_path, get_schedule_raw_path, get_team_map_path

    joined_path = get_schedule_joined_path("nba")
    raw_path = get_schedule_raw_path("nba")
    out = []

    if joined_path.exists():
        with open(joined_path, "r", encoding="utf-8") as f:
            rows = json.load(f)
        for g in rows:
            sy = g.get("season_year")
            gdate = (g.get("game_date") or "")[:10] if g.get("game_date") else ""
            if not _in_target_seasons(sy, None, gdate):
                continue
            out.append({
                "game_id": str(g.get("game_id") or "").strip(),
                "game_date": gdate or (str(g.get("game_date") or "")[:10]),
                "home_team": (g.get("home_team") or "").strip(),
                "away_team": (g.get("away_team") or "").strip(),
            })
        return [x for x in out if x["game_id"] and (x["home_team"] or x["away_team"])]

    if raw_path.exists():
        with open(raw_path, "r", encoding="utf-8") as f:
            rows = json.load(f)
        team_map_path = get_team_map_path("nba")
        team_by_id = {}
        if team_map_path.exists():
            with open(team_map_path, "r", encoding="utf-8") as f:
                tm = json.load(f)
            for t in tm if isinstance(tm, list) else [tm]:
                tid = t.get("team_id") or t.get("id")
                if tid is not None:
                    team_by_id[str(tid)] = (t.get("team_name") or t.get("full_name") or "").strip()
        for g in rows:
            sy = g.get("season_year")
            gdate = (g.get("game_date") or "")[:10] if g.get("game_date") else ""
            if not _in_target_seasons(sy, None, gdate):
                continue
            hid = str(g.get("home_team_id") or "")
            aid = str(g.get("away_team_id") or "")
            out.append({
                "game_id": str(g.get("game_id") or "").strip(),
                "game_date": gdate or (str(g.get("game_date") or "")[:10]),
                "home_team": team_by_id.get(hid, ""),
                "away_team": team_by_id.get(aid, ""),
            })
        return [x for x in out if x["game_id"]]

    return out


def _load_ncaam_universe() -> list[dict]:
    """Load NCAAM games in target seasons from raw schedule files (normalized list + optional date payloads)."""
    from configs.leagues.league_ncaam import RAW_DIR

    out = []
    seen = set()

    # Primary: normalized flat schedule (001 output)
    try:
        raw_path = PROJECT_ROOT / "data" / "ncaam" / "raw" / "ncaam_schedule_raw.json"
        if not raw_path.exists():
            raw_path = RAW_DIR / "ncaam_schedule_raw.json"
        if raw_path.exists():
            with open(raw_path, "r", encoding="utf-8") as f:
                rows = json.load(f)
            if isinstance(rows, list):
                for ev in rows:
                    if not isinstance(ev, dict):
                        continue
                    gid = str(ev.get("game_id") or ev.get("id") or "").strip()
                    if not gid or gid in seen:
                        continue
                    sy = ev.get("season_year")
                    st = ev.get("season_type")
                    gdate = (ev.get("game_date") or ev.get("date") or "")[:10]
                    if not _in_target_seasons(sy, st, gdate):
                        continue
                    seen.add(gid)
                    home = (ev.get("home_team_raw") or ev.get("home_team") or "").strip()
                    away = (ev.get("away_team_raw") or ev.get("away_team") or "").strip()
                    out.append({"game_id": gid, "game_date": gdate, "home_team": home, "away_team": away})
    except Exception:
        pass

    # Optional: date-stamped raw payloads (payload.events + leagues[0].season.year)
    for path in sorted(RAW_DIR.glob("ncaam_schedule_raw_*.json")):
        if path.name in ("ncaam_schedule_raw.json", "ncaam_schedule_raw_latest.json"):
            continue
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        leagues = data.get("leagues") or []
        season_year = None
        if leagues and isinstance(leagues[0], dict):
            s = (leagues[0].get("season") or {})
            if isinstance(s, dict):
                season_year = s.get("year")
        events = data.get("events") or []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            eid = str(ev.get("id") or ev.get("game_id") or "").strip()
            if not eid or eid in seen:
                continue
            gdate = (ev.get("date") or ev.get("game_date") or "")[:10]
            sy = season_year or ev.get("season_year")
            st = ev.get("season_type")
            if not _in_target_seasons(sy, st, gdate):
                continue
            seen.add(eid)
            home = away = ""
            for comp in (ev.get("competitions") or [])[:1]:
                for c in (comp.get("competitors") or []):
                    ha = str(c.get("homeAway") or "").lower()
                    name = (c.get("team") or {}).get("displayName") or (c.get("team") or {}).get("name") or ""
                    if ha == "home":
                        home = name.strip()
                    elif ha == "away":
                        away = name.strip()
            out.append({"game_id": eid, "game_date": gdate, "home_team": home, "away_team": away})
    return out


# -----------------------------------------------------------------------------
# Step 2: Audit (existing odds + token guard)
# -----------------------------------------------------------------------------

def _load_existing_nba(project_root: Path) -> tuple[list, set[str], set[tuple[str, str]]]:
    """Return (snapshots, have_event_ids, past_set for token guard)."""
    path = project_root / "data" / "external" / "odds_api_raw.json"
    snapshots = []
    have_event_ids = set()
    past_set = set()
    now = _now_utc()
    if not path.exists():
        return [], set(), set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            snapshots = json.load(f)
    except Exception:
        return [], set(), set()
    if not isinstance(snapshots, list):
        return [], set(), set()
    for snap in snapshots:
        for g in (snap.get("data") or []) if isinstance(snap, dict) else []:
            eid = (g.get("id") or "").strip()
            if eid:
                have_event_ids.add(eid)
            ct = g.get("commence_time")
            ct_dt = _parse_commence(ct)
            if ct_dt is not None and ct_dt < now:
                past_set.add((eid, str(ct) if ct else ""))
    return snapshots, have_event_ids, past_set


def _load_existing_ncaam(project_root: Path) -> tuple[list[dict], set[str], set[tuple[str, str]]]:
    """Return (snapshots, have_event_ids, past_set)."""
    from configs.leagues.league_ncaam import ODDS_RAW_LATEST_PATH, MARKET_RAW_DIR

    snapshots = []
    have_event_ids = set()
    past_set = set()
    now = _now_utc()
    paths = [ODDS_RAW_LATEST_PATH]
    if MARKET_RAW_DIR.exists():
        paths += sorted(MARKET_RAW_DIR.glob("ncaam_odds_raw_*.json"))
    for path in paths:
        if not path.exists():
            continue
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
            if eid:
                have_event_ids.add(eid)
            ct = g.get("commence_time")
            ct_dt = _parse_commence(ct)
            if ct_dt is not None and ct_dt < now:
                past_set.add((eid, str(ct) if ct else ""))
    return snapshots, have_event_ids, past_set


def _token_guard_skip(game_id: str, commence_time: str | None, past_set: set[tuple[str, str]]) -> bool:
    if not (game_id or "").strip():
        return False
    return (game_id.strip(), str(commence_time) if commence_time else "") in past_set


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


def _fetch_event_odds(sport_key: str, event_id: str):
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


# -----------------------------------------------------------------------------
# Run: NBA
# -----------------------------------------------------------------------------

def _build_event_key_to_id_nba(events: list) -> dict[tuple[str, str, str], str]:
    """(norm_date, norm_home, norm_away) -> event_id."""
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


def run_nba() -> None:
    sport_key = "basketball_nba"
    json_path = PROJECT_ROOT / "data" / "external" / "odds_api_raw.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)

    universe = _load_nba_universe()
    print(f"[NBA] Universe (target seasons {TARGET_SEASON_YEARS}): {len(universe)} games")

    snapshots, have_event_ids, past_set = _load_existing_nba(PROJECT_ROOT)
    print(f"[NBA] Existing snapshots: {len(snapshots)}; events already have odds: {len(have_event_ids)}")

    events = _fetch_events_list(sport_key)
    event_key_to_id = _build_event_key_to_id_nba(events)

    missing = []
    for g in universe:
        dt = _normalize_date(g.get("game_date"))
        home = _normalize_team(g.get("home_team"))
        away = _normalize_team(g.get("away_team"))
        key = (dt, home, away)
        eid = event_key_to_id.get(key)
        if not eid:
            continue
        if eid in have_event_ids:
            continue
        commence = None
        for ev in events:
            if (ev.get("id") or "").strip() == eid:
                commence = ev.get("commence_time")
                break
        if _token_guard_skip(eid, commence, past_set):
            continue
        missing.append((eid, commence, g))

    if not missing:
        print("[NBA] No games missing odds (or all skipped by token guard).")
        return

    print(f"[NBA] Fetching odds for {len(missing)} missing events (append to ledger)...")
    import time
    new_games = []
    for i, (eid, commence, g) in enumerate(missing):
        odds = _fetch_event_odds(sport_key, eid)
        if odds:
            new_games.append(odds)
            have_event_ids.add(eid)
            if commence:
                past_set.add((eid, str(commence)))
        if (i + 1) % 10 == 0:
            print(f"  Fetched {i + 1}/{len(missing)}")
        time.sleep(0.2)

    if not new_games:
        print("[NBA] No odds returned from API.")
        return

    # Append one new snapshot to existing ledger (do not overwrite)
    captured_at = datetime.now(timezone.utc).isoformat()
    new_snapshot = {
        "captured_at_utc": captured_at,
        "sport": sport_key,
        "source": "the_odds_api",
        "description": "historical_backfill",
        "data": new_games,
    }
    snapshots.append(new_snapshot)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(snapshots, f, indent=2)
    print(f"[NBA] Appended 1 snapshot ({len(new_games)} games) to {json_path}")


# -----------------------------------------------------------------------------
# Run: NCAAM
# -----------------------------------------------------------------------------

def _build_event_key_to_id_ncaam(events: list) -> dict[tuple[str, str, str], str]:
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


def run_ncaam() -> None:
    from configs.leagues.league_ncaam import (
        ODDS_RAW_LATEST_PATH,
        MARKET_RAW_DIR,
        ensure_ncaam_dirs,
        timestamped_odds_raw_path,
    )
    sport_key = "basketball_ncaab"
    ensure_ncaam_dirs()

    universe = _load_ncaam_universe()
    print(f"[NCAAM] Universe (target seasons {TARGET_SEASON_YEARS}): {len(universe)} games")

    snapshots, have_event_ids, past_set = _load_existing_ncaam(PROJECT_ROOT)
    print(f"[NCAAM] Existing raw files: {len(snapshots)}; events already have odds: {len(have_event_ids)}")

    events = _fetch_events_list(sport_key)
    event_key_to_id = _build_event_key_to_id_ncaam(events)

    missing = []
    for g in universe:
        dt = _normalize_date(g.get("game_date"))
        home = _normalize_team(g.get("home_team"))
        away = _normalize_team(g.get("away_team"))
        key = (dt, home, away)
        eid = event_key_to_id.get(key)
        if not eid:
            continue
        if eid in have_event_ids:
            continue
        commence = None
        for ev in events:
            if (ev.get("id") or "").strip() == eid:
                commence = ev.get("commence_time")
                break
        if _token_guard_skip(eid, commence, past_set):
            continue
        missing.append((eid, commence, g))

    if not missing:
        print("[NCAAM] No games missing odds (or all skipped by token guard).")
        return

    print(f"[NCAAM] Fetching odds for {len(missing)} missing events (append to ledger)...")
    import time
    new_games = []
    for i, (eid, commence, g) in enumerate(missing):
        odds = _fetch_event_odds(sport_key, eid)
        if odds:
            new_games.append(odds)
            have_event_ids.add(eid)
            if commence:
                past_set.add((eid, str(commence)))
        if (i + 1) % 10 == 0:
            print(f"  Fetched {i + 1}/{len(missing)}")
        time.sleep(0.2)

    if not new_games:
        print("[NCAAM] No odds returned from API.")
        return

    # Merge new into existing so latest remains full; write new timestamped file (append ledger)
    merged_data = list(new_games)
    for snap in snapshots:
        for g in snap.get("data") or []:
            if g.get("id") and g.get("id") not in {x.get("id") for x in merged_data}:
                merged_data.append(g)
    captured_at = datetime.now(timezone.utc).isoformat()
    ts_label = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_path = timestamped_odds_raw_path(ts_label)
    snapshot = {
        "captured_at_utc": captured_at,
        "sport": sport_key,
        "source": "the_odds_api",
        "description": "historical_backfill",
        "data": merged_data,
    }
    ODDS_RAW_LATEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ODDS_RAW_LATEST_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    with open(ts_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    print(f"[NCAAM] Appended backfill; latest + {ts_path} ({len(new_games)} new, {len(merged_data)} total)")


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Historical odds backfill (2023-24, 2024-25, 2025-26)")
    parser.add_argument("--league", choices=["nba", "ncaam", "both"], default="both")
    args = parser.parse_args()

    if args.league in ("nba", "both"):
        run_nba()
    if args.league in ("ncaam", "both"):
        run_ncaam()


if __name__ == "__main__":
    main()
