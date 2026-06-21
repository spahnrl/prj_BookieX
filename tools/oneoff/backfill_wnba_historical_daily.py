"""
Backfill WNBA daily prediction artifacts from real historical odds.

This is intentionally narrow:
- Uses The Odds API historical WNBA odds endpoint.
- Writes historical raw/flat files away from live latest artifacts.
- Fetches real ESPN WNBA results for the requested window so point-history models
  can use only settled games before each slate.
- Does not fabricate odds, picks, prices, results, ROI, or backtests.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional local convenience
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eng.daily import build_wnba_daily_view as wnba_daily
from eng.pipelines.shared.e_gen_032_get_betline_flatten import (
    NCAAM_FLAT_FIELDS,
    _ncaam_flatten_snapshot,
)

RAW_DIR = PROJECT_ROOT / "data" / "wnba" / "raw"
RAW_HIST_DIR = RAW_DIR / "historical_odds"
DERIVED_HIST_DIR = PROJECT_ROOT / "data" / "wnba" / "derived" / "historical"
BACKUP_STAMP = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

ESPN_WNBA_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
HISTORICAL_ODDS_URL = "https://api.the-odds-api.com/v4/historical/sports/basketball_wnba/odds"
MARKETS = "h2h,spreads,totals"
REGIONS = "us"
ODDS_FORMAT = "american"
SNAPSHOT_TIME_UTC = "16:00:00"


def _safe_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_int(value):
    text = _safe_text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _parse_utc(value: str) -> datetime | None:
    text = _safe_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _date_range(start: date, end: date) -> list[date]:
    out = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _api_key() -> str:
    if load_dotenv is not None:
        load_dotenv(PROJECT_ROOT / ".env")
    key = os.getenv("ODDS_API_KEY")
    if not key:
        raise SystemExit("ODDS_API_KEY is not available; cannot fetch historical WNBA odds.")
    return key


def _requests_get(url: str, *, params: dict, timeout: int = 60):
    try:
        import certifi

        verify = certifi.where()
    except Exception:
        verify = True
    try:
        return requests.get(url, params=params, timeout=timeout, verify=verify)
    except requests.exceptions.SSLError:
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        print("[wnba_historical_backfill] SSL retry enabled.")
        return requests.get(url, params=params, timeout=timeout, verify=False)


def _extract_competitor(competitors: list[dict], home_away: str) -> dict | None:
    for comp in competitors or []:
        if _safe_text(comp.get("homeAway")).lower() == home_away:
            return comp
    return None


def _team_name(comp: dict | None) -> str:
    team = (comp or {}).get("team") or {}
    return _safe_text(team.get("displayName") or team.get("shortDisplayName") or team.get("name"))


def _score(comp: dict | None):
    return _safe_int((comp or {}).get("score"))


def _normalize_espn_payload(payload: dict, requested_date: str) -> list[dict]:
    rows = []
    for event in payload.get("events", []) or []:
        comps = event.get("competitions") or []
        if not comps:
            continue
        comp0 = comps[0] or {}
        competitors = comp0.get("competitors") or []
        home = _extract_competitor(competitors, "home")
        away = _extract_competitor(competitors, "away")
        if not home or not away:
            continue
        status_type = ((event.get("status") or {}).get("type") or {})
        venue = comp0.get("venue") or {}
        rows.append(
            {
                "espn_game_id": _safe_text(event.get("id")),
                "requested_date": requested_date,
                "event_date_utc": _safe_text(event.get("date")),
                "game_date_utc": _safe_text(event.get("date"))[:10],
                "home_team": _team_name(home),
                "away_team": _team_name(away),
                "home_score": _score(home),
                "away_score": _score(away),
                "completed": bool(status_type.get("completed")),
                "status_name": _safe_text(status_type.get("name") or status_type.get("description")),
                "status_state": _safe_text(status_type.get("state")),
                "venue": _safe_text(venue.get("fullName") or venue.get("name")),
                "source_system": "espn_public_scoreboard_wnba",
            }
        )
    return rows


def _fetch_results(start: date, end: date) -> dict:
    rows = []
    for day in _date_range(start, end):
        date_str = day.strftime("%Y%m%d")
        resp = _requests_get(ESPN_WNBA_SCOREBOARD_URL, params={"dates": date_str, "limit": 500}, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        daily = _normalize_espn_payload(payload, date_str)
        rows.extend(daily)
        print(f"[wnba_historical_backfill] ESPN {date_str}: events={len(payload.get('events') or [])} normalized={len(daily)}")
    deduped = {}
    for row in rows:
        key = row.get("espn_game_id") or f"{row.get('requested_date')}:{row.get('away_team')}:{row.get('home_team')}"
        deduped[key] = row
    result_rows = list(deduped.values())
    label = f"{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
    raw_json = RAW_DIR / f"wnba_historical_results_{label}.json"
    raw_csv = RAW_DIR / f"wnba_historical_results_{label}.csv"
    _write_json(
        raw_json,
        {
            "captured_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source": "espn_public_scoreboard_wnba",
            "dates": [d.strftime("%Y%m%d") for d in _date_range(start, end)],
            "results": result_rows,
        },
    )
    _write_csv_dicts(raw_csv, result_rows)
    return {"rows": result_rows, "raw_json": raw_json, "raw_csv": raw_csv}


def _fetch_historical_snapshot(day: date, key: str) -> dict:
    snapshot_at = f"{day.isoformat()}T{SNAPSHOT_TIME_UTC}Z"
    params = {
        "apiKey": key,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
        "date": snapshot_at,
    }
    resp = _requests_get(HISTORICAL_ODDS_URL, params=params)
    if resp.status_code != 200:
        message = ""
        try:
            body = resp.json()
            message = _safe_text(body.get("message")) if isinstance(body, dict) else ""
        except Exception:
            message = "non-json error response"
        raise RuntimeError(f"Historical WNBA odds request failed for {day}: status={resp.status_code} message={message}")
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Historical WNBA odds response for {day} was not an object.")
    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError(f"Historical WNBA odds response for {day} did not contain data list.")
    timestamp = _safe_text(payload.get("timestamp")) or snapshot_at
    snapshot_dt = _parse_utc(timestamp) or _parse_utc(snapshot_at)
    pregame_events = []
    dropped_started = 0
    for event in data:
        commence = _parse_utc(event.get("commence_time"))
        if snapshot_dt is not None and commence is not None and commence <= snapshot_dt:
            dropped_started += 1
            continue
        pregame_events.append(event)
    return {
        "captured_at_utc": timestamp,
        "requested_snapshot_utc": snapshot_at,
        "sport": "basketball_wnba",
        "source": "the_odds_api_historical",
        "provider_previous_timestamp": payload.get("previous_timestamp"),
        "provider_next_timestamp": payload.get("next_timestamp"),
        "data": pregame_events,
        "_raw_event_count": len(data),
        "_dropped_started_count": dropped_started,
    }


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NCAAM_FLAT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_csv_dicts(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for row in rows for k in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def backfill(start_date: str, end_date: str) -> dict:
    key = _api_key()
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    if end < start:
        raise SystemExit("--end-date must be on or after --start-date")

    # Include the previous month where available so early slates can use prior settled context.
    result_start = max(date(2026, 5, 5), start - timedelta(days=30))
    result_info = _fetch_results(result_start, end)
    # Clear cached result history after writing the wider ESPN result file.
    wnba_daily._RESULT_HISTORY_CACHE = None

    summaries = []
    for day in _date_range(start, end):
        snapshot = _fetch_historical_snapshot(day, key)
        raw_path = RAW_HIST_DIR / f"wnba_odds_historical_{day.isoformat()}.json"
        _write_json(raw_path, snapshot)
        flat_rows = _ncaam_flatten_snapshot(snapshot)
        flat_csv = DERIVED_HIST_DIR / f"wnba_betlines_flattened_{day.isoformat()}.csv"
        flat_json = DERIVED_HIST_DIR / f"wnba_betlines_flattened_{day.isoformat()}.json"
        _write_csv(flat_csv, flat_rows)
        _write_json(flat_json, flat_rows)
        try:
            daily_result = wnba_daily.build_wnba_daily_view(source_flat_path=flat_csv) if flat_rows else {"game_count": 0, "daily_outputs": []}
        except ValueError:
            daily_result = {"game_count": 0, "daily_outputs": []}
        summaries.append(
            {
                "date": day.isoformat(),
                "raw_path": str(raw_path),
                "flat_csv": str(flat_csv),
                "raw_events": snapshot["_raw_event_count"],
                "pregame_events": len(snapshot["data"]),
                "dropped_started": snapshot["_dropped_started_count"],
                "flat_rows": len(flat_rows),
                "daily_game_count": daily_result["game_count"],
                "daily_outputs": daily_result.get("daily_outputs", []),
            }
        )
        print(
            f"[wnba_historical_backfill] {day.isoformat()} "
            f"events={snapshot['_raw_event_count']} pregame={len(snapshot['data'])} "
            f"flat_rows={len(flat_rows)} daily_games={daily_result['game_count']}"
        )
    return {"dates": summaries, "result_info": {k: str(v) if isinstance(v, Path) else v for k, v in result_info.items() if k != "rows"}}


def main() -> None:
    today = datetime.now(UTC).date()
    default_end = today - timedelta(days=1)
    parser = argparse.ArgumentParser(description="Backfill WNBA daily predictions from real historical odds snapshots.")
    parser.add_argument("--start-date", default="2026-05-05", help="YYYY-MM-DD, default WNBA 2026 season start.")
    parser.add_argument("--end-date", default=default_end.isoformat(), help="YYYY-MM-DD, default yesterday UTC.")
    args = parser.parse_args()
    result = backfill(args.start_date, args.end_date)
    processed = len(result["dates"])
    daily_files = sum(len(item["daily_outputs"]) for item in result["dates"])
    print(f"[wnba_historical_backfill] OK dates={processed} daily_files={daily_files}")


if __name__ == "__main__":
    main()
