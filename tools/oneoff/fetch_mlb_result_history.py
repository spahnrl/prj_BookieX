"""
Fetch ESPN MLB settled result history for model features.

This writes one consolidated real-results artifact for MLB run models. It does
not create predictions, ROI, or backtest outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "mlb" / "raw"
ESPN_MLB_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"


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


def _requests_get(url: str, **kwargs):
    try:
        import certifi

        kwargs.setdefault("verify", certifi.where())
    except Exception:
        pass
    try:
        return requests.get(url, **kwargs)
    except requests.exceptions.SSLError:
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        print("[mlb_result_history] SSL retry enabled for ESPN scoreboard fetch.")
        retry_kwargs = dict(kwargs)
        retry_kwargs["verify"] = False
        return requests.get(url, **retry_kwargs)


def _date_range(start: datetime, end: datetime) -> list[str]:
    out = []
    cur = start
    while cur <= end:
        out.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return out


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
                "source_system": "espn_public_scoreboard_mlb",
            }
        )
    return rows


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for row in rows for k in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def fetch_history(start_date: str, end_date: str) -> dict:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    rows = []
    for date_str in _date_range(start, end):
        resp = _requests_get(ESPN_MLB_SCOREBOARD_URL, params={"dates": date_str, "limit": 500}, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        daily = _normalize_espn_payload(payload, date_str)
        rows.extend(daily)
        print(f"[mlb_result_history] ESPN {date_str}: events={len(payload.get('events') or [])} normalized={len(daily)}")
    deduped = {}
    for row in rows:
        key = row.get("espn_game_id") or f"{row.get('requested_date')}:{row.get('away_team')}:{row.get('home_team')}"
        deduped[key] = row
    results = list(deduped.values())
    label = f"{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
    raw_json = RAW_DIR / f"mlb_historical_results_{label}.json"
    raw_csv = RAW_DIR / f"mlb_historical_results_{label}.csv"
    _write_json(
        raw_json,
        {
            "captured_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source": "espn_public_scoreboard_mlb",
            "dates": _date_range(start, end),
            "results": results,
        },
    )
    _write_csv(raw_csv, results)
    return {"dates": len(_date_range(start, end)), "results": len(results), "raw_json": raw_json, "raw_csv": raw_csv}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch ESPN MLB settled result history for run-model features.")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    result = fetch_history(args.start_date, args.end_date)
    print("[mlb_result_history] OK")
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
