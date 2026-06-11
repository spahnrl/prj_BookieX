"""The Odds API normalizer driven by LeagueConfig files."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from zoneinfo import ZoneInfo

from eng.normalization.base import BaseNormalizer


class OddsApiNormalizer(BaseNormalizer):
    """Normalize h2h, spread, and total odds rows from The Odds API."""

    def normalize_event(
        self,
        raw_event: dict[str, Any],
        captured_at_utc: str | None = None,
    ) -> dict[str, Any]:
        event_time_utc = _parse_utc(raw_event.get("commence_time"))
        event_time_local = event_time_utc.astimezone(ZoneInfo(self.config.timezone))
        home_team = self.canonical_team(raw_event.get("home_team"))
        away_team = self.canonical_team(raw_event.get("away_team"))

        return {
            "source": "the_odds_api",
            "api_sport_key": raw_event.get("sport_key") or self.config.api_sport_key,
            "league_key": self.config.league_key,
            "event_id": raw_event.get("id"),
            "commence_time_utc": event_time_utc.isoformat().replace("+00:00", "Z"),
            "commence_time_local": event_time_local.isoformat(),
            "event_date_local": event_time_local.date().isoformat(),
            "home_team": home_team,
            "away_team": away_team,
            "home_team_key": self.team_key(home_team),
            "away_team_key": self.team_key(away_team),
            "captured_at_utc": captured_at_utc,
        }

    def normalize_markets(
        self,
        raw_event: dict[str, Any],
        captured_at_utc: str | None = None,
    ) -> list[dict[str, Any]]:
        event = self.normalize_event(raw_event, captured_at_utc=captured_at_utc)
        rows: list[dict[str, Any]] = []

        for bookmaker in raw_event.get("bookmakers") or []:
            for market in bookmaker.get("markets") or []:
                market_key = str(market.get("key") or "")
                market_config = self.config.markets.get(market_key)
                if not market_config or not market_config.enabled:
                    continue

                for outcome in market.get("outcomes") or []:
                    raw_outcome_name = str(outcome.get("name") or "")
                    canonical_outcome = self.canonical_outcome(
                        market_key=market_key,
                        raw_outcome_name=raw_outcome_name,
                        event=event,
                    )
                    rows.append(
                        {
                            "source": "the_odds_api",
                            "api_sport_key": event["api_sport_key"],
                            "league_key": self.config.league_key,
                            "event_id": event["event_id"],
                            "event_date_local": event["event_date_local"],
                            "commence_time_utc": event["commence_time_utc"],
                            "home_team": event["home_team"],
                            "away_team": event["away_team"],
                            "bookmaker_key": bookmaker.get("key"),
                            "bookmaker_title": bookmaker.get("title"),
                            "bookmaker_last_update": bookmaker.get("last_update"),
                            "market_key": market_key,
                            "market_type": market_config.market_type,
                            "market_last_update": market.get("last_update"),
                            "outcome_name": raw_outcome_name,
                            "canonical_outcome": canonical_outcome,
                            "price": outcome.get("price"),
                            "point": outcome.get("point"),
                            "captured_at_utc": captured_at_utc,
                        }
                    )

        return rows

    def canonical_team(self, raw_name: Any) -> str:
        name = str(raw_name or "").strip()
        return self.config.team_aliases.get(_clean_key(name), name)

    def team_key(self, raw_name: Any) -> str:
        canonical_name = self.canonical_team(raw_name)
        configured_key = self.config.team_keys.get(_clean_key(canonical_name))
        if configured_key:
            return configured_key
        return re.sub(r"[^A-Z0-9]+", "_", canonical_name.upper()).strip("_")

    def canonical_outcome(
        self,
        market_key: str,
        raw_outcome_name: str,
        event: dict[str, Any],
    ) -> str:
        market_config = self.config.markets[market_key]
        configured = market_config.outcome_aliases.get(_clean_key(raw_outcome_name))
        if configured:
            return configured

        canonical_name = self.canonical_team(raw_outcome_name)
        if _clean_key(canonical_name) == _clean_key(event["home_team"]):
            return "HOME"
        if _clean_key(canonical_name) == _clean_key(event["away_team"]):
            return "AWAY"

        cleaned = _clean_key(raw_outcome_name)
        if cleaned in {"over", "o"}:
            return "OVER"
        if cleaned in {"under", "u"}:
            return "UNDER"
        if cleaned in {"draw", "tie"}:
            return "DRAW"
        return raw_outcome_name.strip().upper()


def _parse_utc(value: Any) -> datetime:
    if not value:
        raise ValueError("Odds API event is missing commence_time")
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clean_key(value: Any) -> str:
    return " ".join(str(value).strip().casefold().split())
