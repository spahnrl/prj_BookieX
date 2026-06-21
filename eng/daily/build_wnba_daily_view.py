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
import re
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
MODEL_VERSION = "WNBA_MULTI_MODEL_V1"
CALIBRATION_VERSION = "WNBA_POINTS_MODEL_SEED_V1"
MARKET_CONSENSUS_MODEL_NAME = "WNBA_MarketConsensus_v1"
SPREAD_VALUE_MODEL_NAME = "WNBA_SpreadValue_v1"
TOTAL_VALUE_MODEL_NAME = "WNBA_TotalValue_v1"
MARKET_VALUE_MODEL_NAME = "WNBA_MarketValueBlend_v1"
POINTS_BASELINE_MODEL_NAME = "WNBA_PointsBaseline_v1"
LAST5_POINTS_MODEL_NAME = "WNBA_Last5Points_v1"
MARKET_PRESSURE_MODEL_NAME = "WNBA_MarketPressure_v1"
MODEL_NAME = "WNBA_MarketBlend_v1"
RESULT_HISTORY_DIR = PROJECT_ROOT / "data" / "wnba" / "raw"
MIN_BOOKS_FOR_VALUE_PICK = 3
SPREAD_EDGE_THRESHOLD = 0.5
TOTAL_EDGE_THRESHOLD = 1.0
MARKET_PRESSURE_PULL_WEIGHT = 0.25
MARKET_BLEND_MODEL_WEIGHT = 0.51
MARKET_BLEND_MARKET_WEIGHT = 0.49


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


def _norm_team(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _safe_text(value).lower())


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


def _load_result_history() -> list[dict]:
    rows_by_key: dict[str, dict] = {}
    for path in sorted(RESULT_HISTORY_DIR.glob("wnba_historical_results_*.json")):
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            continue
        for row in results:
            if not isinstance(row, dict) or not row.get("completed"):
                continue
            key = _safe_text(row.get("espn_game_id")) or (
                f"{row.get('requested_date')}:{row.get('away_team')}:{row.get('home_team')}"
            )
            rows_by_key[key] = row
    return list(rows_by_key.values())


_RESULT_HISTORY_CACHE: list[dict] | None = None


def _result_history() -> list[dict]:
    global _RESULT_HISTORY_CACHE
    if _RESULT_HISTORY_CACHE is None:
        _RESULT_HISTORY_CACHE = _load_result_history()
    return _RESULT_HISTORY_CACHE


def _history_before_date(game_date: str) -> list[dict]:
    date_key = _safe_text(game_date).replace("-", "")
    rows = []
    for row in _result_history():
        requested = _safe_text(row.get("requested_date"))
        if requested and requested < date_key:
            rows.append(row)
    rows.sort(key=lambda r: (_safe_text(r.get("requested_date")), _safe_text(r.get("espn_game_id"))))
    return rows


def _team_point_stats(team: str, history: list[dict]) -> dict:
    key = _norm_team(team)
    games = []
    for row in history:
        home = _norm_team(row.get("home_team"))
        away = _norm_team(row.get("away_team"))
        home_score = _safe_float(row.get("home_score"))
        away_score = _safe_float(row.get("away_score"))
        if home_score is None or away_score is None:
            continue
        if key == home:
            games.append({"date": _safe_text(row.get("requested_date")), "points_for": home_score, "points_against": away_score})
        elif key == away:
            games.append({"date": _safe_text(row.get("requested_date")), "points_for": away_score, "points_against": home_score})
    games.sort(key=lambda g: g["date"])
    last5 = games[-5:]
    return {
        "games": len(games),
        "avg_points_for": _median([g["points_for"] for g in games]),
        "avg_points_against": _median([g["points_against"] for g in games]),
        "last5_games": len(last5),
        "last5_points_for": _median([g["points_for"] for g in last5]),
        "last5_points_against": _median([g["points_against"] for g in last5]),
    }


def _total_bet(proj_total, market_total):
    if proj_total is None or market_total is None:
        return ""
    if proj_total > market_total:
        return "OVER"
    if proj_total < market_total:
        return "UNDER"
    return ""


def _spread_pick(home_line_proj, spread_home, home: str, away: str) -> str:
    if home_line_proj is None or spread_home is None:
        return ""
    if home_line_proj < spread_home:
        return home
    if home_line_proj > spread_home:
        return away
    return ""


def _null_model(model_name: str, context_flags: dict | None = None) -> dict:
    return {
        "model_name": model_name,
        "total_projection": None,
        "total_distance": None,
        "total_edge": None,
        "total_pick": "",
        "home_line_proj": None,
        "spread_distance": None,
        "spread_edge": None,
        "spread_pick": "",
        "parlay_edge_score": None,
        "confidence_tier": "IGNORE",
        "confidence_reason": _safe_text((context_flags or {}).get("warning")) or "Model unavailable.",
        "actionability": "NONE",
        "context_flags": context_flags or {},
    }


def _score_model(
    *,
    model_name: str,
    proj_home,
    proj_away,
    spread_home,
    market_total,
    home: str,
    away: str,
    context_flags: dict,
) -> dict:
    if proj_home is None or proj_away is None:
        return _null_model(model_name, context_flags)
    proj_total = round(float(proj_home) + float(proj_away), 3)
    home_line_proj = round(float(proj_away) - float(proj_home), 3)
    spread_pick = _spread_pick(home_line_proj, spread_home, home, away)
    total_pick = _total_bet(proj_total, market_total)
    spread_distance = abs(home_line_proj - spread_home) if spread_home is not None else None
    total_distance = abs(proj_total - market_total) if market_total is not None else None
    best_edge = max(spread_distance or 0, total_distance or 0)
    if best_edge >= 4:
        confidence_tier = "STRONG"
    elif best_edge >= 2:
        confidence_tier = "WATCH"
    elif best_edge >= 1:
        confidence_tier = "LEAN"
    else:
        confidence_tier = "IGNORE"
    if confidence_tier == "IGNORE":
        spread_pick = ""
        total_pick = ""
    return {
        "model_name": model_name,
        "total_projection": proj_total,
        "total_distance": round(total_distance, 3) if total_distance is not None else None,
        "total_edge": round(total_distance, 3) if total_distance is not None else None,
        "total_pick": total_pick,
        "home_line_proj": home_line_proj,
        "spread_distance": round(spread_distance, 3) if spread_distance is not None else None,
        "spread_edge": round(spread_distance, 3) if spread_distance is not None else None,
        "spread_pick": spread_pick,
        "parlay_edge_score": round((spread_distance or 0) + (total_distance or 0), 3),
        "confidence_tier": confidence_tier,
        "confidence_reason": (
            f"{model_name} compares point projection to current spread/total; "
            f"largest model-market gap={best_edge:.3f}."
        ),
        "actionability": "ACTION" if confidence_tier in ("STRONG", "WATCH") and (spread_pick or total_pick) else "NONE",
        "context_flags": context_flags,
    }


def _market_implied_scores(spread_home, market_total) -> tuple[float | None, float | None]:
    spread = _safe_float(spread_home)
    total = _safe_float(market_total)
    if spread is None or total is None:
        return None, None
    home_score = (total - spread) / 2.0
    away_score = total - home_score
    return home_score, away_score


def _build_point_models(home: str, away: str, game_date: str, consensus: dict) -> dict[str, dict]:
    spread_home = _safe_float(consensus.get("spread_home_last"))
    market_total = _safe_float(consensus.get("total_last"))
    history = _history_before_date(game_date)
    home_stats = _team_point_stats(home, history)
    away_stats = _team_point_stats(away, history)

    if all(home_stats.get(k) is not None for k in ("avg_points_for", "avg_points_against")) and all(
        away_stats.get(k) is not None for k in ("avg_points_for", "avg_points_against")
    ):
        baseline_home = (home_stats["avg_points_for"] + away_stats["avg_points_against"]) / 2.0
        baseline_away = (away_stats["avg_points_for"] + home_stats["avg_points_against"]) / 2.0
        baseline = _score_model(
            model_name=POINTS_BASELINE_MODEL_NAME,
            proj_home=baseline_home,
            proj_away=baseline_away,
            spread_home=spread_home,
            market_total=market_total,
            home=home,
            away=away,
            context_flags={
                "source": "espn_completed_results_before_slate",
                "home_games": home_stats["games"],
                "away_games": away_stats["games"],
                "home_avg_points_for": home_stats["avg_points_for"],
                "home_avg_points_against": home_stats["avg_points_against"],
                "away_avg_points_for": away_stats["avg_points_for"],
                "away_avg_points_against": away_stats["avg_points_against"],
            },
        )
    else:
        baseline = _null_model(
            POINTS_BASELINE_MODEL_NAME,
            {"source": "espn_completed_results_before_slate", "warning": "Insufficient season point history."},
        )

    if all(home_stats.get(k) is not None for k in ("last5_points_for", "last5_points_against")) and all(
        away_stats.get(k) is not None for k in ("last5_points_for", "last5_points_against")
    ):
        last5_home = (home_stats["last5_points_for"] + away_stats["last5_points_against"]) / 2.0
        last5_away = (away_stats["last5_points_for"] + home_stats["last5_points_against"]) / 2.0
        last5 = _score_model(
            model_name=LAST5_POINTS_MODEL_NAME,
            proj_home=last5_home,
            proj_away=last5_away,
            spread_home=spread_home,
            market_total=market_total,
            home=home,
            away=away,
            context_flags={
                "source": "espn_completed_results_before_slate",
                "home_last5_games": home_stats["last5_games"],
                "away_last5_games": away_stats["last5_games"],
                "home_last5_points_for": home_stats["last5_points_for"],
                "home_last5_points_against": home_stats["last5_points_against"],
                "away_last5_points_for": away_stats["last5_points_for"],
                "away_last5_points_against": away_stats["last5_points_against"],
            },
        )
    else:
        last5 = _null_model(
            LAST5_POINTS_MODEL_NAME,
            {"source": "espn_completed_results_before_slate", "warning": "Insufficient last-5 point history."},
        )

    base_total = _safe_float(baseline.get("total_projection"))
    base_margin = _safe_float(baseline.get("home_line_proj"))
    if base_total is not None and base_margin is not None and market_total is not None:
        adjusted_total = base_total + MARKET_PRESSURE_PULL_WEIGHT * (market_total - base_total)
        pressure_home = (adjusted_total - base_margin) / 2.0
        pressure_away = adjusted_total - pressure_home
        pressure = _score_model(
            model_name=MARKET_PRESSURE_MODEL_NAME,
            proj_home=pressure_home,
            proj_away=pressure_away,
            spread_home=spread_home,
            market_total=market_total,
            home=home,
            away=away,
            context_flags={
                "source": "points_baseline_regressed_to_market_total",
                "baseline_total": base_total,
                "market_total": market_total,
                "pull_weight": MARKET_PRESSURE_PULL_WEIGHT,
            },
        )
    else:
        pressure = _null_model(
            MARKET_PRESSURE_MODEL_NAME,
            {"source": "points_baseline_regressed_to_market_total", "warning": "Missing baseline or market total."},
        )

    market_home, market_away = _market_implied_scores(spread_home, market_total)
    if base_total is not None and base_margin is not None and market_home is not None and market_away is not None:
        base_home = (base_total - base_margin) / 2.0
        base_away = base_total - base_home
        blend_home = MARKET_BLEND_MODEL_WEIGHT * base_home + MARKET_BLEND_MARKET_WEIGHT * market_home
        blend_away = MARKET_BLEND_MODEL_WEIGHT * base_away + MARKET_BLEND_MARKET_WEIGHT * market_away
        blend = _score_model(
            model_name=MODEL_NAME,
            proj_home=blend_home,
            proj_away=blend_away,
            spread_home=spread_home,
            market_total=market_total,
            home=home,
            away=away,
            context_flags={
                "source": "points_baseline_market_blend",
                "baseline_home": round(base_home, 3),
                "baseline_away": round(base_away, 3),
                "market_home": round(market_home, 3),
                "market_away": round(market_away, 3),
                "weight_model": MARKET_BLEND_MODEL_WEIGHT,
                "weight_market": MARKET_BLEND_MARKET_WEIGHT,
            },
        )
    else:
        blend = _null_model(
            MODEL_NAME,
            {"source": "points_baseline_market_blend", "warning": "Missing baseline or market-implied scores."},
        )

    return {
        POINTS_BASELINE_MODEL_NAME: baseline,
        LAST5_POINTS_MODEL_NAME: last5,
        MARKET_PRESSURE_MODEL_NAME: pressure,
        MODEL_NAME: blend,
    }


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
        "model_name": MARKET_VALUE_MODEL_NAME,
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
    market_value_model = _model_result(consensus)
    point_models = _build_point_models(home, away, game_date, consensus)
    model = point_models.get(MODEL_NAME) or market_value_model
    if not model.get("spread_pick") and not model.get("total_pick"):
        model = market_value_model
    tip_cst = _to_central_iso(commence)
    spread_edge = float(model.get("spread_edge") or 0)
    total_edge = float(model.get("total_edge") or 0)
    parlay_edge = float(model.get("parlay_edge_score") or 0)
    confidence_tier = _safe_text(model.get("confidence_tier")) or "IGNORE"
    confidence_reason = _safe_text(model.get("confidence_reason"))
    actionability = _safe_text(model.get("actionability")) or "NONE"
    value_flags = model.get("context_flags") or {}
    baseline_model = {
        "model_name": MARKET_CONSENSUS_MODEL_NAME,
        "total_projection": consensus.get("total_last"),
        "total_distance": 0,
        "total_edge": 0,
        "total_pick": "",
        "home_line_proj": consensus.get("spread_home_last"),
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
            "projected_home_score": _fmt_num(((model.get("total_projection") or 0) - (model.get("home_line_proj") or 0)) / 2.0) if model.get("total_projection") is not None and model.get("home_line_proj") is not None else "",
            "projected_away_score": _fmt_num((model.get("total_projection") or 0) - (((model.get("total_projection") or 0) - (model.get("home_line_proj") or 0)) / 2.0)) if model.get("total_projection") is not None and model.get("home_line_proj") is not None else "",
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
            MARKET_CONSENSUS_MODEL_NAME: baseline_model,
            SPREAD_VALUE_MODEL_NAME: spread_model,
            TOTAL_VALUE_MODEL_NAME: total_model,
            MARKET_VALUE_MODEL_NAME: market_value_model,
            **point_models,
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
            "wnba_model_status": "multi_model_points_seed",
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
            "model_regime_normal": "WNBA_POINTS_MODEL_SEED_V1",
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


def build_wnba_daily_view(date: str | None = None, source_flat_path: Path | None = None) -> dict:
    ensure_wnba_dirs()
    source_flat_path = source_flat_path or BETLINES_FLATTENED_CSV_PATH
    if source_flat_path == BETLINES_FLATTENED_CSV_PATH:
        rows = _load_flattened_rows()
    else:
        if not source_flat_path.exists():
            raise FileNotFoundError(f"Missing WNBA flattened odds CSV: {source_flat_path}")
        with source_flat_path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            raise ValueError(f"WNBA flattened odds CSV is empty: {source_flat_path}")
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
            "generated_from_artifact_hash": _sha256(source_flat_path),
            "date": game_date,
            "build_timestamp_utc": _utc_now_iso(),
            "is_model_output": True,
            "is_roi_output": False,
            "model_warning": (
                "WNBA Daily View uses seed point-history and market-value models. Picks are limited-sample "
                "model-market signals, not mature historical ROI or production betting authority."
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
        "source": str(source_flat_path),
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
