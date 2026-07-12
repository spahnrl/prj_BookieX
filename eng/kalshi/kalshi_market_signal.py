"""Build read-only Kalshi market signal artifacts for BookieX.

This module intentionally uses Kalshi public market-data endpoints only.
No account credentials are required and no trading endpoints are called.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KALSHI_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
SPORT_KEYWORDS = {
    "nba": ("NBA", "basketball"),
    "ncaam": ("NCAAM", "NCAA", "basketball", "college basketball"),
    "wnba": ("WNBA", "basketball"),
    "mlb": ("MLB", "baseball"),
    "nhl": ("NHL", "hockey"),
}
STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "for",
    "vs",
    "versus",
    "at",
    "home",
    "away",
    "will",
    "win",
    "advance",
    "advances",
    "game",
    "match",
    "series",
}


@dataclass(frozen=True)
class BuildPaths:
    raw: Path
    normalized: Path
    matches: Path
    signal: Path


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price_probability(*values: Any) -> float | None:
    converted = [_to_float(v) for v in values]
    prices = [v for v in converted if v is not None]
    if not prices:
        return None
    if any(v > 1.0 for v in prices):
        prices = [v / 100.0 for v in prices]
    return round(sum(prices) / len(prices), 4)


def _money(value: Any) -> float | None:
    amount = _to_float(value)
    return round(amount, 4) if amount is not None else None


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {part for part in raw if len(part) > 1 and part not in STOPWORDS}


def _team_tokens(name: str) -> set[str]:
    return _tokens(name)


def _market_text(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(k) or "")
        for k in (
            "title",
            "subtitle",
            "yes_sub_title",
            "no_sub_title",
            "market_question",
            "event_name",
            "category",
        )
    )


def _paths(league: str, date: str) -> BuildPaths:
    safe_league = league.lower().strip()
    safe_date = date.strip()
    return BuildPaths(
        raw=PROJECT_ROOT / "data" / "kalshi" / "raw" / f"kalshi_markets_{safe_date}.json",
        normalized=PROJECT_ROOT / "data" / "kalshi" / "derived" / f"kalshi_market_signal_{safe_date}.json",
        matches=PROJECT_ROOT / "data" / "kalshi" / "derived" / f"kalshi_bookiex_event_matches_{safe_league}_{safe_date}.json",
        signal=PROJECT_ROOT / "data" / "kalshi" / "view" / f"kalshi_bookiex_signal_{safe_league}_{safe_date}.json",
    )


def _daily_view_path(league: str, date: str) -> Path:
    key = league.lower().strip()
    if key == "nba":
        return PROJECT_ROOT / "data" / "nba" / "daily" / f"daily_view_{date}_v1.json"
    return PROJECT_ROOT / "data" / key / "daily" / f"daily_view_{key}_{date}_v1.json"


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _get_url_json(url: str, timeout: int) -> tuple[dict[str, Any], str]:
    req = Request(url, headers={"User-Agent": "BookieX-Kalshi-Signal/1.0"})
    try:
        with urlopen(req, timeout=timeout, context=_ssl_context()) as response:
            body = response.read().decode("utf-8")
        tls_mode = "verified"
    except URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        with urlopen(req, timeout=timeout, context=ssl._create_unverified_context()) as response:
            body = response.read().decode("utf-8")
        tls_mode = "unverified_cert_fallback"
    data = json.loads(body)
    return (data if isinstance(data, dict) else {}), tls_mode


def fetch_public_markets(
    *,
    status: str = "open",
    limit: int = 1000,
    max_pages: int = 3,
    timeout: int = 30,
) -> dict[str, Any]:
    """Fetch public Kalshi markets with cursor pagination."""
    markets: list[dict[str, Any]] = []
    cursor = ""
    pages = 0
    tls_modes: set[str] = set()
    while pages < max_pages:
        params: dict[str, Any] = {"limit": limit, "status": status, "mve_filter": "exclude"}
        if cursor:
            params["cursor"] = cursor
        url = f"{KALSHI_BASE_URL}/markets?{urlencode(params)}"
        payload, tls_mode = _get_url_json(url, timeout=timeout)
        tls_modes.add(tls_mode)
        batch = payload.get("markets") or []
        if isinstance(batch, list):
            markets.extend(m for m in batch if isinstance(m, dict))
        cursor = str(payload.get("cursor") or "")
        pages += 1
        if not cursor:
            break
    return {
        "schema_version": "KALSHI_RAW_MARKETS_V1",
        "source": "kalshi_public_rest",
        "base_url": KALSHI_BASE_URL,
        "fetched_at_utc": _now_utc(),
        "request": {"status": status, "limit": limit, "max_pages": max_pages},
        "tls_mode": "mixed" if len(tls_modes) > 1 else next(iter(tls_modes), "unknown"),
        "market_count": len(markets),
        "markets": markets,
    }


def normalize_markets(raw_doc: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for market in raw_doc.get("markets") or []:
        if not isinstance(market, dict):
            continue
        yes_bid = _money(market.get("yes_bid_dollars", market.get("yes_bid")))
        yes_ask = _money(market.get("yes_ask_dollars", market.get("yes_ask")))
        last_price = _money(market.get("last_price_dollars", market.get("last_price")))
        implied_probability = _price_probability(yes_bid, yes_ask)
        price_source = "yes_bid_ask_mid"
        if implied_probability is None:
            implied_probability = _price_probability(last_price)
            price_source = "last_price"
        rows.append(
            {
                "market_id": market.get("ticker"),
                "ticker": market.get("ticker"),
                "event_ticker": market.get("event_ticker"),
                "series_ticker": market.get("series_ticker"),
                "event_name": market.get("event_title") or market.get("title"),
                "market_question": market.get("title"),
                "subtitle": market.get("subtitle"),
                "yes_sub_title": market.get("yes_sub_title"),
                "no_sub_title": market.get("no_sub_title"),
                "category": market.get("category"),
                "market_status": market.get("status"),
                "kalshi_yes_bid": yes_bid,
                "kalshi_yes_ask": yes_ask,
                "kalshi_no_bid": _money(market.get("no_bid_dollars", market.get("no_bid"))),
                "kalshi_no_ask": _money(market.get("no_ask_dollars", market.get("no_ask"))),
                "kalshi_last_price": last_price,
                "implied_probability": implied_probability,
                "probability_price_source": price_source,
                "volume": _money(market.get("volume_fp", market.get("volume"))),
                "volume_24h": _money(market.get("volume_24h_fp", market.get("volume_24h"))),
                "open_interest": _money(market.get("open_interest_fp", market.get("open_interest"))),
                "liquidity": _money(market.get("liquidity_dollars", market.get("liquidity"))),
                "open_time": market.get("open_time"),
                "close_time": market.get("close_time"),
                "expiration_time": market.get("expiration_time") or market.get("latest_expiration_time"),
                "occurrence_datetime": market.get("occurrence_datetime"),
            }
        )
    return {
        "schema_version": "KALSHI_MARKET_SIGNAL_V1",
        "source_schema_version": raw_doc.get("schema_version"),
        "generated_at_utc": _now_utc(),
        "market_count": len(rows),
        "markets": rows,
    }


def _daily_games(daily_doc: dict[str, Any]) -> list[dict[str, Any]]:
    games = daily_doc.get("games")
    return games if isinstance(games, list) else []


def _game_identity(game: dict[str, Any]) -> dict[str, Any]:
    ident = game.get("identity")
    return ident if isinstance(ident, dict) else {}


def _game_id(game: dict[str, Any]) -> str:
    ident = _game_identity(game)
    for value in (ident.get("game_id"), game.get("game_id"), game.get("espn_game_id"), game.get("game_source_id")):
        if value not in (None, ""):
            return str(value)
    return ""


def _match_game_to_market(game: dict[str, Any], markets: list[dict[str, Any]], league: str) -> dict[str, Any] | None:
    ident = _game_identity(game)
    home = str(ident.get("home_team") or game.get("home_team") or "")
    away = str(ident.get("away_team") or game.get("away_team") or "")
    if not home or not away:
        return None
    home_tokens = _team_tokens(home)
    away_tokens = _team_tokens(away)
    league_keywords = {k.lower() for k in SPORT_KEYWORDS.get(league.lower(), ())}

    best: tuple[int, dict[str, Any], str] | None = None
    for market in markets:
        text = _market_text(market)
        text_tokens = _tokens(text)
        if not text_tokens:
            continue
        home_hits = home_tokens & text_tokens
        away_hits = away_tokens & text_tokens
        league_hits = league_keywords & text_tokens
        score = 0
        reasons: list[str] = []
        if home_hits:
            score += 40
            reasons.append(f"home token match: {', '.join(sorted(home_hits))}")
        if away_hits:
            score += 40
            reasons.append(f"away token match: {', '.join(sorted(away_hits))}")
        if league_hits:
            score += 10
            reasons.append(f"league token match: {', '.join(sorted(league_hits))}")
        if home.lower() in text.lower():
            score += 20
            reasons.append("full home team string")
        if away.lower() in text.lower():
            score += 20
            reasons.append("full away team string")
        if score >= 70 and (best is None or score > best[0]):
            best = (score, market, "; ".join(reasons))
    if best is None:
        return None
    score, market, reason = best
    return {
        "bookiex_game_id": _game_id(game),
        "league": league.upper(),
        "home_team": home,
        "away_team": away,
        "kalshi_ticker": market.get("ticker"),
        "kalshi_title": market.get("market_question") or market.get("event_name"),
        "match_confidence": min(score, 100),
        "match_reason": reason,
    }


def build_matches(league: str, date: str, daily_doc: dict[str, Any], normalized_doc: dict[str, Any]) -> dict[str, Any]:
    markets = [m for m in (normalized_doc.get("markets") or []) if isinstance(m, dict)]
    rows: list[dict[str, Any]] = []
    for game in _daily_games(daily_doc):
        if not isinstance(game, dict):
            continue
        match = _match_game_to_market(game, markets, league)
        if match is not None:
            rows.append(match)
    return {
        "schema_version": "KALSHI_BOOKIEX_EVENT_MATCHES_V1",
        "league": league.lower(),
        "date": date,
        "generated_at_utc": _now_utc(),
        "daily_game_count": len(_daily_games(daily_doc)),
        "kalshi_market_count": len(markets),
        "matched_game_count": len(rows),
        "matches": rows,
    }


def _model_probability(game: dict[str, Any]) -> float | None:
    model = game.get("model_output")
    model = model if isinstance(model, dict) else {}
    for key in ("projected_probability", "win_probability", "bookiex_projected_probability"):
        value = _to_float(model.get(key))
        if value is not None:
            return value / 100.0 if value > 1.0 else value
    return None


def _signal_label(bookiex_probability: float | None, kalshi_probability: float | None, liquidity: float | None) -> str:
    if kalshi_probability is None:
        return "KALSHI_PRICE_MISSING"
    if liquidity is not None and liquidity < 100:
        return "KALSHI_TOO_ILLIQUID"
    if bookiex_probability is None:
        return "KALSHI_MATCHED_NO_BOOKIEX_PROBABILITY"
    gap = bookiex_probability - kalshi_probability
    if abs(gap) < 0.03:
        return "KALSHI_CONFIRMS_BOOKIEX"
    return "KALSHI_BELOW_BOOKIEX_FAIR" if gap > 0 else "KALSHI_ABOVE_BOOKIEX_FAIR"


def build_signal_view(
    league: str,
    date: str,
    daily_doc: dict[str, Any],
    normalized_doc: dict[str, Any],
    matches_doc: dict[str, Any],
) -> dict[str, Any]:
    markets_by_ticker = {
        str(m.get("ticker")): m for m in normalized_doc.get("markets") or [] if isinstance(m, dict) and m.get("ticker")
    }
    matches_by_game_id = {
        str(m.get("bookiex_game_id")): m for m in matches_doc.get("matches") or [] if isinstance(m, dict)
    }
    rows: list[dict[str, Any]] = []
    for game in _daily_games(daily_doc):
        if not isinstance(game, dict):
            continue
        ident = _game_identity(game)
        model = game.get("model_output")
        model = model if isinstance(model, dict) else {}
        gid = _game_id(game)
        match = matches_by_game_id.get(gid)
        market = markets_by_ticker.get(str((match or {}).get("kalshi_ticker"))) if match else None
        bookiex_prob = _model_probability(game)
        kalshi_prob = _to_float((market or {}).get("implied_probability")) if market else None
        liquidity = _to_float((market or {}).get("liquidity")) if market else None
        probability_gap = None
        if bookiex_prob is not None and kalshi_prob is not None:
            probability_gap = round(bookiex_prob - kalshi_prob, 4)
        rows.append(
            {
                "bookiex_game_id": gid,
                "league": league.upper(),
                "game_date": ident.get("game_date_local") or daily_doc.get("date") or date,
                "matchup": f"{ident.get('away_team', '')} @ {ident.get('home_team', '')}".strip(),
                "away_team": ident.get("away_team"),
                "home_team": ident.get("home_team"),
                "bookiex_pick": model.get("spread_pick") or model.get("total_pick") or model.get("pick"),
                "bookiex_confidence": model.get("confidence_tier"),
                "bookiex_projected_probability": bookiex_prob,
                "kalshi_ticker": (match or {}).get("kalshi_ticker"),
                "kalshi_title": (match or {}).get("kalshi_title"),
                "kalshi_implied_probability": kalshi_prob,
                "probability_gap": probability_gap,
                "kalshi_yes_bid": (market or {}).get("kalshi_yes_bid"),
                "kalshi_yes_ask": (market or {}).get("kalshi_yes_ask"),
                "kalshi_volume": (market or {}).get("volume"),
                "kalshi_liquidity": liquidity,
                "match_confidence": (match or {}).get("match_confidence"),
                "signal_label": _signal_label(bookiex_prob, kalshi_prob, liquidity) if match else "KALSHI_NO_MATCH",
            }
        )
    return {
        "schema_version": "KALSHI_BOOKIEX_SIGNAL_V1",
        "league": league.lower(),
        "date": date,
        "generated_at_utc": _now_utc(),
        "source": {
            "daily_view_path": str(_daily_view_path(league, date)),
            "kalshi_public_rest": KALSHI_BASE_URL,
        },
        "game_count": len(rows),
        "matched_game_count": sum(1 for r in rows if r.get("kalshi_ticker")),
        "signals": rows,
    }


def build_artifacts(
    *,
    league: str,
    date: str,
    fetch: bool,
    status: str,
    limit: int,
    max_pages: int,
    timeout: int,
) -> BuildPaths:
    paths = _paths(league, date)
    if fetch or not paths.raw.exists():
        raw_doc = fetch_public_markets(status=status, limit=limit, max_pages=max_pages, timeout=timeout)
        _write_json(paths.raw, raw_doc)
    else:
        raw_doc = _read_json(paths.raw)

    normalized_doc = normalize_markets(raw_doc)
    _write_json(paths.normalized, normalized_doc)

    daily_path = _daily_view_path(league, date)
    if not daily_path.exists():
        raise FileNotFoundError(f"Daily view not found: {daily_path}")
    daily_doc = _read_json(daily_path)
    matches_doc = build_matches(league, date, daily_doc, normalized_doc)
    _write_json(paths.matches, matches_doc)

    signal_doc = build_signal_view(league, date, daily_doc, normalized_doc, matches_doc)
    _write_json(paths.signal, signal_doc)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build BookieX Kalshi market signal artifacts.")
    parser.add_argument("--league", required=True, choices=("nba", "ncaam", "wnba", "mlb", "nhl"))
    parser.add_argument("--date", required=True, help="Daily slate date, YYYY-MM-DD.")
    parser.add_argument("--status", default="open", choices=("unopened", "open", "paused", "closed", "settled"))
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--no-fetch", action="store_true", help="Reuse existing raw Kalshi artifact if present.")
    args = parser.parse_args(argv)
    try:
        paths = build_artifacts(
            league=args.league,
            date=args.date,
            fetch=not args.no_fetch,
            status=args.status,
            limit=args.limit,
            max_pages=args.max_pages,
            timeout=args.timeout,
        )
    except Exception as exc:
        print(f"[kalshi] ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"[kalshi] raw: {paths.raw}")
    print(f"[kalshi] normalized: {paths.normalized}")
    print(f"[kalshi] matches: {paths.matches}")
    print(f"[kalshi] signal: {paths.signal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
