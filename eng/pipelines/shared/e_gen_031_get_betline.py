"""
e_gen_031_get_betline.py

Unified market retrieval: fetch current betting lines from The Odds API.

- Checks existing data (NBA: data/external/odds_api_raw.json; NCAAM: data/ncaam/raw
  ncaam_odds_api_raw.json list + legacy data/ncaam/market/raw + timestamped raw) before API calls.
  Token Guard: if we already have odds for a game_id and commence_time
  has passed, we do NOT call the API for that game.
- Optional --skip-if-recent N: skip fetch if we have a snapshot from the last N minutes.
- Optional --backfill-ncaam: use paid key to fetch historical odds for canonical games
  that are missing lines (writes same format as normal run for 032/041 compatibility).

Usage:
  python e_gen_031_get_betline.py --league nba
  python e_gen_031_get_betline.py --league ncaam
  python e_gen_031_get_betline.py --league wnba
  python e_gen_031_get_betline.py --league nhl
  python e_gen_031_get_betline.py --league ncaam --skip-if-recent 60
  python e_gen_031_get_betline.py --league ncaam --backfill-ncaam
  python e_gen_031_get_betline.py --league ncaam --gap-fill-ncaam

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

from utils.io_helpers import (
    get_odds_raw_accum_path,
    get_odds_raw_latest_path,
    get_timestamped_odds_raw_path,
)
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
SPORT_KEY_BY_LEAGUE = {
    "nba": "basketball_nba",
    "ncaam": "basketball_ncaab",
    "wnba": "basketball_wnba",
    "nhl": "icehockey_nhl",
}

API_KEY = os.getenv("ODDS_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing required environment variable: ODDS_API_KEY")


def _redact_api_key(text: object) -> str:
    return re.sub(r"apiKey=[^&\s)]+", "apiKey=<REDACTED>", str(text))


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


def _load_ncaam_accum_from_disk() -> list[dict]:
    """JSON array of snapshot dicts (NBA-parity). Empty if missing or invalid."""
    from configs.leagues.league_ncaam import LEGACY_ODDS_RAW_ACCUM_PATH, ODDS_RAW_ACCUM_PATH

    def _read(path) -> list[dict]:
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [s for s in data if isinstance(s, dict)]
        except json.JSONDecodeError:
            pass
        return []

    primary = _read(ODDS_RAW_ACCUM_PATH)
    if primary:
        return primary
    return _read(LEGACY_ODDS_RAW_ACCUM_PATH)


def _load_accum_from_path(path: Path) -> list[dict]:
    """JSON array of snapshot dicts. Empty if missing or invalid."""
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [s for s in data if isinstance(s, dict)]
    except json.JSONDecodeError:
        pass
    return []


def _load_latest_snapshot(path: Path | None) -> dict | None:
    if path is None or not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def load_existing_ncaam(project_root: Path) -> tuple[list[dict], set[tuple[str, str]]]:
    """
    Returns (accum_snapshots_from_disk, past_set).

    accum_snapshots_from_disk: list from ncaam_odds_api_raw.json only (for append on next fetch).

    past_set: union across accum + legacy ncaam_odds_raw_*.json + ncaam_odds_latest.json
    for token-guard (games we already saw with commence in the past).
    """
    from configs.leagues.league_ncaam import glob_ncaam_odds_raw_json_files, ncaam_odds_latest_read_path

    past_set: set[tuple[str, str]] = set()
    now = _now_utc()

    def _ingest_past_from_snap(snap: dict) -> None:
        games = snap.get("data") or []
        if not isinstance(games, list):
            return
        for g in games:
            gid = (g.get("id") or "").strip() if isinstance(g, dict) else ""
            ct = g.get("commence_time") if isinstance(g, dict) else None
            if not gid:
                continue
            ct_dt = _parse_commence(ct)
            if ct_dt is not None and ct_dt < now:
                past_set.add((gid, str(ct) if ct else ""))

    accum_snapshots = _load_ncaam_accum_from_disk()
    for snap in accum_snapshots:
        _ingest_past_from_snap(snap)

    for path in glob_ncaam_odds_raw_json_files():
        try:
            with open(path, "r", encoding="utf-8") as f:
                snap = json.load(f)
            if isinstance(snap, dict):
                _ingest_past_from_snap(snap)
        except json.JSONDecodeError:
            continue

    latest_path = ncaam_odds_latest_read_path()
    if latest_path:
        try:
            with open(latest_path, "r", encoding="utf-8") as f:
                snap = json.load(f)
            if isinstance(snap, dict):
                _ingest_past_from_snap(snap)
        except json.JSONDecodeError:
            pass

    return accum_snapshots, past_set


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

def requests_get(url: str, **kwargs):
    try:
        import certifi
        kwargs.setdefault("verify", certifi.where())
    except Exception:
        pass

    try:
        return requests.get(url, **kwargs)
    except requests.exceptions.SSLError as exc:
        log_info(f"SSL verification failed for {url}; retrying odds fetch with verify=False: {_redact_api_key(exc)}")
        kwargs["verify"] = False
        return requests.get(url, **kwargs)


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
    response = requests_get(url, params=params, timeout=30)
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
        response = requests_get(url, params=params, timeout=30)
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
        response = requests_get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json() if isinstance(response.json(), list) else []
    except Exception:
        return []


def fetch_historical_odds(sport_key: str, date_iso: str) -> dict | None:
    """
    Fetch historical odds snapshot for one date (featured markets).
    GET /v4/historical/sports/{sport}/odds with date=YYYY-MM-DDTHH:MM:SSZ.
    Returns wrapper dict with timestamp, data (list of games), or None on failure.
    """
    url = f"https://api.the-odds-api.com/v4/historical/sports/{sport_key}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
        "date": date_iso,
    }
    if sport_key == "basketball_ncaab":
        params["dateFormat"] = "iso"
    try:
        response = requests_get(url, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


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
        ODDS_RAW_ACCUM_PATH,
        ODDS_RAW_LATEST_PATH,
        ensure_ncaam_dirs,
        ncaam_odds_latest_read_path,
        timestamped_odds_raw_path,
    )
    sport_key = "basketball_ncaab"
    ensure_ncaam_dirs()

    accum_on_disk, _ = load_existing_ncaam(PROJECT_ROOT)
    snapshots_for_recent = list(accum_on_disk)
    _latest_read = ncaam_odds_latest_read_path()
    if not snapshots_for_recent and _latest_read:
        try:
            with open(_latest_read, "r", encoding="utf-8") as f:
                legacy_latest = json.load(f)
            if isinstance(legacy_latest, dict):
                snapshots_for_recent = [legacy_latest]
        except json.JSONDecodeError:
            pass

    if skip_if_recent_minutes is not None and skip_if_recent_minutes > 0 and snapshots_for_recent:
        latest = snapshots_for_recent[-1]
        cap = latest.get("captured_at_utc")
        if cap:
            try:
                cap_dt = _parse_commence(cap) or datetime.min.replace(tzinfo=timezone.utc)
                if ( _now_utc() - cap_dt ).total_seconds() < skip_if_recent_minutes * 60:
                    raw_from_existing = latest.get("data") or []
                    log_info(f"Skipped API call (data from last {skip_if_recent_minutes} min). Using existing.")
                    _print_first_last_odds_dates("NCAAM", raw_from_existing)
                    log_info(f"Latest -> {ODDS_RAW_LATEST_PATH} (skip-if-recent satisfied)")
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

    accum_list = list(accum_on_disk)
    if not accum_list and _latest_read:
        try:
            with open(_latest_read, "r", encoding="utf-8") as f:
                seed = json.load(f)
            if isinstance(seed, dict) and isinstance(seed.get("data"), list):
                accum_list = [seed]
        except json.JSONDecodeError:
            pass
    accum_list.append(snapshot)

    ts_label = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_path = timestamped_odds_raw_path(ts_label)

    ODDS_RAW_LATEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    ODDS_RAW_ACCUM_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ODDS_RAW_ACCUM_PATH, "w", encoding="utf-8") as f:
        json.dump(accum_list, f, indent=2)
    with open(ODDS_RAW_LATEST_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    ts_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ts_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)

    log_info(f"Retrieved {len(raw_data)} games")
    _print_first_last_odds_dates("NCAAM", raw_data)
    log_info(f"Accum JSON  -> {ODDS_RAW_ACCUM_PATH} ({len(accum_list)} snapshots)")
    log_info(f"Latest JSON -> {ODDS_RAW_LATEST_PATH}")
    log_info(f"Timestamped  -> {ts_path}")


# =====================================================
# CONFIGURED LEAGUES: latest + timestamped raw JSON
# =====================================================

def run_configured_league(league: str, skip_if_recent_minutes: int | None = None) -> None:
    league = (league or "").strip().lower()
    if league not in ("wnba", "nhl"):
        raise ValueError(f"run_configured_league is only wired for WNBA/NHL in Phase 2A, got {league!r}")

    sport_key = SPORT_KEY_BY_LEAGUE[league]
    accum_path = get_odds_raw_accum_path(league)
    latest_path = get_odds_raw_latest_path(league)
    if latest_path is None:
        raise ValueError(f"No latest raw odds path configured for {league!r}")

    accum_on_disk = _load_accum_from_path(accum_path)
    latest_snapshot = _load_latest_snapshot(latest_path)
    snapshots_for_recent = list(accum_on_disk)
    if not snapshots_for_recent and latest_snapshot:
        snapshots_for_recent = [latest_snapshot]

    if skip_if_recent_minutes is not None and skip_if_recent_minutes > 0 and snapshots_for_recent:
        latest = snapshots_for_recent[-1]
        cap = latest.get("captured_at_utc")
        if cap:
            try:
                cap_dt = _parse_commence(cap) or datetime.min.replace(tzinfo=timezone.utc)
                if (_now_utc() - cap_dt).total_seconds() < skip_if_recent_minutes * 60:
                    raw_from_existing = latest.get("data") or []
                    log_info(f"Skipped API call (data from last {skip_if_recent_minutes} min). Using existing.")
                    _print_first_last_odds_dates(league.upper(), raw_from_existing)
                    log_info(f"Latest -> {latest_path} (skip-if-recent satisfied)")
                    return
            except Exception:
                pass

    log_info(f"Fetching {league.upper()} odds from The Odds API ({sport_key})...")
    raw_data = fetch_current_odds(sport_key)
    captured_at = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "captured_at_utc": captured_at,
        "sport": sport_key,
        "source": "the_odds_api",
        "data": raw_data,
    }

    accum_list = list(accum_on_disk)
    if not accum_list and latest_snapshot and isinstance(latest_snapshot.get("data"), list):
        accum_list = [latest_snapshot]
    accum_list.append(snapshot)

    ts_label = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_path = get_timestamped_odds_raw_path(league, ts_label)

    accum_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(accum_path, "w", encoding="utf-8") as f:
        json.dump(accum_list, f, indent=2)
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    if ts_path is not None:
        ts_path.parent.mkdir(parents=True, exist_ok=True)
        with open(ts_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)

    log_info(f"Retrieved {len(raw_data)} games")
    _print_first_last_odds_dates(league.upper(), raw_data)
    log_info(f"Accum JSON  -> {accum_path} ({len(accum_list)} snapshots)")
    log_info(f"Latest JSON -> {latest_path}")
    if ts_path is not None:
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
    Output format is same as normal run (accum list + latest + timestamped raw) so 032/041 stay compatible.
    """
    from configs.leagues.league_ncaam import (
        CANONICAL_GAMES_PATH,
        ODDS_RAW_ACCUM_PATH,
        ODDS_RAW_LATEST_PATH,
        ensure_ncaam_dirs,
        glob_ncaam_odds_raw_json_files,
        ncaam_odds_latest_read_path,
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
    for path in glob_ncaam_odds_raw_json_files():
        try:
            with open(path, "r", encoding="utf-8") as f:
                snap = json.load(f)
            if isinstance(snap, dict):
                for g in (snap.get("data") or []):
                    eid = (g.get("id") or "").strip() if isinstance(g, dict) else ""
                    if eid:
                        have_event_ids.add(eid)
        except json.JSONDecodeError:
            continue
    _lr = ncaam_odds_latest_read_path()
    if _lr:
        try:
            with open(_lr, "r", encoding="utf-8") as f:
                snap = json.load(f)
            if isinstance(snap, dict):
                for g in (snap.get("data") or []):
                    eid = (g.get("id") or "").strip() if isinstance(g, dict) else ""
                    if eid:
                        have_event_ids.add(eid)
        except json.JSONDecodeError:
            pass

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
    ODDS_RAW_ACCUM_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts_label = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_path = timestamped_odds_raw_path(ts_label)
    with open(ODDS_RAW_LATEST_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    with open(ts_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    accum_list = _load_ncaam_accum_from_disk()
    accum_list.append(snapshot)
    with open(ODDS_RAW_ACCUM_PATH, "w", encoding="utf-8") as f:
        json.dump(accum_list, f, indent=2)
    _print_first_last_odds_dates("NCAAM (backfill)", merged_data)
    log_info(
        f"Backfill: added {len(backfill_games)} events; latest now has {len(merged_data)} total. "
        f"Wrote {ts_path}; accum now {len(accum_list)} snapshots"
    )


# =====================================================
# NCAAM GAP-FILL (historical by date)
# =====================================================

def get_ncaam_covered_dates() -> set[str]:
    """
    From canonical ``data/ncaam/raw`` and legacy ``data/ncaam/market/raw``, treat a date as
    covered only if we have a gap-fill snapshot for that date: ncaam_odds_raw_YYYYMMDD.json
    (exactly 8 digits, no suffix).
    This avoids incorrectly skipping 2025-11-04 when 20251103.json contains games that
    commence on 2025-11-04 UTC (late-evening Nov 3 US).
    """
    from configs.leagues.league_ncaam import glob_ncaam_odds_raw_json_files

    covered = set()
    # Only date-only filenames from gap-fill (ncaam_odds_raw_YYYYMMDD.json)
    pattern = re.compile(r"^ncaam_odds_raw_(\d{8})\.json$")
    for path in glob_ncaam_odds_raw_json_files():
        m = pattern.match(path.name)
        if not m:
            continue
        yyyymmdd = m.group(1)
        if len(yyyymmdd) == 8:
            covered.add(f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}")
    return covered


def get_ncaam_target_date_range() -> tuple[str, str]:
    """
    Target season date range for gap-fill: from canonical games game_date min/max.
    Falls back to 2025-11-03..2026-03-13 if canonical missing.
    """
    from configs.leagues.league_ncaam import CANONICAL_GAMES_PATH

    default_start = "2025-11-03"
    default_end = "2026-03-13"
    path = Path(CANONICAL_GAMES_PATH)
    if not path.exists():
        return default_start, default_end
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return default_start, default_end
    dates = [(r.get("game_date") or "").strip()[:10] for r in rows]
    dates = [d for d in dates if len(d) == 10 and d.count("-") == 2]
    if not dates:
        return default_start, default_end
    return min(dates), max(dates)


def run_gap_fill_ncaam() -> None:
    """
    Gap-fill historical NCAAM odds by date. Reads existing raw files to compute covered dates,
    derives target range from canonical games, fetches only missing dates via historical API,
    writes one ncaam_odds_raw_YYYYMMDD.json per missing date (existing snapshot shape).
    Idempotent: re-run skips dates already present in any raw file.
    """
    from datetime import datetime, timedelta, timezone

    from configs.leagues.league_ncaam import (
        ensure_ncaam_dirs,
        timestamped_odds_raw_path,
    )

    sport_key = "basketball_ncaab"
    ensure_ncaam_dirs()

    covered = get_ncaam_covered_dates()
    start_str, end_str = get_ncaam_target_date_range()
    start_dt = datetime.strptime(start_str, "%Y-%m-%d")
    end_dt = datetime.strptime(end_str, "%Y-%m-%d")
    target_dates = []
    d = start_dt
    while d <= end_dt:
        target_dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    missing = [d for d in target_dates if d not in covered]
    missing.sort()

    log_info(f"NCAAM gap-fill: target range {start_str}..{end_str} ({len(target_dates)} days)")
    log_info(f"Already covered: {len(covered)} distinct game dates in raw files")
    log_info(f"Missing dates to fetch: {len(missing)}")

    if not missing:
        log_info("No missing dates; nothing to fetch.")
        return

    written = 0
    for date_str in missing:
        date_iso = f"{date_str}T12:00:00Z"
        resp = fetch_historical_odds(sport_key, date_iso)
        if not resp or not isinstance(resp.get("data"), list):
            log_info(f"  {date_str}: no data (skip)")
            continue
        snapshot_ts = (resp.get("timestamp") or date_iso).strip()
        snapshot = {
            "captured_at_utc": snapshot_ts,
            "sport": sport_key,
            "source": "the_odds_api",
            "data": resp["data"],
        }
        label = date_str.replace("-", "")
        out_path = timestamped_odds_raw_path(label)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        written += 1
        log_info(f"  {date_str}: wrote {out_path.name} ({len(resp['data'])} games)")

    log_info(f"Gap-fill complete: wrote {written} new raw snapshot(s).")


# =====================================================
# ENTRYPOINT
# =====================================================

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Fetch betting lines from The Odds API")
    parser.add_argument("--league", required=True, choices=sorted(SPORT_KEY_BY_LEAGUE))
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
    parser.add_argument(
        "--gap-fill-ncaam",
        action="store_true",
        help="Gap-fill missing NCAAM odds by date (historical API); skips dates already in raw",
    )
    parser.add_argument("--silent", action="store_true", help="Only print critical errors")
    args = parser.parse_args()
    set_silent(args.silent)

    if args.gap_fill_ncaam:
        if args.league != "ncaam":
            raise SystemExit("--gap-fill-ncaam requires --league ncaam")
        run_gap_fill_ncaam()
        return

    if args.backfill_ncaam:
        if args.league != "ncaam":
            raise SystemExit("--backfill-ncaam requires --league ncaam")
        run_backfill_ncaam()
        return

    if args.league == "nba":
        run_nba(skip_if_recent_minutes=args.skip_if_recent)
    elif args.league == "ncaam":
        run_ncaam(skip_if_recent_minutes=args.skip_if_recent)
    else:
        run_configured_league(args.league, skip_if_recent_minutes=args.skip_if_recent)


if __name__ == "__main__":
    main()
