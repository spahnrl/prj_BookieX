"""
b_gen_001_ingest_schedule.py

Unified schedule ingestion for NBA and NCAAM.

- NBA: fetch from NBA CDN, normalize to flat schema, JSON-first via io_helpers.
- NCAAM: fetch ESPN scoreboard by date range, normalize to NBA-aligned schema,
  JSON-first via io_helpers. Supports --start-date / --end-date. Default (no dates):
  start 2025-10-01, end **America/Chicago calendar today** + 14 days (so March Madness
  is included and the window matches CST slate day). Games
  where either team is TBD are excluded from the saved schedule.

Usage:
  python eng/pipelines/shared/b_gen_001_ingest_schedule.py --league nba
  python eng/pipelines/shared/b_gen_001_ingest_schedule.py --league ncaam [--start-date YYYYMMDD] [--end-date YYYYMMDD]

Forward-only: reads only external APIs; writes only schedule raw JSON + legacy CSV audit.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import requests
from pathlib import Path
from datetime import datetime, timedelta, UTC

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils.io_helpers import get_schedule_raw_path, save_schedule_raw
from utils.run_log import set_silent, log_info, log_error
from utils.datetime_bridge import SLATE_TIMEZONE


def _requests_get(url: str, **kwargs):
    """Use certifi when local Python's default trust store cannot verify public sports APIs."""
    try:
        import certifi
        kwargs.setdefault("verify", certifi.where())
    except Exception:
        pass
    try:
        return requests.get(url, **kwargs)
    except requests.exceptions.SSLError as exc:
        log_error(f"SSL verification failed for {url}; retrying schedule fetch with verify=False: {exc}")
        retry_kwargs = dict(kwargs)
        retry_kwargs["verify"] = False
        return requests.get(url, **retry_kwargs)


# =============================================================================
# NBA: FETCH, NORMALIZE, WRITE
# =============================================================================

NBA_SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
NBA_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://www.nba.com/"}
NBA_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
NBA_SCOREBOARD_LOOKBACK_DAYS = 3
NBA_SCOREBOARD_LOOKAHEAD_DAYS = 14


def _nba_derive_season_year(game_date_est: str) -> int:
    date_str = game_date_est.split("T")[0]
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.year if dt.month >= 10 else dt.year - 1


def _nba_normalize(raw: dict) -> list[dict]:
    records = []
    for game_date in raw["leagueSchedule"]["gameDates"]:
        for game in game_date["games"]:
            season_year = _nba_derive_season_year(game["gameDateEst"])
            records.append({
                "game_id": game["gameId"],
                "game_date": game["gameDateEst"],
                "game_time_utc": game["gameTimeUTC"],
                "status": game["gameStatus"],
                "season_year": season_year,
                "home_team_id": game["homeTeam"]["teamId"],
                "home_team_score": game["homeTeam"]["score"],
                "away_team_id": game["awayTeam"]["teamId"],
                "away_team_score": game["awayTeam"]["score"],
                "is_playoff": game.get("playoffGame", False),
            })
    return records


def _nba_build_team_lookup_for_scoreboard() -> dict[str, dict]:
    """Map ESPN scoreboard team names/abbrs to the NBA team ids used by the pipeline."""
    from utils.io_helpers import get_team_map_path

    path = get_team_map_path("nba")
    if not path.exists():
        raise FileNotFoundError(f"Missing team map: {path}")
    with open(path, "r", encoding="utf-8") as f:
        teams = json.load(f)

    lookup = {}
    for t in teams:
        keys = {
            str(t.get("team_id") or "").strip(),
            str(t.get("abbreviation") or "").strip().upper(),
            str(t.get("team_name") or "").strip().lower(),
        }
        for key in [k for k in keys if k]:
            lookup[key] = t
    return lookup


def _nba_scoreboard_status_code(status_name: str | None, status_state: str | None, completed: bool) -> int:
    if completed or (status_state or "").lower() == "post":
        return 3
    if (status_state or "").lower() == "in":
        return 2
    name = (status_name or "").upper()
    if "FINAL" in name:
        return 3
    return 1


def _nba_normalize_scoreboard_payload(payload: dict, requested_date: str, team_lookup: dict[str, dict]) -> list[dict]:
    rows = []
    events = payload.get("events", []) or []
    for event in events:
        comps = event.get("competitions") or []
        if not comps:
            continue
        comp0 = comps[0] or {}
        competitors = comp0.get("competitors") or []
        home = _ncaam_extract_competitor(competitors, "home")
        away = _ncaam_extract_competitor(competitors, "away")
        if not home or not away:
            continue

        def _team(c: dict) -> dict:
            return c.get("team") or {}

        def _lookup(c: dict) -> dict | None:
            t = _team(c)
            candidates = [
                str(t.get("id") or "").strip(),
                str(t.get("abbreviation") or "").strip().upper(),
                str(t.get("displayName") or "").strip().lower(),
                str(t.get("shortDisplayName") or "").strip().lower(),
                str(t.get("name") or "").strip().lower(),
            ]
            for key in candidates:
                if key and key in team_lookup:
                    return team_lookup[key]
            return None

        home_match = _lookup(home)
        away_match = _lookup(away)
        if not home_match or not away_match:
            log_error(
                "NBA scoreboard event skipped; team map miss: "
                f"{(_team(away).get('displayName') or _team(away).get('name'))} @ "
                f"{(_team(home).get('displayName') or _team(home).get('name'))}"
            )
            continue

        event_date = event.get("date") or ""
        requested_iso_date = datetime.strptime(requested_date, "%Y%m%d").date().isoformat()
        status_type = ((event.get("status") or {}).get("type") or {})
        completed = bool(status_type.get("completed"))
        status_name = status_type.get("name")
        status_state = status_type.get("state")

        def _score(c: dict):
            v = c.get("score")
            if v in (None, ""):
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        rows.append({
            "game_id": f"espn_nba_{event.get('id')}",
            "game_date": requested_iso_date,
            "game_time_utc": event_date,
            "status": _nba_scoreboard_status_code(status_name, status_state, completed),
            "season_year": _nba_derive_season_year(event_date[:10]) if event_date else 2025,
            "home_team_id": home_match["team_id"],
            "home_team_score": _score(home),
            "away_team_id": away_match["team_id"],
            "away_team_score": _score(away),
            "is_playoff": True,
            "source_system": "espn_public_scoreboard",
            "requested_date": requested_date,
            "espn_game_id": str(event.get("id") or ""),
            "status_name": status_name,
            "status_state": status_state,
            "completed_flag": int(completed),
        })
    return rows


def _nba_fetch_scoreboard_window() -> list[dict]:
    today_cst = datetime.now(SLATE_TIMEZONE).date()
    start_date = today_cst - timedelta(days=NBA_SCOREBOARD_LOOKBACK_DAYS)
    end_date = today_cst + timedelta(days=NBA_SCOREBOARD_LOOKAHEAD_DAYS)
    team_lookup = _nba_build_team_lookup_for_scoreboard()
    rows = []
    cur = start_date
    while cur <= end_date:
        date_str = cur.strftime("%Y%m%d")
        resp = _requests_get(NBA_SCOREBOARD_URL, params={"dates": date_str, "limit": 100}, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        daily_rows = _nba_normalize_scoreboard_payload(payload, date_str, team_lookup)
        rows.extend(daily_rows)
        log_info(f"NBA ESPN scoreboard {date_str}: normalized {len(daily_rows)} events")
        cur += timedelta(days=1)
    return rows


def _nba_merge_scoreboard_rows(static_rows: list[dict], scoreboard_rows: list[dict]) -> list[dict]:
    """
    Keep the full NBA static schedule, but overlay resolved date/team playoff rows from
    ESPN scoreboard. This catches Finals games that are still TBD or absent in static data.
    """
    merged = list(static_rows)
    existing_keys = {
        (
            str(r.get("game_date") or "")[:10],
            str(r.get("away_team_id") or ""),
            str(r.get("home_team_id") or ""),
        )
        for r in merged
    }
    added = 0
    for row in scoreboard_rows:
        key = (
            str(row.get("game_date") or "")[:10],
            str(row.get("away_team_id") or ""),
            str(row.get("home_team_id") or ""),
        )
        if key in existing_keys:
            continue
        merged.append(row)
        existing_keys.add(key)
        added += 1
    if added:
        log_info(f"NBA schedule repair: added {added} resolved scoreboard games")
    return merged


def _nba_write_legacy_csv(rows: list[dict]) -> None:
    path = get_schedule_raw_path("nba").parent / "nba_schedule.csv"
    if not rows:
        return
    fieldnames = sorted({k for row in rows for k in row.keys()})
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    log_info(f"Legacy audit CSV: {path}")


def run_nba() -> None:
    resp = _requests_get(NBA_SCHEDULE_URL, headers=NBA_HEADERS, timeout=30)
    resp.raise_for_status()
    raw = resp.json()
    normalized = _nba_normalize(raw)
    try:
        scoreboard_rows = _nba_fetch_scoreboard_window()
        normalized = _nba_merge_scoreboard_rows(normalized, scoreboard_rows)
    except Exception as exc:
        log_error(f"NBA scoreboard repair feed failed; continuing with static schedule only: {exc}")
    save_schedule_raw("nba", normalized)
    _nba_write_legacy_csv(normalized)
    log_info(f"Schedule JSON: {get_schedule_raw_path('nba')}")
    log_info(f"Rows: {len(normalized)}")


# =============================================================================
# NCAAM: FETCH BY DATE, NORMALIZE, DEDUPE, WRITE
# =============================================================================

# Default lookahead days so a normal run fetches through March Madness (e.g. run on 3/16 gets 3/17+)
NCAAM_DEFAULT_END_LOOKAHEAD_DAYS = 14

NCAAM_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/"
    "basketball/mens-college-basketball/scoreboard"
)


def _ncaam_build_dates(start_date: str, end_date: str) -> list[str]:
    start_dt = datetime.strptime(start_date, "%Y%m%d").date()
    end_dt = datetime.strptime(end_date, "%Y%m%d").date()
    if end_dt < start_dt:
        raise ValueError("end_date must be >= start_date")
    out = []
    cur = start_dt
    while cur <= end_dt:
        out.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return out


def _ncaam_team_name_norm_key(value: str) -> str:
    text = (value or "").strip().lower()
    for old, new in [("&", " and "), ("'", ""), (".", " "), ("-", " "), ("/", " "), (",", " "), ("(", " "), (")", " ")]:
        text = text.replace(old, new)
    text = "".join(c for c in text if c.isalnum() or c.isspace())
    return " ".join(text.split()).replace(" ", "")


def _ncaam_extract_competitor(competitors: list[dict], home_away: str) -> dict | None:
    for c in competitors:
        if str(c.get("homeAway", "")).lower() == home_away:
            return c
    return None


def _ncaam_event_competitor_name(c: dict) -> str:
    """Competitor display name for TBD check; same source as normalize."""
    t = (c or {}).get("team") or {}
    return (t.get("displayName") or t.get("shortDisplayName") or t.get("name") or "").strip()


def _ncaam_event_has_tbd(event: dict) -> bool:
    """True if either home or away competitor name is literally TBD."""
    comps = event.get("competitions") or []
    if not comps:
        return False
    comp0 = comps[0] or {}
    competitors = comp0.get("competitors") or []
    home = _ncaam_extract_competitor(competitors, "home")
    away = _ncaam_extract_competitor(competitors, "away")
    if not home or not away:
        return False
    return (
        _ncaam_event_competitor_name(home).upper() == "TBD"
        or _ncaam_event_competitor_name(away).upper() == "TBD"
    )


def _ncaam_row_has_tbd(row: dict) -> bool:
    """True if either home_team_raw or away_team_raw is TBD (for filtering saved schedule)."""
    home = (row.get("home_team_raw") or "").strip().upper()
    away = (row.get("away_team_raw") or "").strip().upper()
    return home == "TBD" or away == "TBD"


def _ncaam_normalize_payload(payload: dict, requested_date: str) -> list[dict]:
    import re
    rows = []
    events = payload.get("events", []) or []
    fetched_at_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    season_obj = payload.get("season") or {}
    season_year = season_obj.get("year")

    for event in events:
        event_id = event.get("id")
        event_date = event.get("date")
        event_name = event.get("name")
        short_name = event.get("shortName")
        season_type_raw = (event.get("season") or {}).get("type")
        season_type = season_type_raw.get("type") if isinstance(season_type_raw, dict) else season_type_raw
        status_obj = event.get("status") or {}
        status_type = status_obj.get("type") or {}
        status_name = status_type.get("name")
        status_state = status_type.get("state")
        completed_flag = status_type.get("completed")
        detail = status_type.get("detail")
        short_detail = status_type.get("shortDetail")

        comps = event.get("competitions", [])
        if not comps:
            continue
        comp0 = comps[0] or {}
        competitors = comp0.get("competitors") or []
        home = _ncaam_extract_competitor(competitors, "home")
        away = _ncaam_extract_competitor(competitors, "away")
        if not home or not away:
            continue

        venue = comp0.get("venue") or {}
        neutral_site_flag = int(bool(comp0.get("neutralSite", False)))

        def _name(c: dict) -> str:
            t = c.get("team") or {}
            return t.get("displayName") or t.get("shortDisplayName") or t.get("name") or ""

        def _abbr(c: dict) -> str:
            return (c.get("team") or {}).get("abbreviation") or ""

        def _score(c: dict):
            v = c.get("score")
            if v in (None, ""):
                return None
            try:
                return int(v)
            except Exception:
                return None

        home_team_raw = _name(home)
        away_team_raw = _name(away)
        game_date_str = event_date[:10] if event_date else None

        row = {
            "game_id": str(event_id) if event_id else "",
            "game_date": game_date_str,
            "game_time_utc": (event_date or "").strip(),
            "status": status_name or status_state or "",
            "season_year": season_year,
            "home_team_id": "",
            "away_team_id": "",
            "home_team_score": _score(home),
            "away_team_score": _score(away),
            "requested_date": requested_date,
            "season_type": season_type,
            "event_name": event_name,
            "short_name": short_name,
            "status_name": status_name,
            "status_state": status_state,
            "status_detail": detail,
            "status_short_detail": short_detail,
            "completed_flag": int(bool(completed_flag)),
            "home_team_raw": home_team_raw,
            "away_team_raw": away_team_raw,
            "home_team_normalized": (home_team_raw or "").strip().lower(),
            "away_team_normalized": (away_team_raw or "").strip().lower(),
            "home_team_norm_key": _ncaam_team_name_norm_key(home_team_raw),
            "away_team_norm_key": _ncaam_team_name_norm_key(away_team_raw),
            "home_team_abbr": _abbr(home),
            "away_team_abbr": _abbr(away),
            "neutral_site_flag": neutral_site_flag,
            "venue_name": venue.get("fullName") or venue.get("name") or "",
            "source_system": "espn_public_scoreboard",
            "fetched_at_utc": fetched_at_utc,
        }
        rows.append(row)
    return rows


def _ncaam_dedupe(rows: list[dict]) -> list[dict]:
    by_id = {}
    for r in rows:
        k = str(r.get("game_id") or "").strip()
        if k:
            by_id[k] = r
    out = list(by_id.values())
    out.sort(key=lambda r: (str(r.get("game_date") or ""), str(r.get("away_team_raw") or ""), str(r.get("home_team_raw") or ""), str(r.get("game_id") or "")))
    return out


def _ncaam_write_legacy_csv(rows: list[dict]) -> None:
    from configs.leagues.league_ncaam import SCHEDULE_RAW_PATH
    if not rows:
        return
    SCHEDULE_RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHEDULE_RAW_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys(), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    log_info(f"Legacy audit CSV: {SCHEDULE_RAW_PATH}")


def _ncaam_load_per_date_if_usable(raw_path: Path) -> dict | None:
    """If path exists and is valid ESPN scoreboard payload (dict with 'events' list), return it; else None."""
    if not raw_path.exists():
        return None
    try:
        with open(raw_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict) or "events" not in payload:
        return None
    if not isinstance(payload.get("events"), list):
        return None
    return payload


def run_ncaam(start_date: str, end_date: str) -> None:
    from configs.leagues.league_ncaam import RAW_DIR, ensure_ncaam_dirs

    ensure_ncaam_dirs()
    log_info("NCAAM ingest policy: always fetch fresh per-date scoreboard payloads (no raw reuse)")
    date_list = _ncaam_build_dates(start_date, end_date)
    all_rows = []
    all_payloads = []

    for date_str in date_list:
        raw_path = RAW_DIR / f"ncaam_schedule_raw_{date_str}.json"
        resp = _requests_get(NCAAM_SCOREBOARD_URL, params={"dates": date_str, "groups": 50, "limit": 500}, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        events = payload.get("events") or []
        events_for_cache = [e for e in events if not _ncaam_event_has_tbd(e)]
        payload_for_cache = {**payload, "events": events_for_cache}
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(payload_for_cache, f, indent=2)
        excluded_tbd = len(events) - len(events_for_cache)
        log_info(f"{date_str}: fetched {len(events)} events; excluded {excluded_tbd} TBD from cache; wrote {len(events_for_cache)} to per-date cache")

        all_payloads.append({"requested_date": date_str, "payload": payload})

        rows = _ncaam_normalize_payload(payload, date_str)
        all_rows.extend(rows)
        log_info(f"{date_str} -> events normalized: {len(rows)}")

    deduped = _ncaam_dedupe(all_rows)
    # Exclude games where either team is TBD so pipeline only gets named matchups
    schedule_to_save = [r for r in deduped if not _ncaam_row_has_tbd(r)]
    excluded_tbd_count = len(deduped) - len(schedule_to_save)
    if excluded_tbd_count:
        log_info(f"Excluded {excluded_tbd_count} games with TBD (saving only named matchups)")

    raw_latest = RAW_DIR / "ncaam_schedule_raw_latest.json"
    raw_latest.parent.mkdir(parents=True, exist_ok=True)
    with open(raw_latest, "w", encoding="utf-8") as f:
        json.dump({
            "captured_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source": "espn_public_scoreboard",
            "requested_start_date": start_date,
            "requested_end_date": end_date,
            "date_payloads": all_payloads,
        }, f, indent=2)
    log_info(f"Latest raw JSON: {raw_latest}")

    save_schedule_raw("ncaam", schedule_to_save)
    _ncaam_write_legacy_csv(schedule_to_save)

    log_info(f"Schedule JSON: {get_schedule_raw_path('ncaam')}")
    log_info(f"Date count: {len(date_list)}; unique games (after dedupe): {len(deduped)}; saved (no TBD): {len(schedule_to_save)}")


# =============================================================================
# ENTRYPOINT
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest schedule (NBA or NCAAM)")
    parser.add_argument("--league", required=True, choices=["nba", "ncaam"])
    parser.add_argument("--start-date", dest="start_date", help="NCAAM only: YYYYMMDD")
    parser.add_argument("--end-date", dest="end_date", help="NCAAM only: YYYYMMDD")
    parser.add_argument("--silent", action="store_true", help="Only print critical errors")
    args = parser.parse_args()
    set_silent(args.silent)

    if args.league == "nba":
        run_nba()
    else:
        if (args.start_date and not args.end_date) or (args.end_date and not args.start_date):
            raise ValueError("NCAAM: provide both --start-date and --end-date or neither")
        if args.start_date and args.end_date:
            run_ncaam(args.start_date, args.end_date)
        else:
            # Default: season start through CST today + lookahead (aligns with daily slate / March Madness window)
            today_cst = datetime.now(SLATE_TIMEZONE).date()
            start_str = "20251001"
            end_date = today_cst + timedelta(days=NCAAM_DEFAULT_END_LOOKAHEAD_DAYS)
            end_str = end_date.strftime("%Y%m%d")
            run_ncaam(start_str, end_str)


if __name__ == "__main__":
    main()
