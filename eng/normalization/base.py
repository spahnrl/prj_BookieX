"""Base contracts for config-driven BookieX normalizers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from eng.normalization.config import LeagueConfig


class BaseNormalizer(ABC):
    """Normalize raw provider payloads into a stable BookieX event/market shape."""

    def __init__(self, config: LeagueConfig) -> None:
        self.config = config

    @abstractmethod
    def normalize_event(
        self,
        raw_event: dict[str, Any],
        captured_at_utc: str | None = None,
    ) -> dict[str, Any]:
        """Return one canonical BookieX event record."""

    @abstractmethod
    def normalize_markets(
        self,
        raw_event: dict[str, Any],
        captured_at_utc: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return canonical BookieX market/outcome rows for one event."""

    def normalize_snapshot(
        self,
        raw_events: list[dict[str, Any]],
        captured_at_utc: str | None = None,
    ) -> dict[str, Any]:
        """Normalize a provider snapshot into event records plus flat market rows."""
        events: list[dict[str, Any]] = []
        market_rows: list[dict[str, Any]] = []

        for raw_event in raw_events:
            events.append(self.normalize_event(raw_event, captured_at_utc=captured_at_utc))
            market_rows.extend(
                self.normalize_markets(raw_event, captured_at_utc=captured_at_utc)
            )

        return {
            "source": "the_odds_api",
            "api_sport_key": self.config.api_sport_key,
            "league_key": self.config.league_key,
            "events": events,
            "market_rows": market_rows,
        }
