"""
Backfill MLB daily market-value prediction artifacts from real historical odds.

This is intentionally narrow:
- Uses The Odds API historical MLB odds endpoint.
- Writes historical raw/flat files away from the live latest artifacts.
- Builds dated MLB Daily View JSON files from those historical snapshots.
- Does not fabricate odds, picks, prices, results, ROI, or backtests.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import defaultdict
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

from eng.daily import build_mlb_daily_view as mlb_daily
from eng.pipelines.shared.e_gen_032_get_betline_flatten import (
    NCAAM_FLAT_FIELDS,
    _ncaam_flatten_snapshot,
)
from utils.io_helpers import get_daily_view_output_dir

RAW_HIST_DIR = PROJECT_ROOT / "data" / "mlb" / "raw" / "historical_odds"
DERIVED_HIST_DIR = PROJECT_ROOT / "data" / "mlb" / "derived" / "historical"
BACKUP_STAMP = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

HISTORICAL_ODDS_URL = "https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/odds"
MARKETS = "h2h,spreads,totals"
REGIONS = "us"
ODDS_FORMAT = "american"
SNAPSHOT_TIME_UTC = "16:00:00"


def _safe_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


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


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _api_key() -> str:
    if load_dotenv is not None:
        load_dotenv(PROJECT_ROOT / ".env")
    key = os.getenv("ODDS_API_KEY")
    if not key:
        raise SystemExit("ODDS_API_KEY is not available; cannot fetch historical MLB odds.")
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
        print("[mlb_historical_backfill] SSL retry enabled for historical odds fetch.")
        return requests.get(url, params=params, timeout=timeout, verify=False)


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
        raise RuntimeError(f"Historical MLB odds request failed for {day}: status={resp.status_code} message={message}")
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Historical MLB odds response for {day} was not an object.")
    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError(f"Historical MLB odds response for {day} did not contain data list.")
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
        "sport": "baseball_mlb",
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


def _backup_if_exists(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.bak_{BACKUP_STAMP}_mlb_hist")
    backup.write_bytes(path.read_bytes())
    return backup


def _build_daily_from_rows(rows: list[dict], source_flat_path: Path) -> dict:
    by_game: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        gid = _safe_text(row.get("game_id"))
        if gid:
            by_game[gid].append(row)
    games = [mlb_daily._structured_game(game_rows) for game_rows in by_game.values()]
    games.sort(key=lambda g: (g["identity"]["game_date_local"], g["identity"]["game_id"]))
    daily_dir = get_daily_view_output_dir("mlb")
    outputs = []
    backups = []
    for game_date in sorted({g["identity"]["game_date_local"] for g in games}):
        slate_games = [g for g in games if g["identity"]["game_date_local"] == game_date]
        if not slate_games:
            continue
        payload = {
            "schema_version": mlb_daily.SCHEMA_VERSION,
            "model_version": mlb_daily.MODEL_VERSION,
            "calibration_version": mlb_daily.CALIBRATION_VERSION,
            "generated_from_artifact_hash": _sha256(source_flat_path),
            "date": game_date,
            "build_timestamp_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "is_model_output": True,
            "is_roi_output": False,
            "model_warning": (
                "MLB Daily View uses a cross-book market-value model built from real historical odds. "
                "Picks mean available line value versus consensus, not mature season-long ROI confidence."
            ),
            "historical_backfill": {
                "source_flat_path": str(source_flat_path),
                "source": "the_odds_api_historical",
                "no_future_odds_policy": "Only pregame events at the historical snapshot time are included.",
            },
            "games": slate_games,
        }
        out_path = daily_dir / f"daily_view_mlb_{game_date}_v1.json"
        backup = _backup_if_exists(out_path)
        if backup:
            backups.append(str(backup))
        _write_json(out_path, payload)
        outputs.append({"date": game_date, "path": str(out_path), "games": len(slate_games)})
    return {"game_count": len(games), "outputs": outputs, "backups": backups}


def backfill(start_date: str, end_date: str) -> dict:
    key = _api_key()
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    if end < start:
        raise SystemExit("--end-date must be on or after --start-date")
    summaries = []
    for day in _date_range(start, end):
        snapshot = _fetch_historical_snapshot(day, key)
        raw_path = RAW_HIST_DIR / f"mlb_odds_historical_{day.isoformat()}.json"
        _write_json(raw_path, snapshot)
        flat_rows = _ncaam_flatten_snapshot(snapshot)
        flat_csv = DERIVED_HIST_DIR / f"mlb_betlines_flattened_{day.isoformat()}.csv"
        flat_json = DERIVED_HIST_DIR / f"mlb_betlines_flattened_{day.isoformat()}.json"
        _write_csv(flat_csv, flat_rows)
        _write_json(flat_json, flat_rows)
        daily_result = _build_daily_from_rows(flat_rows, flat_csv) if flat_rows else {"game_count": 0, "outputs": [], "backups": []}
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
                "daily_outputs": daily_result["outputs"],
                "backups": daily_result["backups"],
            }
        )
        print(
            f"[mlb_historical_backfill] {day.isoformat()} "
            f"events={snapshot['_raw_event_count']} pregame={len(snapshot['data'])} "
            f"flat_rows={len(flat_rows)} daily_games={daily_result['game_count']}"
        )
    return {"dates": summaries}


def main() -> None:
    today = datetime.now(UTC).date()
    default_end = today - timedelta(days=1)
    default_start = default_end - timedelta(days=6)
    parser = argparse.ArgumentParser(description="Backfill MLB daily predictions from real historical odds snapshots.")
    parser.add_argument("--start-date", default=default_start.isoformat(), help="YYYY-MM-DD, default seven-day sample window.")
    parser.add_argument("--end-date", default=default_end.isoformat(), help="YYYY-MM-DD, default yesterday UTC.")
    args = parser.parse_args()
    result = backfill(args.start_date, args.end_date)
    processed = len(result["dates"])
    daily_files = sum(len(item["daily_outputs"]) for item in result["dates"])
    print(f"[mlb_historical_backfill] OK dates={processed} daily_files={daily_files}")


if __name__ == "__main__":
    main()
