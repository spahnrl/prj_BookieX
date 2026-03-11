"""
tools/build_historical_schedules.py

Build historical schedule foundation for 2022-23 and 2023-24 seasons.

NBA: Call the NBA CDN for the 2022-23 and 2023-24 seasons. Save as
  data/nba/raw/nba_schedule_2023.json and data/nba/raw/nba_schedule_2024.json.
  Output structure matches nba_schedule.json (flat list from _nba_normalize).

NCAAM: Call ESPN Scoreboard API for 2022-23 and 2023-24 windows.
  Pull all games between Nov 1 and April 15 for each cycle. Save as
  data/ncaam/raw/ncaam_schedule_raw_20221101_20230415.json and
  data/ncaam/raw/ncaam_schedule_raw_20231101_20240415.json (or merge into
  one list per season). Output structure matches ncaam_schedule_raw.json.

Deduplication: Merge new historical games into master schedule lists
  (nba_schedule.json and ncaam_schedule_raw.json) by game_id.

Usage:
  python tools/build_historical_schedules.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests

from configs.leagues.league_nba import RAW_DIR as NBA_RAW_DIR
NCAAM_RAW_DIR = PROJECT_ROOT / "data" / "ncaam" / "raw"

# Season label -> (CDN season string, output year suffix for filename)
NBA_SEASONS = [
    ("2022-23", 2023),  # 2022-23 season -> nba_schedule_2023.json
    ("2023-24", 2024),
]
NBA_CDN_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
NBA_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://www.nba.com/"}

# NCAAM: (season label, nov 1, april 15)
NCAAM_WINDOWS = [
    ("2022-23", date(2022, 11, 1), date(2023, 4, 15)),
    ("2023-24", date(2023, 11, 1), date(2024, 4, 15)),
]
NCAAM_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/"
    "basketball/mens-college-basketball/scoreboard"
)


def _nba_derive_season_year(game_date_est: str) -> int:
    date_str = game_date_est.split("T")[0]
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.year if dt.month >= 10 else dt.year - 1


def _nba_normalize(raw: dict) -> list[dict]:
    """Same as b_gen_001: produce flat list matching nba_schedule.json."""
    records = []
    for game_date in raw.get("leagueSchedule", {}).get("gameDates", []):
        for game in game_date.get("games", []):
            season_year = _nba_derive_season_year(game["gameDateEst"])
            records.append({
                "game_id": game["gameId"],
                "game_date": game["gameDateEst"],
                "game_time_utc": game.get("gameTimeUTC", ""),
                "status": game.get("gameStatus"),
                "season_year": season_year,
                "home_team_id": game["homeTeam"]["teamId"],
                "home_team_score": game["homeTeam"].get("score"),
                "away_team_id": game["awayTeam"]["teamId"],
                "away_team_score": game["awayTeam"].get("score"),
                "is_playoff": game.get("playoffGame", False),
            })
    return records


def fetch_nba_season(season_str: str) -> dict | None:
    """Fetch NBA schedule for season (e.g. 2022-23). Returns raw CDN response or None."""
    try:
        r = requests.get(
            NBA_CDN_URL,
            headers=NBA_HEADERS,
            params={"Season": season_str},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and "leagueSchedule" in data:
            return data
        return None
    except Exception as e:
        print(f"  NBA fetch {season_str} failed: {e}")
        return None


def build_nba_historical() -> None:
    NBA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    for season_str, year_suffix in NBA_SEASONS:
        print(f"NBA: Fetching {season_str}...")
        raw = fetch_nba_season(season_str)
        if not raw:
            print(f"  Skipping {season_str} (no data). CDN may only serve current season.")
            continue
        label = raw.get("leagueSchedule", {}).get("seasonYear", "")
        if season_str not in str(label):
            print(f"  Warning: CDN returned season {label}, expected {season_str}. Saving anyway.")
        rows = _nba_normalize(raw)
        out_path = NBA_RAW_DIR / f"nba_schedule_{year_suffix}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2)
        print(f"  Saved {len(rows)} games -> {out_path}")
        time.sleep(0.5)


def _ncaam_team_name_norm_key(value: str) -> str:
    text = (value or "").strip().lower()
    for old, new in [("&", " and "), ("'", ""), (".", " "), ("-", " "), ("/", " "), (",", " "), ("(", " "), (")", " ")]:
        text = text.replace(old, new)
    text = "".join(c for c in text if c.isalnum() or c.isspace())
    return " ".join(text.split()).replace(" ", "")


def _ncaam_extract_competitor(competitors: list, home_away: str):
    for c in competitors:
        if str(c.get("homeAway", "")).lower() == home_away:
            return c
    return None


def _ncaam_normalize_payload(payload: dict, requested_date: str, season_year: int | None) -> list[dict]:
    """Produce flat list matching ncaam_schedule_raw.json (same schema as b_gen_001)."""
    rows = []
    events = payload.get("events", []) or []
    fetched_at_utc = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000000Z")
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
        def _name(c): return (c.get("team") or {}).get("displayName") or (c.get("team") or {}).get("shortDisplayName") or (c.get("team") or {}).get("name") or ""
        def _abbr(c): return (c.get("team") or {}).get("abbreviation") or ""
        def _score(c):
            v = c.get("score")
            if v in (None, ""): return None
            try: return int(v)
            except Exception: return None
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


def build_ncaam_historical() -> None:
    NCAAM_RAW_DIR.mkdir(parents=True, exist_ok=True)
    for season_label, start_d, end_d in NCAAM_WINDOWS:
        print(f"NCAAM: Fetching {season_label} ({start_d} to {end_d})...")
        season_year = start_d.year if start_d.month >= 8 else start_d.year + 1
        if start_d.month >= 11:
            season_year = start_d.year + 1
        all_rows = []
        cur = start_d
        while cur <= end_d:
            date_str = cur.strftime("%Y%m%d")
            try:
                r = requests.get(
                    NCAAM_SCOREBOARD_URL,
                    params={"dates": date_str, "groups": 50, "limit": 500},
                    timeout=30,
                )
                r.raise_for_status()
                payload = r.json()
                rows = _ncaam_normalize_payload(payload, date_str, season_year)
                all_rows.extend(rows)
            except Exception as e:
                print(f"  Warning: {date_str} failed: {e}")
            cur += timedelta(days=1)
            time.sleep(0.15)
        by_id = {}
        for r in all_rows:
            k = str(r.get("game_id") or "").strip()
            if k:
                by_id[k] = r
        deduped = list(by_id.values())
        deduped.sort(key=lambda r: (str(r.get("game_date") or ""), str(r.get("away_team_raw") or ""), str(r.get("game_id") or "")))
        out_path = NCAAM_RAW_DIR / f"ncaam_schedule_raw_{start_d.strftime('%Y%m%d')}_{end_d.strftime('%Y%m%d')}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(deduped, f, indent=2)
        print(f"  Saved {len(deduped)} games -> {out_path}")


def merge_into_master_nba() -> None:
    """Merge all nba_schedule*.json into data/nba/raw/nba_schedule.json by game_id."""
    master_path = NBA_RAW_DIR / "nba_schedule.json"
    by_id = {}
    for path in sorted(NBA_RAW_DIR.glob("nba_schedule*.json")):
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for g in data:
            gid = str(g.get("game_id") or "").strip()
            if gid:
                by_id[gid] = g
    merged = list(by_id.values())
    merged.sort(key=lambda g: (str(g.get("game_date") or ""), str(g.get("game_id") or "")))
    NBA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    with open(master_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    print(f"Merged {len(merged)} NBA games into {master_path}")


def merge_into_master_ncaam() -> None:
    """Merge ncaam_schedule_raw.json and all ncaam_schedule_raw_*.json into ncaam_schedule_raw.json."""
    from configs.leagues.league_ncaam import RAW_DIR
    master_path = RAW_DIR / "ncaam_schedule_raw.json"
    by_id = {}
    paths = [master_path] if master_path.exists() else []
    paths += sorted(RAW_DIR.glob("ncaam_schedule_raw_*.json"))
    for path in paths:
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if isinstance(data, list):
            for g in data:
                gid = str(g.get("game_id") or "").strip()
                if gid:
                    by_id[gid] = g
        elif isinstance(data, dict) and "events" in data:
            for ev in data.get("events", []):
                eid = str(ev.get("id") or ev.get("game_id") or "").strip()
                if not eid:
                    continue
                comps = ev.get("competitions", [])
                if not comps:
                    continue
                comp0 = comps[0] or {}
                competitors = comp0.get("competitors") or []
                home = _ncaam_extract_competitor(competitors, "home")
                away = _ncaam_extract_competitor(competitors, "away")
                if not home or not away:
                    continue
                def _n(c): return (c.get("team") or {}).get("displayName") or ""
                gdate = (ev.get("date") or ev.get("game_date") or "")[:10]
                by_id[eid] = {
                    "game_id": eid,
                    "game_date": gdate,
                    "game_time_utc": (ev.get("date") or "").strip(),
                    "status": "",
                    "season_year": (ev.get("season") or {}).get("year") if isinstance(ev.get("season"), dict) else None,
                    "home_team_id": "",
                    "away_team_id": "",
                    "home_team_score": home.get("score"),
                    "away_team_score": away.get("score"),
                    "requested_date": "",
                    "season_type": (ev.get("season") or {}).get("type") if isinstance(ev.get("season"), dict) else None,
                    "event_name": ev.get("name"),
                    "short_name": ev.get("shortName"),
                    "status_name": "",
                    "status_state": "",
                    "status_detail": "",
                    "status_short_detail": "",
                    "completed_flag": 0,
                    "home_team_raw": _n(home),
                    "away_team_raw": _n(away),
                    "home_team_normalized": "",
                    "away_team_normalized": "",
                    "home_team_norm_key": "",
                    "away_team_norm_key": "",
                    "home_team_abbr": (home.get("team") or {}).get("abbreviation") or "",
                    "away_team_abbr": (away.get("team") or {}).get("abbreviation") or "",
                    "neutral_site_flag": 0,
                    "venue_name": "",
                    "source_system": "espn_public_scoreboard",
                    "fetched_at_utc": "",
                }
    merged = list(by_id.values())
    merged.sort(key=lambda r: (str(r.get("game_date") or ""), str(r.get("away_team_raw") or ""), str(r.get("game_id") or "")))
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with open(master_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    print(f"Merged {len(merged)} NCAAM games into {master_path}")


def main() -> None:
    build_nba_historical()
    build_ncaam_historical()
    merge_into_master_nba()
    merge_into_master_ncaam()
    print("Done.")


if __name__ == "__main__":
    main()
