"""
b_gen_001_ingest_schedule.py

Unified schedule ingestion for NBA and NCAAM.

- NBA: fetch from NBA CDN, normalize to flat schema, JSON-first via io_helpers.
- NCAAM: fetch ESPN scoreboard by date range, normalize to NBA-aligned schema,
  JSON-first via io_helpers. Supports --start-date / --end-date.

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


# =============================================================================
# NBA: FETCH, NORMALIZE, WRITE
# =============================================================================

NBA_SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
NBA_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://www.nba.com/"}


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


def _nba_write_legacy_csv(rows: list[dict]) -> None:
    path = get_schedule_raw_path("nba").parent / "nba_schedule.csv"
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    log_info(f"Legacy audit CSV: {path}")


def run_nba() -> None:
    resp = requests.get(NBA_SCHEDULE_URL, headers=NBA_HEADERS, timeout=30)
    resp.raise_for_status()
    raw = resp.json()
    normalized = _nba_normalize(raw)
    save_schedule_raw("nba", normalized)
    _nba_write_legacy_csv(normalized)
    log_info(f"Schedule JSON: {get_schedule_raw_path('nba')}")
    log_info(f"Rows: {len(normalized)}")


# =============================================================================
# NCAAM: FETCH BY DATE, NORMALIZE, DEDUPE, WRITE
# =============================================================================

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


def run_ncaam(start_date: str, end_date: str) -> None:
    from configs.leagues.league_ncaam import RAW_DIR, ensure_ncaam_dirs

    ensure_ncaam_dirs()
    date_list = _ncaam_build_dates(start_date, end_date)
    all_rows = []
    all_payloads = []

    for date_str in date_list:
        resp = requests.get(NCAAM_SCOREBOARD_URL, params={"dates": date_str, "groups": 50, "limit": 500}, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        all_payloads.append({"requested_date": date_str, "payload": payload})

        raw_path = RAW_DIR / f"ncaam_schedule_raw_{date_str}.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        rows = _ncaam_normalize_payload(payload, date_str)
        all_rows.extend(rows)
        log_info(f"{date_str} -> events normalized: {len(rows)}")

    deduped = _ncaam_dedupe(all_rows)

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

    save_schedule_raw("ncaam", deduped)
    _ncaam_write_legacy_csv(deduped)

    log_info(f"Schedule JSON: {get_schedule_raw_path('ncaam')}")
    log_info(f"Date count: {len(date_list)}; unique games: {len(deduped)}")


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
            # Default: full 2025/2026 season (2025-10-01 to today) for backtest-ready pipeline
            today_str = datetime.now(UTC).strftime("%Y%m%d")
            start_str = "20251001"
            run_ncaam(start_str, today_str)


if __name__ == "__main__":
    main()
