"""
Build WNBA daily-view artifacts from real WNBA odds artifacts.

This creates the first WNBA model layer inside the NBA dashboard contract. It
uses a market-value model: compare the latest available bookmaker lines against
the current cross-book consensus and recommend only measurable line value. It
does not invent ROI, confidence from historical backtests, injuries, rest, or
settled-game pocket scores.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from configs.leagues.league_wnba import (
    BETLINES_FLATTENED_CSV_PATH,
    FINAL_VIEW_CSV_PATH,
    FINAL_VIEW_JSON_PATH,
    ensure_wnba_dirs,
)
from utils.io_helpers import get_daily_view_output_dir

SCHEMA_VERSION = "DAILY_VIEW_V1"
MODEL_VERSION = "WNBA_MARKET_VALUE_V1"
CALIBRATION_VERSION = "WNBA_MARKET_VALUE_NO_BACKTEST"
BASELINE_MODEL_NAME = "WNBA_MarketConsensus_v1"
SPREAD_VALUE_MODEL_NAME = "WNBA_SpreadValue_v1"
TOTAL_VALUE_MODEL_NAME = "WNBA_TotalValue_v1"
MODEL_NAME = "WNBA_MarketValueBlend_v1"
MIN_BOOKS_FOR_VALUE_PICK = 3
SPREAD_EDGE_THRESHOLD = 0.5
TOTAL_EDGE_THRESHOLD = 1.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _median(values: list[float]):
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return float(statistics.median(nums))


def _fmt_num(value):
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    if f.is_integer():
        return int(f)
    return round(f, 4)


def _parse_utc(ts: str) -> datetime | None:
    text = _safe_text(ts)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _to_central_iso(ts: str) -> str | None:
    dt = _parse_utc(ts)
    if dt is None:
        return None
    return dt.astimezone(ZoneInfo("America/Chicago")).isoformat()


def _slate_date(ts: str) -> str:
    dt = _parse_utc(ts)
    if dt is None:
        return _safe_text(ts)[:10]
    return dt.astimezone(ZoneInfo("America/Chicago")).date().isoformat()


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        hasher.update(f.read())
    return hasher.hexdigest()


def _load_flattened_rows() -> list[dict]:
    if not BETLINES_FLATTENED_CSV_PATH.exists():
        raise FileNotFoundError(f"Missing WNBA flattened odds CSV: {BETLINES_FLATTENED_CSV_PATH}")
    with BETLINES_FLATTENED_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"WNBA flattened odds CSV is empty: {BETLINES_FLATTENED_CSV_PATH}")
    return rows


def _latest_game_rows(game_rows: list[dict]) -> list[dict]:
    captured = [_safe_text(r.get("captured_at_utc")) for r in game_rows if _safe_text(r.get("captured_at_utc"))]
    if not captured:
        return game_rows
    latest = max(captured)
    latest_rows = [r for r in game_rows if _safe_text(r.get("captured_at_utc")) == latest]
    return latest_rows or game_rows


def _best_spread_value(latest_rows: list[dict], home: str, away: str, spread_home) -> dict:
    spread_home_f = _safe_float(spread_home)
    if spread_home_f is None:
        return {"pick": "", "edge": 0.0, "line": None, "book": "", "reason": "No consensus spread."}
    home_norm = home.lower()
    away_norm = away.lower()
    away_consensus = -spread_home_f
    candidates = []
    for row in latest_rows:
        if _safe_text(row.get("market_key")).lower() != "spreads":
            continue
        outcome = _safe_text(row.get("outcome_name"))
        point = _safe_float(row.get("point"))
        if point is None:
            continue
        book = _safe_text(row.get("bookmaker_title")) or _safe_text(row.get("bookmaker_key"))
        price = _safe_float(row.get("price"))
        if outcome.lower() == home_norm:
            edge = point - spread_home_f
            candidates.append({"pick": home, "edge": edge, "line": point, "book": book, "price": price})
        elif outcome.lower() == away_norm:
            edge = point - away_consensus
            candidates.append({"pick": away, "edge": edge, "line": point, "book": book, "price": price})
    if not candidates:
        return {"pick": "", "edge": 0.0, "line": None, "book": "", "reason": "No spread candidates."}
    best = max(candidates, key=lambda c: (c["edge"], c["price"] or -9999))
    if best["edge"] < SPREAD_EDGE_THRESHOLD:
        return {
            "pick": "",
            "edge": round(max(best["edge"], 0.0), 3),
            "line": _fmt_num(best["line"]),
            "book": best["book"],
            "reason": f"Best spread value is below {SPREAD_EDGE_THRESHOLD} point threshold.",
        }
    return {
        "pick": best["pick"],
        "edge": round(best["edge"], 3),
        "line": _fmt_num(best["line"]),
        "book": best["book"],
        "reason": (
            f"{best['pick']} has {best['edge']:.1f} points of spread value vs consensus "
            f"at {best['book']}."
        ),
    }


def _best_total_value(latest_rows: list[dict], total) -> dict:
    total_f = _safe_float(total)
    if total_f is None:
        return {"pick": "", "edge": 0.0, "line": None, "book": "", "reason": "No consensus total."}
    candidates = []
    for row in latest_rows:
        if _safe_text(row.get("market_key")).lower() != "totals":
            continue
        outcome = _safe_text(row.get("outcome_name")).upper()
        point = _safe_float(row.get("point"))
        if point is None:
            continue
        book = _safe_text(row.get("bookmaker_title")) or _safe_text(row.get("bookmaker_key"))
        price = _safe_float(row.get("price"))
        if outcome == "OVER":
            edge = total_f - point
            candidates.append({"pick": "OVER", "edge": edge, "line": point, "book": book, "price": price})
        elif outcome == "UNDER":
            edge = point - total_f
            candidates.append({"pick": "UNDER", "edge": edge, "line": point, "book": book, "price": price})
    if not candidates:
        return {"pick": "", "edge": 0.0, "line": None, "book": "", "reason": "No total candidates."}
    best = max(candidates, key=lambda c: (c["edge"], c["price"] or -9999))
    if best["edge"] < TOTAL_EDGE_THRESHOLD:
        return {
            "pick": "",
            "edge": round(max(best["edge"], 0.0), 3),
            "line": _fmt_num(best["line"]),
            "book": best["book"],
            "reason": f"Best total value is below {TOTAL_EDGE_THRESHOLD} point threshold.",
        }
    return {
        "pick": best["pick"],
        "edge": round(best["edge"], 3),
        "line": _fmt_num(best["line"]),
        "book": best["book"],
        "reason": (
            f"{best['pick']} has {best['edge']:.1f} points of total value vs consensus "
            f"at {best['book']}."
        ),
    }


def _confidence_from_edges(spread_edge: float, total_edge: float, book_count: int) -> tuple[str, str]:
    best_edge = max(float(spread_edge or 0), float(total_edge or 0))
    if book_count < MIN_BOOKS_FOR_VALUE_PICK:
        return "IGNORE", "Insufficient bookmaker coverage for WNBA market-value signal."
    if best_edge >= 2.0:
        return "STRONG", "Large cross-book line-value gap detected; no ROI backtest attached."
    if best_edge >= 1.0:
        return "WATCH", "Moderate cross-book line-value gap detected; no ROI backtest attached."
    if best_edge >= 0.5:
        return "LEAN", "Small cross-book line-value gap detected; no ROI backtest attached."
    return "IGNORE", "No actionable WNBA line-value gap versus consensus."


def _bookmaker_consensus(game_rows: list[dict]) -> dict:
    home = _safe_text(game_rows[0].get("home_team"))
    away = _safe_text(game_rows[0].get("away_team"))
    latest_rows = _latest_game_rows(game_rows)
    captured = sorted(_safe_text(r.get("captured_at_utc")) for r in game_rows if _safe_text(r.get("captured_at_utc")))
    book_keys = {_safe_text(r.get("bookmaker_key")) for r in game_rows if _safe_text(r.get("bookmaker_key"))}
    latest_book_keys = {_safe_text(r.get("bookmaker_key")) for r in latest_rows if _safe_text(r.get("bookmaker_key"))}

    home_spreads: list[float] = []
    away_spreads: list[float] = []
    home_spread_prices: list[float] = []
    away_spread_prices: list[float] = []
    totals: list[float] = []
    over_prices: list[float] = []
    under_prices: list[float] = []
    home_moneylines: list[float] = []
    away_moneylines: list[float] = []

    market_keys = set()
    for row in latest_rows:
        market = _safe_text(row.get("market_key")).lower()
        outcome = _safe_text(row.get("outcome_name"))
        price = _safe_float(row.get("price"))
        point = _safe_float(row.get("point"))
        if market:
            market_keys.add(market)
        if market == "spreads":
            if outcome.lower() == home.lower():
                home_spreads.append(point)
                home_spread_prices.append(price)
            elif outcome.lower() == away.lower():
                away_spreads.append(point)
                away_spread_prices.append(price)
        elif market == "totals":
            if point is not None:
                totals.append(point)
            if outcome.lower() == "over":
                over_prices.append(price)
            elif outcome.lower() == "under":
                under_prices.append(price)
        elif market == "h2h":
            if outcome.lower() == home.lower():
                home_moneylines.append(price)
            elif outcome.lower() == away.lower():
                away_moneylines.append(price)

    spread_home = _median(home_spreads)
    spread_away = _median(away_spreads)
    if spread_home is None and spread_away is not None:
        spread_home = -spread_away
    if spread_away is None and spread_home is not None:
        spread_away = -spread_home
    spread_value = _best_spread_value(latest_rows, home, away, spread_home)
    total_value = _best_total_value(latest_rows, _median(totals))

    return {
        "spread_home_last": _fmt_num(spread_home),
        "spread_away_last": _fmt_num(spread_away),
        "spread_home_price_last": _fmt_num(_median(home_spread_prices)),
        "spread_away_price_last": _fmt_num(_median(away_spread_prices)),
        "total_last": _fmt_num(_median(totals)),
        "over_price_last": _fmt_num(_median(over_prices)),
        "under_price_last": _fmt_num(_median(under_prices)),
        "moneyline_home_last": _fmt_num(_median(home_moneylines)),
        "moneyline_away_last": _fmt_num(_median(away_moneylines)),
        "consensus_book_count": len(latest_book_keys) or len(book_keys),
        "all_time_snapshot_count": len(game_rows),
        "market_count": len(market_keys),
        "odds_snapshot_last_utc": captured[-1] if captured else "",
        "spread_value": spread_value,
        "total_value": total_value,
    }


def _model_result(consensus: dict) -> dict:
    spread_home = _safe_float(consensus.get("spread_home_last"))
    total = _safe_float(consensus.get("total_last"))
    home_line_proj = spread_home
    total_projection = total
    spread_value = consensus.get("spread_value") or {}
    total_value = consensus.get("total_value") or {}
    spread_edge = float(spread_value.get("edge") or 0)
    total_edge = float(total_value.get("edge") or 0)
    book_count = int(consensus.get("consensus_book_count") or 0)
    confidence_tier, confidence_reason = _confidence_from_edges(spread_edge, total_edge, book_count)
    spread_pick = _safe_text(spread_value.get("pick"))
    total_pick = _safe_text(total_value.get("pick"))
    if not spread_pick and not total_pick:
        confidence_tier = "IGNORE"
        confidence_reason = "No WNBA line-value pick cleared the configured thresholds."
    if confidence_tier == "IGNORE":
        spread_pick = ""
        total_pick = ""
    actionability = "ACTION" if confidence_tier in ("STRONG", "WATCH") and (spread_pick or total_pick) else "NONE"
    return {
        "model_name": MODEL_NAME,
        "total_projection": total_projection,
        "total_distance": total_edge,
        "total_edge": total_edge,
        "total_pick": total_pick,
        "home_line_proj": home_line_proj,
        "spread_distance": spread_edge,
        "spread_edge": spread_edge,
        "spread_pick": spread_pick,
        "parlay_edge_score": round(spread_edge + total_edge, 3),
        "confidence_tier": confidence_tier,
        "confidence_reason": confidence_reason,
        "actionability": actionability,
        "context_flags": {
            "source": "bookmaker_consensus_value",
            "spread_value_book": spread_value.get("book", ""),
            "spread_value_line": spread_value.get("line"),
            "spread_value_reason": spread_value.get("reason", ""),
            "total_value_book": total_value.get("book", ""),
            "total_value_line": total_value.get("line"),
            "total_value_reason": total_value.get("reason", ""),
            "warning": "WNBA market-value model only; no historical ROI/backtest attached.",
        },
    }


def _structured_game(game_rows: list[dict]) -> dict:
    first = game_rows[0]
    game_id = _safe_text(first.get("game_id"))
    home = _safe_text(first.get("home_team"))
    away = _safe_text(first.get("away_team"))
    commence = _safe_text(first.get("commence_time"))
    game_date = _slate_date(commence)
    consensus = _bookmaker_consensus(game_rows)
    model = _model_result(consensus)
    tip_cst = _to_central_iso(commence)
    spread_edge = float(model.get("spread_edge") or 0)
    total_edge = float(model.get("total_edge") or 0)
    parlay_edge = float(model.get("parlay_edge_score") or 0)
    confidence_tier = _safe_text(model.get("confidence_tier")) or "IGNORE"
    confidence_reason = _safe_text(model.get("confidence_reason"))
    actionability = _safe_text(model.get("actionability")) or "NONE"
    value_flags = model.get("context_flags") or {}
    baseline_model = {
        "model_name": BASELINE_MODEL_NAME,
        "total_projection": model.get("total_projection"),
        "total_distance": 0,
        "total_edge": 0,
        "total_pick": "",
        "home_line_proj": model.get("home_line_proj"),
        "spread_distance": 0,
        "spread_edge": 0,
        "spread_pick": "",
        "parlay_edge_score": 0,
        "context_flags": {
            "source": "latest_cross_book_consensus",
            "book_count": consensus.get("consensus_book_count"),
        },
    }
    spread_model = {
        "model_name": SPREAD_VALUE_MODEL_NAME,
        "total_projection": model.get("total_projection"),
        "total_distance": 0,
        "total_edge": 0,
        "total_pick": "",
        "home_line_proj": model.get("home_line_proj"),
        "spread_distance": spread_edge,
        "spread_edge": spread_edge,
        "spread_pick": model.get("spread_pick"),
        "parlay_edge_score": spread_edge,
        "context_flags": {
            "source": "spread_line_value_vs_consensus",
            "value_book": value_flags.get("spread_value_book", ""),
            "value_line": value_flags.get("spread_value_line"),
            "reason": value_flags.get("spread_value_reason", ""),
        },
    }
    total_model = {
        "model_name": TOTAL_VALUE_MODEL_NAME,
        "total_projection": model.get("total_projection"),
        "total_distance": total_edge,
        "total_edge": total_edge,
        "total_pick": model.get("total_pick"),
        "home_line_proj": model.get("home_line_proj"),
        "spread_distance": 0,
        "spread_edge": 0,
        "spread_pick": "",
        "parlay_edge_score": total_edge,
        "context_flags": {
            "source": "total_line_value_vs_consensus",
            "value_book": value_flags.get("total_value_book", ""),
            "value_line": value_flags.get("total_value_line"),
            "reason": value_flags.get("total_value_reason", ""),
        },
    }

    return {
        "identity": {
            "game_id": game_id,
            "game_date_local": game_date,
            "home_team": home,
            "away_team": away,
            "tip_time_cst": tip_cst,
            "season_type": "WNBA",
        },
        "market_state": {
            "spread_home_last": consensus.get("spread_home_last"),
            "total_last": consensus.get("total_last"),
            "moneyline_home_last": consensus.get("moneyline_home_last"),
            "moneyline_away_last": consensus.get("moneyline_away_last"),
            "spread_home_consensus": consensus.get("spread_home_last"),
            "total_consensus": consensus.get("total_last"),
            "spread_home_consensus_all_time": consensus.get("spread_home_last"),
            "total_consensus_all_time": consensus.get("total_last"),
            "consensus_book_count": consensus.get("consensus_book_count"),
            "all_time_snapshot_count": consensus.get("all_time_snapshot_count"),
            "odds_snapshot_last_utc": consensus.get("odds_snapshot_last_utc"),
        },
        "model_output": {
            "projected_home_score": "",
            "projected_away_score": "",
            "projected_margin_home": model.get("home_line_proj"),
            "projected_total": model.get("total_projection"),
            "spread_pick": model.get("spread_pick"),
            "total_pick": model.get("total_pick"),
            "confidence_tier": confidence_tier,
            "cluster_alignment": "MARKET_VALUE" if confidence_tier != "IGNORE" else "NONE",
            "arbitration_cluster": "MARKET_VALUE" if confidence_tier != "IGNORE" else "NONE",
            "confidence_reason": confidence_reason,
            "actionability": actionability,
        },
        "edge_metrics": {
            "spread_edge": spread_edge,
            "total_edge": total_edge,
            "parlay_edge_score": parlay_edge,
            "spread_edge_percentile": min(0.99, max(0.1, spread_edge / 3.0)),
            "total_edge_percentile": min(0.99, max(0.1, total_edge / 4.0)),
        },
        "arbitration": {
            "spread": model.get("spread_pick") or None,
            "total": model.get("total_pick") or None,
            "selection_authority": MODEL_NAME,
            "reason": confidence_reason,
        },
        "models": {
            BASELINE_MODEL_NAME: baseline_model,
            SPREAD_VALUE_MODEL_NAME: spread_model,
            TOTAL_VALUE_MODEL_NAME: total_model,
            MODEL_NAME: model,
        },
        "agent_overrides": {
            "override_pick": None,
            "override_reason": None,
            "override_confidence_delta": None,
        },
        "context_flags": {
            "home_rest_days": None,
            "away_rest_days": None,
            "home_b2b_flag": None,
            "away_b2b_flag": None,
            "home_fatigue_flag": None,
            "away_fatigue_flag": None,
            "home_went_ot_last_game": None,
            "away_went_ot_last_game": None,
            "home_3pt_pct": None,
            "away_3pt_pct": None,
            "three_pt_diff": None,
            "wnba_model_status": "market_value_model_no_backtest",
            "wnba_spread_value_book": value_flags.get("spread_value_book", ""),
            "wnba_spread_value_line": value_flags.get("spread_value_line"),
            "wnba_total_value_book": value_flags.get("total_value_book", ""),
            "wnba_total_value_line": value_flags.get("total_value_line"),
        },
        "execution_overlay": {},
        "pocket_score": None,
        "pocket": None,
        "calibration_tags": {
            "edge_bucket": "2+" if max(spread_edge, total_edge) >= 2 else "1-2" if max(spread_edge, total_edge) >= 1 else "0-1",
            "historical_bucket_win_rate": None,
            "over_under_bias_flag": None,
            "favorite_dog_bias_flag": None,
            "model_regime_normal": "WNBA_MARKET_VALUE_NO_BACKTEST",
        },
        "temporal_integrity": {
            "schedule_date_utc": commence[:10],
            "tipoff_time_utc": commence,
            "tipoff_time_cst": tip_cst,
            "tipoff_local_day": game_date,
            "schedule_matches_local_day": True,
            "utc_rollover_flag": bool(commence and tip_cst and commence[:10] != tip_cst[:10]),
            "odds_commence_time_utc": commence,
            "odds_commence_time_cst": tip_cst,
        },
    }


def _final_view_row(game: dict) -> dict:
    identity = game["identity"]
    market = game["market_state"]
    model = game["model_output"]
    edge = game["edge_metrics"]
    return {
        "game_id": identity["game_id"],
        "game_date": identity["game_date_local"],
        "home_team": identity["home_team"],
        "away_team": identity["away_team"],
        "spread_home": market["spread_home_last"],
        "total": market["total_last"],
        "moneyline_home": market["moneyline_home_last"],
        "moneyline_away": market["moneyline_away_last"],
        "selection_authority": MODEL_NAME,
        "primary_model_source": MODEL_NAME,
        "Home Line Projection": model["projected_margin_home"],
        "Total Projection": model["projected_total"],
        "Line Bet": model["spread_pick"],
        "Total Bet": model["total_pick"],
        "Spread Edge": edge["spread_edge"],
        "Total Edge": edge["total_edge"],
        "Parlay Edge Score": edge["parlay_edge_score"],
        "confidence_tier": model["confidence_tier"],
        "actionability": model["actionability"],
        "odds_snapshot_last_utc": market["odds_snapshot_last_utc"],
    }


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    fields = sorted({key for row in rows for key in row.keys()})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_wnba_daily_view(date: str | None = None) -> dict:
    ensure_wnba_dirs()
    rows = _load_flattened_rows()
    by_game: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        gid = _safe_text(row.get("game_id"))
        if gid:
            by_game[gid].append(row)
    games = [_structured_game(game_rows) for game_rows in by_game.values()]
    games.sort(key=lambda g: (g["identity"]["game_date_local"], g["identity"]["game_id"]))
    if date:
        games = [g for g in games if g["identity"]["game_date_local"] == date]
    if not games:
        raise ValueError(f"No WNBA games available for date={date or 'ALL'} from {BETLINES_FLATTENED_CSV_PATH}")

    final_rows = [_final_view_row(g) for g in games]
    _write_json(FINAL_VIEW_JSON_PATH, final_rows)
    _write_csv(FINAL_VIEW_CSV_PATH, final_rows)

    daily_dir = get_daily_view_output_dir("wnba")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    outputs = []
    for game_date in sorted({g["identity"]["game_date_local"] for g in games}):
        slate_games = [g for g in games if g["identity"]["game_date_local"] == game_date]
        payload = {
            "schema_version": SCHEMA_VERSION,
            "model_version": MODEL_VERSION,
            "calibration_version": CALIBRATION_VERSION,
            "generated_from_artifact_hash": _sha256(BETLINES_FLATTENED_CSV_PATH),
            "date": game_date,
            "build_timestamp_utc": _utc_now_iso(),
            "is_model_output": True,
            "is_roi_output": False,
            "model_warning": (
                "WNBA Daily View uses a cross-book market-value model. Picks mean available line value "
                "versus consensus, not historical ROI or win-probability confidence. No WNBA ROI, pocket "
                "score, or backtest has been generated yet."
            ),
            "games": slate_games,
        }
        out_path = daily_dir / f"daily_view_wnba_{game_date}_v1.json"
        _write_json(out_path, payload)
        snapshot_path = daily_dir / "snapshots" / f"daily_view_wnba_{game_date}_v1_{timestamp}.json"
        _write_json(snapshot_path, payload)
        outputs.append({"date": game_date, "path": str(out_path), "games": len(slate_games)})
    return {
        "league": "wnba",
        "source": str(BETLINES_FLATTENED_CSV_PATH),
        "final_view_json": str(FINAL_VIEW_JSON_PATH),
        "final_view_csv": str(FINAL_VIEW_CSV_PATH),
        "daily_outputs": outputs,
        "game_count": len(games),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build WNBA NBA-contract Daily View from flattened odds.")
    parser.add_argument("--date", help="Optional slate date YYYY-MM-DD. Default builds all dates in flattened odds.")
    args = parser.parse_args()
    result = build_wnba_daily_view(args.date)
    print(
        f"[wnba_daily_view] games={result['game_count']} "
        f"daily_files={len(result['daily_outputs'])} final={result['final_view_json']}"
    )
    for item in result["daily_outputs"]:
        print(f"  {item['date']}: {item['games']} game(s) -> {item['path']}")


if __name__ == "__main__":
    main()
