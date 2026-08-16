"""
Build NFL/NCAAF daily-view artifacts from football final views.

This mirrors the newer market-value daily contract used by MLB/WNBA so the
dashboard can render football with model-backed picks instead of bridge-only
slates.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.io_helpers import get_daily_view_output_dir, get_final_view_json_path


CENTRAL = ZoneInfo("America/Chicago")


def _safe_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_float(value):
    text = _safe_text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_utc(ts: str) -> datetime | None:
    text = _safe_text(ts)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _slate_date(row: dict) -> str:
    for key in ("game_time_utc", "commence_time", "odds_commence_time_utc"):
        dt = _parse_utc(row.get(key))
        if dt:
            return dt.astimezone(CENTRAL).date().isoformat()
    return _safe_text(row.get("game_date"))[:10]


def _tip_time_cst(row: dict) -> str:
    for key in ("game_time_utc", "commence_time", "odds_commence_time_utc"):
        dt = _parse_utc(row.get(key))
        if dt:
            return dt.astimezone(CENTRAL).strftime("%Y-%m-%d %I:%M %p CT")
    return ""


def _load_final_rows(league: str) -> list[dict]:
    path = get_final_view_json_path(league)
    if not path.exists():
        raise FileNotFoundError(f"Missing final view for {league}: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and isinstance(data.get("games"), list):
        return data["games"]
    if isinstance(data, list):
        return data
    raise ValueError(f"Final view must be a list or dict with games: {path}")


def _daily_game(row: dict) -> dict:
    authority = _safe_text(row.get("selection_authority")) or "Football_MarketBlend_v1"
    models = row.get("models") if isinstance(row.get("models"), dict) else {}
    selected = models.get(authority) or {}
    spread_edge = _safe_float(row.get("Spread Edge"))
    total_edge = _safe_float(row.get("Total Edge"))
    parlay_edge = _safe_float(row.get("Parlay Edge Score"))
    return {
        "identity": {
            "game_id": _safe_text(row.get("game_id")),
            "odds_event_id": _safe_text(row.get("odds_event_id")),
            "game_date": _safe_text(row.get("game_date"))[:10],
            "slate_date": _slate_date(row),
            "tip_time_cst": _tip_time_cst(row),
            "away_team": _safe_text(row.get("away_team") or row.get("away_team_raw")),
            "home_team": _safe_text(row.get("home_team") or row.get("home_team_raw")),
            "away_team_key": _safe_text(row.get("away_team_key")),
            "home_team_key": _safe_text(row.get("home_team_key")),
            "status": _safe_text(row.get("status")),
            "completed": _safe_text(row.get("completed")),
        },
        "market_state": {
            "spread_home_last": _safe_float(row.get("spread_home")),
            "spread_away_last": _safe_float(row.get("spread_away")),
            "total_last": _safe_float(row.get("total")),
            "moneyline_home_last": _safe_float(row.get("moneyline_home")),
            "moneyline_away_last": _safe_float(row.get("moneyline_away")),
            "bookmaker_count": _safe_float(row.get("consensus_book_count")) or 0,
            "odds_snapshot_last_utc": _safe_text(row.get("odds_snapshot_last_utc")),
            "line_source": _safe_text(row.get("line_source")),
        },
        "model_output": {
            "model_name": authority,
            "spread_pick": _safe_text(row.get("Line Bet")),
            "total_pick": _safe_text(row.get("Total Bet")),
            "home_line_proj": _safe_float(row.get("Home Line Projection")),
            "total_projection": _safe_float(row.get("Total Projection")),
            "confidence_tier": _safe_text(row.get("confidence_tier")) or "IGNORE",
            "confidence_reason": _safe_text(row.get("confidence_reason")),
            "actionability": _safe_text(row.get("actionability")),
            "agent_reasoning": _safe_text(row.get("agent_reasoning")),
        },
        "edge_metrics": {
            "spread_edge": spread_edge,
            "total_edge": total_edge,
            "parlay_edge_score": parlay_edge,
        },
        "models": models,
        "execution_overlay": {
            "dual_sweet_spot": False,
            "spread_sweet_spot": bool(spread_edge is not None and abs(spread_edge) >= 1.5),
            "total_sweet_spot": bool(total_edge is not None and abs(total_edge) >= 1.5),
            "spread_avoid": False,
            "total_avoid": False,
        },
        "calibration_tags": {
            "historical_bucket_win_rate": None,
            "sample_warning": "Football seed model; backtest-regime calibration required before mature ROI claims.",
        },
        "source_row": row,
        "agent_reasoning": _safe_text(row.get("agent_reasoning")),
    }


def _write_csv(path: Path, games: list[dict]) -> None:
    rows = []
    for game in games:
        identity = game["identity"]
        market = game["market_state"]
        model = game["model_output"]
        edge = game["edge_metrics"]
        rows.append({**identity, **market, **model, **edge})
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for row in rows for k in row})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_daily_view(league: str, date_str: str | None = None) -> dict:
    league = _safe_text(league).lower()
    if league not in ("nfl", "ncaaf"):
        raise ValueError(f"Football daily view supports nfl/ncaaf only, got {league!r}")
    rows = _load_final_rows(league)
    games = [_daily_game(row) for row in rows]
    if date_str:
        games = [g for g in games if g["identity"].get("slate_date") == date_str]
    elif games:
        dates = sorted({g["identity"].get("slate_date") for g in games if g["identity"].get("slate_date")})
        today = datetime.now(CENTRAL).date().isoformat()
        future = [d for d in dates if d >= today]
        date_str = (future[0] if future else dates[-1]) if dates else today
        games = [g for g in games if g["identity"].get("slate_date") == date_str]
    else:
        date_str = date_str or datetime.now(CENTRAL).date().isoformat()

    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {
        "schema_version": "DAILY_VIEW_V1",
        "league": league,
        "date": date_str,
        "build_timestamp_utc": generated,
        "is_model_output": True,
        "is_roi_output": False,
        "model_warning": "Football market-value seed model; use backtest and agent regime artifacts for maturity checks.",
        "games": games,
    }
    out_dir = get_daily_view_output_dir(league)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"daily_view_{league}_{date_str}_v1.json"
    csv_path = out_dir / f"daily_view_{league}_{date_str}_v1.csv"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    _write_csv(csv_path, games)
    return {"json_path": json_path, "csv_path": csv_path, "game_count": len(games), "date": date_str}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build NFL/NCAAF daily view")
    parser.add_argument("--league", required=True, choices=["nfl", "ncaaf"])
    parser.add_argument("date", nargs="?", help="Slate date YYYY-MM-DD")
    args = parser.parse_args()
    result = build_daily_view(args.league, args.date)
    print(f"[football_daily] {args.league} {result['date']} games={result['game_count']} json={result['json_path']}")


if __name__ == "__main__":
    main()
