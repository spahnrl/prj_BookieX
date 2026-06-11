"""League config loading for BookieX normalization."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MarketConfig:
    key: str
    market_type: str
    enabled: bool = True
    outcome_aliases: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, key: str, raw: dict[str, Any]) -> "MarketConfig":
        return cls(
            key=key,
            market_type=str(raw.get("market_type", key)),
            enabled=bool(raw.get("enabled", True)),
            outcome_aliases={
                _clean_key(k): str(v) for k, v in raw.get("outcome_aliases", {}).items()
            },
        )


@dataclass(frozen=True)
class LeagueConfig:
    api_sport_key: str
    league_key: str
    display_name: str
    timezone: str
    enabled: bool = True
    default_region: str = "us"
    odds_format: str = "american"
    markets: dict[str, MarketConfig] = field(default_factory=dict)
    team_aliases: dict[str, str] = field(default_factory=dict)
    team_keys: dict[str, str] = field(default_factory=dict)
    schema_version: str = "1"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "LeagueConfig":
        missing = [
            field_name
            for field_name in ("api_sport_key", "league_key", "display_name", "timezone")
            if not raw.get(field_name)
        ]
        if missing:
            raise ValueError(f"League config missing required fields: {', '.join(missing)}")

        raw_markets = raw.get("markets") or {}
        markets = {
            key: MarketConfig.from_dict(key, value)
            for key, value in raw_markets.items()
            if isinstance(value, dict)
        }

        team_mappings = raw.get("team_mappings") or {}
        aliases = {
            _clean_key(k): str(v)
            for k, v in (team_mappings.get("aliases") or {}).items()
        }
        keys = {
            _clean_key(k): str(v)
            for k, v in (team_mappings.get("keys") or {}).items()
        }

        return cls(
            api_sport_key=str(raw["api_sport_key"]),
            league_key=str(raw["league_key"]),
            display_name=str(raw["display_name"]),
            timezone=str(raw["timezone"]),
            enabled=bool(raw.get("enabled", True)),
            default_region=str(raw.get("default_region", "us")),
            odds_format=str(raw.get("odds_format", "american")),
            markets=markets,
            team_aliases=aliases,
            team_keys=keys,
            schema_version=str(raw.get("schema_version", "1")),
        )


def load_league_config(path: str | Path) -> LeagueConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return LeagueConfig.from_dict(raw)


def _clean_key(value: Any) -> str:
    return " ".join(str(value).strip().casefold().split())
