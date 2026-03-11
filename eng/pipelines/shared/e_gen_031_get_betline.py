"""
e_gen_031_get_betline.py

Unified market retrieval: fetch current betting lines from The Odds API for NBA or NCAAM.

- Checks existing data (NBA: data/external/odds_api_raw.json; NCAAM: market/raw) before
  making API calls. Token Guard: if we already have odds for a game_id and commence_time
  has passed, we do NOT call the API for that game.
- Optional --skip-if-recent N: skip fetch if we have a snapshot from the last N minutes.
- Optional --backfill-ncaam: use paid key to fetch historical odds for canonical games
  that are missing lines (writes same format as normal run for 032/041 compatibility).

Usage:
  python e_gen_031_get_betline.py --league nba
  python e_gen_031_get_betline.py --league ncaam
  python e_gen_031_get_betline.py --league ncaam --skip-if-recent 60
  python e_gen_031_get_betline.py --league ncaam --backfill-ncaam

Environment: ODDS_API_KEY required.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import requests
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv

from utils.run_log import set_silent, log_info

# =====================================================
# LOAD ENVIRONMENT
# =====================================================

PROJECT_ROOT = _PROJECT_ROOT
env_path = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=env_path)

BASE_URL = "https://api.the-odds-api.com/v4/sports"
MARKETS = "spreads,totals,h2h"
REGIONS = "us"
ODDS_FORMAT = "american"

API_KEY = os.getenv("ODDS_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing required environment variable: ODDS_API_KEY")


# =====================================================
# EXISTING DATA + TOKEN GUARD
# =====================================================

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


def load_existing_nba(project_root: Path) -> tuple[list, set[tuple[str, str]]]:
    """
    Load existing NBA odds from data/external/odds_api_raw.json.
    Returns (list of snapshots, set of (game_id, commence_time) for games we have with commence in the past).
    """
    path = project_root / "data" / "external" / "odds_api_raw.json"
    if not path.exists():
        return [], set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return [], set()
    if not isinstance(data, list):
        return [], set()
    now = _now_utc()
    past_set = set()
    for snap in data:
        games = snap.get("data") if isinstance(snap, dict) else []
        if not isinstance(games, list):
            continue
        for g in games:
            gid = (g.get("id") or "").strip() if isinstance(g, dict) else ""
            ct = g.get("commence_time")
            if not gid:
                continue
            ct_dt = _parse_commence(ct)
            if ct_dt is not None and ct_dt < now:
                past_set.add((gid, str(ct) if ct else ""))
    return data, past_set


def load_existing_ncaam(project_root: Path) -> tuple[list[dict], set[tuple[str, str]]]:
    """
    Load existing NCAAM odds from latest + all timestamped raw JSONs in market/raw.
    Returns (list of snapshot dicts, set of (game_id, commence_time) for past games we have).
    """
    from configs.leagues.league_ncaam import ODDS_RAW_LATEST_PATH, MARKET_RAW_DIR

    snapshots = []
    past_set = set()
    now = _now_utc()

    paths_to_try = [ODDS_RAW_LATEST_PATH]
    if MARKET_RAW_DIR.exists():
        paths_to_try.extend(sorted(MARKET_RAW_DIR.glob("ncaam_odds_raw_*.json")))

    for path in paths_to_try:
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                snap = json.load(f)
        except json.JSONDecodeError:
            continue
        if not isinstance(snap, dict):
            continue
        snapshots.append(snap)
        games = snap.get("data") or []
        if not isinstance(games, list):
            continue
        for g in games:
            gid = (g.get("id") or "").strip() if isinstance(g, dict) else ""
            ct = g.get("commence_time")
            if not gid:
                continue
            ct_dt = _parse_commence(ct)
            if ct_dt is not None and ct_dt < now:
                past_set.add((gid, str(ct) if ct else ""))

    return snapshots, past_set


def token_guard_skip(game_id: str, commence_time: str | None, past_set: set[tuple[str, str]]) -> bool:
    """
    Return True if we should NOT call the API for this game (we already have it and it's finished).
    """
    if not (game_id or "").strip():
        return False
    key = (game_id.strip(), str(commence_time) if commence_time else "")
    return key in past_set


def _print_first_last_odds_dates(league_label: str, games: list) -> None:
    """Log the date of the first and last odds records (by commence_time) for the given league."""
    if not games:
        log_info(f"[{league_label}] Odds records: 0 (no first/last dates)")
        return
    with_commence = [(g, _parse_commence(g.get("commence_time"))) for g in games if isinstance(g, dict)]
    with_commence = [(g, dt) for g, dt in with_commence if dt is not None]
    if not with_commence:
        log_info(f"[{league_label}] Odds records: {len(games)} (no commence_time to order)")
        return
    with_commence.sort(key=lambda x: x[1])
    first_g, first_dt = with_commence[0]
    last_g, last_dt = with_commence[-1]
    first_str = first_dt.strftime("%Y-%m-%d %H:%M UTC") if first_dt else str(first_g.get("commence_time", ""))
    last_str = last_dt.strftime("%Y-%m-%d %H:%M UTC") if last_dt else str(last_g.get("commence_time", ""))
    log_info(f"[{league_label}] First odds record: {first_str}  (id={first_g.get('id', '')})")
    log_info(f"[{league_label}] Last odds record:  {last_str}  (id={last_g.get('id', '')})")


# =====================================================
# FETCH (shared)
# =====================================================

def fetch_current_odds(sport_key: str) -> list:
    url = f"{BASE_URL}/{sport_key}/odds"
    params = {
        "apiKey": API_KEY,
        "markets": MARKETS,
        "regions": REGIONS,
        "oddsFormat": ODDS_FORMAT,
    }
    if sport_key == "basketball_ncaab":
        params["dateFormat"] = "iso"
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_event_odds(sport_key: str, event_id: str) -> dict | None:
    """Fetch odds for a single event (for backfill). Uses 1 request per event."""
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
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def fetch_events_list(sport_key: str) -> list:
    """Get list of events (ids, commence_time, home_team, away_team) for matching."""
    url = f"{BASE_URL}/{sport_key}/events"
    params = {"apiKey": API_KEY}
    if sport_key == "basketball_ncaab":
        params["dateFormat"] = "iso"
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json() if isinstance(response.json(), list) else []
    except Exception:
        return []


# =====================================================
# NBA: append raw JSON + flatten CSV
# =====================================================

NBA_JSON_OUT = Path("data/external/odds_api_raw.json")
NBA_CSV_OUT = Path("data/external/odds_api_current.csv")


def _nba_flatten_odds(raw_data: list, captured_at: str | None = None) -> list:
    captured_at = captured_at or datetime.now(timezone.utc).isoformat()
    rows = []
    for game in raw_data:
        game_id = game.get("id")
        game_date = game.get("commence_time")
        home_team = game.get("home_team")
        away_team = game.get("away_team")
        for bookmaker in game.get("bookmakers", []):
            book_key = bookmaker.get("key")
            book_title = bookmaker.get("title")
            for market in bookmaker.get("markets", []):
                market_key = market.get("key")
                for outcome in market.get("outcomes", []):
                    rows.append({
                        "game_id": game_id,
                        "game_date": game_date,
                        "home_team": home_team,
                        "away_team": away_team,
                        "bookmaker": book_title,
                        "bookmaker_key": book_key,
                        "market": market_key,
                        "outcome_name": outcome.get("name"),
                        "price": outcome.get("price"),
                        "point": outcome.get("point"),
                        "source": "the_odds_api",
                        "captured_at_utc": captured_at,
                    })
    return rows


def run_nba(skip_if_recent_minutes: int | None = None) -> None:
    sport_key = "basketball_nba"
    json_path = PROJECT_ROOT / NBA_JSON_OUT
    csv_path = PROJECT_ROOT / NBA_CSV_OUT
    json_path.parent.mkdir(parents=True, exist_ok=True)

    existing_snapshots, past_set = load_existing_nba(PROJECT_ROOT)

    if skip_if_recent_minutes is not None and skip_if_recent_minutes > 0 and existing_snapshots:
        latest = existing_snapshots[-1]
        cap = latest.get("captured_at_utc")
        if cap:
            try:
                cap_dt = _parse_commence(cap) or datetime.min.replace(tzinfo=timezone.utc)
                if ( _now_utc() - cap_dt ).total_seconds() < skip_if_recent_minutes * 60:
                    raw_from_existing = latest.get("data") or []
                    rows = _nba_flatten_odds(raw_from_existing, cap)
                    if rows:
                        with open(csv_path, "w", newline="", encoding="utf-8") as f:
                            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                            writer.writeheader()
                            writer.writerows(rows)
                    log_info(f"Skipped API call (data from last {skip_if_recent_minutes} min). Using existing.")
                    log_info(f"Games in snapshot: {len(raw_from_existing)}")
                    _print_first_last_odds_dates("NBA", raw_from_existing)
                    log_info(f"CSV -> {csv_path}")
                    return
            except Exception:
                pass

    log_info("Fetching NBA odds from The Odds API...")
    raw_data = fetch_current_odds(sport_key)
    captured_at = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "captured_at_utc": captured_at,
        "sport": sport_key,
        "source": "the_odds_api",
        "data": raw_data,
    }
    existing_snapshots.append(snapshot)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(existing_snapshots, f, indent=2)

    rows = _nba_flatten_odds(raw_data, captured_at)
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    log_info(f"Retrieved {len(raw_data)} games")
    _print_first_last_odds_dates("NBA", raw_data)
    log_info(f"JSON -> {json_path}")
    log_info(f"CSV  -> {csv_path}")
    log_info(f"Rows -> {len(rows)}")


# =====================================================
# NCAAM: latest + timestamped raw JSON
# =====================================================

def run_ncaam(skip_if_recent_minutes: int | None = None) -> None:
    from configs.leagues.league_ncaam import (
        ODDS_RAW_LATEST_PATH,
        ensure_ncaam_dirs,
        timestamped_odds_raw_path,
    )
    sport_key = "basketball_ncaab"
    ensure_ncaam_dirs()

    existing_snapshots, past_set = load_existing_ncaam(PROJECT_ROOT)

    if skip_if_recent_minutes is not None and skip_if_recent_minutes > 0 and existing_snapshots:
        latest = existing_snapshots[-1]
        cap = latest.get("captured_at_utc")
        if cap:
            try:
                cap_dt = _parse_commence(cap) or datetime.min.replace(tzinfo=timezone.utc)
                if ( _now_utc() - cap_dt ).total_seconds() < skip_if_recent_minutes * 60:
                    raw_from_existing = latest.get("data") or []
                    log_info(f"Skipped API call (data from last {skip_if_recent_minutes} min). Using existing.")
                    _print_first_last_odds_dates("NCAAM", raw_from_existing)
                    log_info(f"Latest -> {ODDS_RAW_LATEST_PATH}")
                    return
            except Exception:
                pass

    log_info("Fetching NCAAM odds from The Odds API...")
    raw_data = fetch_current_odds(sport_key)
    captured_at = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "captured_at_utc": captured_at,
        "sport": sport_key,
        "source": "the_odds_api",
        "data": raw_data,
    }

    ts_label = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_path = timestamped_odds_raw_path(ts_label)

    ODDS_RAW_LATEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ODDS_RAW_LATEST_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    ts_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ts_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)

    log_info(f"Retrieved {len(raw_data)} games")
    _print_first_last_odds_dates("NCAAM", raw_data)
    log_info(f"Latest JSON -> {ODDS_RAW_LATEST_PATH}")
    log_info(f"Timestamped  -> {ts_path}")


# =====================================================
# NCAAM HISTORICAL BACKFILL
# =====================================================

def _normalize_team(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s).strip()).upper()


def _normalize_date(d: str) -> str:
    if not d:
        return ""
    d = str(d).strip()[:10]
    return d.replace("-", "") if len(d) == 10 else ""


def run_backfill_ncaam() -> None:
    """
    Fetch odds for NCAAM canonical games that are missing lines.
    Uses event list to match by date + home/away, then fetches per-event odds (token guard applied).
    Output format is same as normal run (latest + timestamped raw) so 032/041 stay compatible.
    """
    from configs.leagues.league_ncaam import (
        CANONICAL_GAMES_PATH,
        ODDS_RAW_LATEST_PATH,
        ensure_ncaam_dirs,
        timestamped_odds_raw_path,
    )
    sport_key = "basketball_ncaab"
    ensure_ncaam_dirs()

    if not CANONICAL_GAMES_PATH.exists():
        raise FileNotFoundError(f"Canonical games not found: {CANONICAL_GAMES_PATH}")

    with open(CANONICAL_GAMES_PATH, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        canonical = list(reader)

    existing_snapshots, past_set = load_existing_ncaam(PROJECT_ROOT)
    have_event_ids = set()
    for snap in existing_snapshots:
        for g in (snap.get("data") or []):
            eid = (g.get("id") or "").strip()
            if eid:
                have_event_ids.add(eid)

    events = fetch_events_list(sport_key)
    # Build key -> event_id: (norm_date, norm_home, norm_away) -> event_id
    event_key_to_id = {}
    for ev in events:
        eid = (ev.get("id") or "").strip()
        if not eid:
            continue
        ct = ev.get("commence_time") or ""
        dt = _normalize_date(ct[:10] if ct else "")
        home = _normalize_team(ev.get("home_team"))
        away = _normalize_team(ev.get("away_team"))
        if dt and (home or away):
            event_key_to_id[(dt, home, away)] = eid

    missing = []
    for row in canonical:
        gdate = _normalize_date(row.get("game_date"))
        home = _normalize_team(row.get("home_team_display") or row.get("home_team") or "")
        away = _normalize_team(row.get("away_team_display") or row.get("away_team") or "")
        key = (gdate, home, away)
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
        if token_guard_skip(eid, commence, past_set):
            continue
        missing.append((eid, commence, row.get("canonical_game_id")))

    if not missing:
        log_info("No canonical games missing odds (or all skipped by token guard).")
        return

    log_info(f"Backfilling odds for {len(missing)} NCAAM games (token guard applied)...")
    backfill_games = []
    for event_id, commence_time, cgid in missing:
        odds = fetch_event_odds(sport_key, event_id)
        if not odds:
            continue
        backfill_games.append(odds)
        have_event_ids.add(event_id)
        if commence_time:
            past_set.add((event_id, str(commence_time)))

    if not backfill_games:
        log_info("No odds returned from API for missing games.")
        return

    # Merge backfilled events into existing so latest remains full (032/041 compatible)
    merged_data = list(backfill_games)
    for snap in existing_snapshots:
        for g in snap.get("data") or []:
            if g.get("id") and g.get("id") not in {x.get("id") for x in merged_data}:
                merged_data.append(g)

    captured_at = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "captured_at_utc": captured_at,
        "sport": sport_key,
        "source": "the_odds_api",
        "data": merged_data,
    }
    ODDS_RAW_LATEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts_label = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_path = timestamped_odds_raw_path(ts_label)
    with open(ODDS_RAW_LATEST_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    with open(ts_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    _print_first_last_odds_dates("NCAAM (backfill)", merged_data)
    log_info(f"Backfill: added {len(backfill_games)} events; latest now has {len(merged_data)} total. Wrote {ts_path}")


# =====================================================
# ENTRYPOINT
# =====================================================

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Fetch betting lines from The Odds API")
    parser.add_argument("--league", required=True, choices=["nba", "ncaam"])
    parser.add_argument(
        "--skip-if-recent",
        type=int,
        default=None,
        metavar="MINUTES",
        help="Skip API call if we already have a snapshot from the last N minutes",
    )
    parser.add_argument(
        "--backfill-ncaam",
        action="store_true",
        help="Fetch historical odds for NCAAM canonical games missing lines (uses paid key)",
    )
    parser.add_argument("--silent", action="store_true", help="Only print critical errors")
    args = parser.parse_args()
    set_silent(args.silent)

    if args.backfill_ncaam:
        if args.league != "ncaam":
            raise SystemExit("--backfill-ncaam requires --league ncaam")
        run_backfill_ncaam()
        return

    if args.league == "nba":
        run_nba(skip_if_recent_minutes=args.skip_if_recent)
    else:
        run_ncaam(skip_if_recent_minutes=args.skip_if_recent)


if __name__ == "__main__":
    main()
