"""
Build a MLB prediction ledger seed from existing MLB daily model artifacts.

Scope:
- Fetch real settled MLB results from ESPN scoreboard for available daily dates.
- Join results to existing MLB daily model predictions.
- Grade spread and total picks only when the game is completed.
- Attach captured odds price from flattened Odds API rows when available.
- Write ledger/backtest seed artifacts, but do not build Pocket ROI.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DAILY_DIR = PROJECT_ROOT / "data" / "mlb" / "daily"
DERIVED_DIR = PROJECT_ROOT / "data" / "mlb" / "derived"
RAW_DIR = PROJECT_ROOT / "data" / "mlb" / "raw"
BACKTEST_DIR = PROJECT_ROOT / "data" / "mlb" / "backtests"
INTERIM_DIR = PROJECT_ROOT / "data" / "mlb" / "interim"

ESPN_MLB_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
FLAT_ODDS_PATH = DERIVED_DIR / "mlb_betlines_flattened.csv"
HISTORICAL_FLAT_DIR = DERIVED_DIR / "historical"


def _utc_now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


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


def _safe_int(value):
    text = _safe_text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _norm_team(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _safe_text(value).lower())


def _requests_get(url: str, **kwargs):
    try:
        import certifi

        kwargs.setdefault("verify", certifi.where())
    except Exception:
        pass
    try:
        return requests.get(url, **kwargs)
    except requests.exceptions.SSLError as exc:
        print(f"SSL verification failed for {url}; retrying MLB results fetch with verify=False: {exc}")
        retry_kwargs = dict(kwargs)
        retry_kwargs["verify"] = False
        return requests.get(url, **retry_kwargs)


def _daily_paths() -> list[Path]:
    return sorted(DAILY_DIR.glob("daily_view_mlb_*_v1.json"))


def _load_daily_predictions(start_date: str | None = None, end_date: str | None = None) -> tuple[list[dict], list[str]]:
    predictions: list[dict] = []
    dates: set[str] = set()
    for path in _daily_paths():
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            continue
        slate_date = _safe_text(payload.get("date"))
        if start_date and slate_date < start_date:
            continue
        if end_date and slate_date > end_date:
            continue
        games = payload.get("games") or []
        if not slate_date or not isinstance(games, list):
            continue
        dates.add(slate_date)
        for game in games:
            identity = game.get("identity") or {}
            model = game.get("model_output") or {}
            if not model.get("spread_pick") and not model.get("total_pick"):
                continue
            predictions.append(
                {
                    "source_daily_path": str(path),
                    "slate_date": slate_date,
                    "odds_game_id": _safe_text(identity.get("game_id")),
                    "home_team": _safe_text(identity.get("home_team")),
                    "away_team": _safe_text(identity.get("away_team")),
                    "market_state": game.get("market_state") or {},
                    "model_output": model,
                    "edge_metrics": game.get("edge_metrics") or {},
                    "models": game.get("models") or {},
                    "selection_authority": _safe_text((game.get("arbitration") or {}).get("selection_authority"))
                    or _safe_text(model.get("model_name"))
                    or "MLB_MarketBlend_v1",
                }
            )
    return predictions, sorted(dates)


def _date_range_from_dates(dates: list[str]) -> list[str]:
    if not dates:
        return []
    start = datetime.strptime(min(dates), "%Y-%m-%d").date()
    end = datetime.strptime(max(dates), "%Y-%m-%d").date()
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


def _fetch_results(date_list: list[str]) -> list[dict]:
    rows = []
    for date_str in date_list:
        resp = _requests_get(ESPN_MLB_SCOREBOARD_URL, params={"dates": date_str, "limit": 500}, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        daily = _normalize_espn_payload(payload, date_str)
        rows.extend(daily)
        print(f"[mlb_ledger] ESPN {date_str}: events={len(payload.get('events') or [])} normalized={len(daily)}")
    deduped = {}
    for row in rows:
        key = row.get("espn_game_id") or f"{row.get('requested_date')}:{row.get('away_team')}:{row.get('home_team')}"
        deduped[key] = row
    return list(deduped.values())


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


def _load_flat_odds() -> list[dict]:
    rows: list[dict] = []
    if FLAT_ODDS_PATH.exists():
        with FLAT_ODDS_PATH.open("r", encoding="utf-8-sig", newline="") as f:
            rows.extend(csv.DictReader(f))
    if HISTORICAL_FLAT_DIR.exists():
        for path in sorted(HISTORICAL_FLAT_DIR.glob("mlb_betlines_flattened_*.csv")):
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                rows.extend(csv.DictReader(f))
    return rows


def _find_price(flat_rows: list[dict], odds_game_id: str, market: str, outcome: str, point, book: str):
    point_f = _safe_float(point)
    book_norm = _safe_text(book).lower()
    outcome_norm = _safe_text(outcome).lower()
    candidates = []
    for row in flat_rows:
        if _safe_text(row.get("game_id")) != odds_game_id:
            continue
        if _safe_text(row.get("market_key")).lower() != market:
            continue
        if _safe_text(row.get("outcome_name")).lower() != outcome_norm:
            continue
        row_point = _safe_float(row.get("point"))
        if point_f is not None and row_point is not None and abs(row_point - point_f) > 0.001:
            continue
        row_book = (_safe_text(row.get("bookmaker_title")) or _safe_text(row.get("bookmaker_key"))).lower()
        if book_norm and row_book != book_norm:
            continue
        candidates.append(row)
    if not candidates and book_norm:
        return _find_price(flat_rows, odds_game_id, market, outcome, point, "")
    if not candidates:
        return None, "", ""
    latest = max(candidates, key=lambda r: _safe_text(r.get("captured_at_utc")))
    return _safe_float(latest.get("price")), _safe_text(latest.get("bookmaker_title") or latest.get("bookmaker_key")), _safe_text(latest.get("captured_at_utc"))


def _american_profit(price) -> float | None:
    price_f = _safe_float(price)
    if price_f is None or price_f == 0:
        return None
    if price_f > 0:
        return round(price_f / 100.0, 4)
    return round(100.0 / abs(price_f), 4)


def _grade_spread(pick_team: str, spread_home, home_team: str, away_team: str, home_score: int, away_score: int) -> str:
    spread_home_f = _safe_float(spread_home)
    if spread_home_f is None or not pick_team:
        return ""
    if _norm_team(pick_team) == _norm_team(home_team):
        margin = home_score + spread_home_f - away_score
    elif _norm_team(pick_team) == _norm_team(away_team):
        margin = away_score - spread_home_f - home_score
    else:
        return "NO_MATCH"
    if margin > 0:
        return "WIN"
    if margin < 0:
        return "LOSS"
    return "PUSH"


def _grade_total(pick: str, total_line, home_score: int, away_score: int) -> str:
    total_f = _safe_float(total_line)
    if total_f is None or not pick:
        return ""
    actual = home_score + away_score
    pick_norm = _safe_text(pick).upper()
    if actual == total_f:
        return "PUSH"
    if pick_norm == "OVER":
        return "WIN" if actual > total_f else "LOSS"
    if pick_norm == "UNDER":
        return "WIN" if actual < total_f else "LOSS"
    return "NO_MATCH"


def _unit_result(result: str, price) -> float | None:
    result = _safe_text(result).upper()
    if result == "WIN":
        return _american_profit(price)
    if result == "LOSS":
        return -1.0
    if result == "PUSH":
        return 0.0
    return None


def _match_result(pred: dict, results: list[dict]) -> tuple[dict | None, str]:
    home_key = _norm_team(pred["home_team"])
    away_key = _norm_team(pred["away_team"])
    slate_req = pred["slate_date"].replace("-", "")
    candidates = []
    for row in results:
        if _norm_team(row.get("home_team")) != home_key or _norm_team(row.get("away_team")) != away_key:
            continue
        if row.get("requested_date") == slate_req:
            candidates.append((0, row, "teams_requested_date"))
        elif row.get("game_date_utc") == pred["slate_date"]:
            candidates.append((1, row, "teams_utc_date"))
        else:
            candidates.append((2, row, "teams_only"))
    if not candidates:
        return None, "unmatched"
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1], candidates[0][2]


def _pick_price_context(model: dict, pick_type: str) -> tuple[str, object]:
    flags = model.get("context_flags") or {}
    if pick_type == "spread":
        return _safe_text(flags.get("spread_value_book")), flags.get("spread_value_line")
    return _safe_text(flags.get("total_value_book")), flags.get("total_value_line")


def _ledger_rows(predictions: list[dict], results: list[dict], flat_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    ledger = []
    audit = []
    for pred in predictions:
        result, match_mode = _match_result(pred, results)
        if not result:
            audit.append({**{k: pred[k] for k in ("slate_date", "odds_game_id", "away_team", "home_team")}, "match_status": "unmatched"})
            continue
        if not result.get("completed"):
            audit.append({**{k: pred[k] for k in ("slate_date", "odds_game_id", "away_team", "home_team")}, "match_status": "not_completed", "espn_game_id": result.get("espn_game_id"), "status": result.get("status_name")})
            continue

        home_score = result.get("home_score")
        away_score = result.get("away_score")
        if home_score is None or away_score is None:
            audit.append({**{k: pred[k] for k in ("slate_date", "odds_game_id", "away_team", "home_team")}, "match_status": "missing_score", "espn_game_id": result.get("espn_game_id")})
            continue

        market = pred["market_state"]
        model = pred["model_output"]
        edge = pred["edge_metrics"]
        selection_authority = _safe_text(pred.get("selection_authority")) or "MLB_MarketBlend_v1"
        for pick_type, pick in (("spread", model.get("spread_pick")), ("total", model.get("total_pick"))):
            pick = _safe_text(pick)
            if not pick:
                continue
            book, value_line = _pick_price_context(pred["models"].get(selection_authority) or model, pick_type)
            if pick_type == "spread":
                line = value_line if value_line not in (None, "") else market.get("spread_home_last")
                outcome = pick
                graded = _grade_spread(pick, market.get("spread_home_last"), pred["home_team"], pred["away_team"], home_score, away_score)
                edge_value = edge.get("spread_edge")
            else:
                line = value_line if value_line not in (None, "") else market.get("total_last")
                outcome = pick.upper()
                graded = _grade_total(pick, market.get("total_last"), home_score, away_score)
                edge_value = edge.get("total_edge")
            price, price_book, captured_at = _find_price(flat_rows, pred["odds_game_id"], "spreads" if pick_type == "spread" else "totals", outcome, line, book)
            ledger.append(
                {
                    "league": "mlb",
                    "slate_date": pred["slate_date"],
                    "odds_game_id": pred["odds_game_id"],
                    "espn_game_id": result.get("espn_game_id"),
                    "match_mode": match_mode,
                    "away_team": pred["away_team"],
                    "home_team": pred["home_team"],
                    "away_score": away_score,
                    "home_score": home_score,
                    "pick_type": pick_type,
                    "model_name": selection_authority,
                    "pick": pick,
                    "line": line,
                    "price": price,
                    "price_book": price_book,
                    "price_captured_at_utc": captured_at,
                    "edge": edge_value,
                    "confidence_tier": model.get("confidence_tier"),
                    "actionability": model.get("actionability"),
                    "result": graded,
                    "unit_result": _unit_result(graded, price),
                    "roi_ready": price is not None and graded in ("WIN", "LOSS", "PUSH"),
                    "source_daily_path": pred["source_daily_path"],
                }
            )
    return ledger, audit


def build_ledger(start_date: str | None = None, end_date: str | None = None) -> dict:
    if end_date is None:
        end_date = datetime.now(ZoneInfo("America/Chicago")).date().isoformat()
    predictions, dates = _load_daily_predictions(start_date, end_date)
    if not predictions:
        raise SystemExit("No MLB predictions with picks found in daily model artifacts.")
    date_list = _date_range_from_dates(dates)
    results = _fetch_results(date_list)
    flat_rows = _load_flat_odds()
    ledger, audit = _ledger_rows(predictions, results, flat_rows)

    stamp = _utc_now_stamp()
    start_label = min(dates).replace("-", "") if dates else "na"
    end_label = max(dates).replace("-", "") if dates else "na"
    raw_json = RAW_DIR / f"mlb_historical_results_{start_label}_{end_label}.json"
    raw_csv = RAW_DIR / f"mlb_historical_results_{start_label}_{end_label}.csv"
    ledger_json = BACKTEST_DIR / "mlb_prediction_ledger_seed.json"
    ledger_csv = BACKTEST_DIR / "mlb_prediction_ledger_seed.csv"
    stamped_ledger_json = BACKTEST_DIR / f"mlb_prediction_ledger_seed_{stamp}.json"
    audit_csv = INTERIM_DIR / "mlb_prediction_ledger_join_audit.csv"

    _write_json(raw_json, {"captured_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "source": "espn_public_scoreboard_mlb", "dates": date_list, "results": results})
    _write_csv(raw_csv, results)
    payload = {
        "league": "mlb",
        "artifact_type": "prediction_ledger_seed",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": "mlb_daily_model_plus_espn_results",
        "is_pocket_roi_output": False,
        "prediction_count": len(predictions),
        "graded_pick_count": len(ledger),
        "roi_ready_pick_count": sum(1 for r in ledger if r.get("roi_ready")),
        "unmatched_or_ungraded_count": len(audit),
        "ledger": ledger,
    }
    _write_json(ledger_json, payload)
    _write_json(stamped_ledger_json, payload)
    _write_csv(ledger_csv, ledger)
    _write_csv(audit_csv, audit)
    return {
        "predictions": len(predictions),
        "results": len(results),
        "graded": len(ledger),
        "roi_ready": payload["roi_ready_pick_count"],
        "audit": len(audit),
        "raw_json": raw_json,
        "ledger_json": ledger_json,
        "ledger_csv": ledger_csv,
        "audit_csv": audit_csv,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build MLB historical prediction ledger seed.")
    parser.add_argument("--start-date", help="Optional YYYY-MM-DD daily model start date.")
    parser.add_argument("--end-date", help="Optional YYYY-MM-DD daily model end date.")
    args = parser.parse_args()
    result = build_ledger(args.start_date, args.end_date)
    print("\n[mlb_ledger] OK")
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()

