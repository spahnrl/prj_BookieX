"""Registry for config-driven BookieX normalizers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from eng.normalization.config import LeagueConfig, load_league_config
from eng.normalization.odds_api import OddsApiNormalizer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "configs" / "normalization" / "leagues"


class NormalizationRegistry:
    """Map provider sport keys to configured normalizer instances."""

    def __init__(self) -> None:
        self._normalizers: dict[str, OddsApiNormalizer] = {}

    @classmethod
    def from_config_dir(
        cls,
        config_dir: str | Path = DEFAULT_CONFIG_DIR,
        active_sport_keys: Iterable[str] | None = None,
    ) -> "NormalizationRegistry":
        registry = cls()
        active = set(active_sport_keys or [])
        for config_path in sorted(Path(config_dir).glob("*.json")):
            config = load_league_config(config_path)
            if not config.enabled:
                continue
            if active and config.api_sport_key not in active:
                continue
            registry.register(config)
        return registry

    def register(self, config: LeagueConfig) -> None:
        if config.api_sport_key in self._normalizers:
            raise ValueError(f"Duplicate normalizer for {config.api_sport_key}")
        self._normalizers[config.api_sport_key] = OddsApiNormalizer(config)

    def get(self, api_sport_key: str) -> OddsApiNormalizer:
        try:
            return self._normalizers[api_sport_key]
        except KeyError as exc:
            known = ", ".join(sorted(self._normalizers)) or "none"
            raise KeyError(f"No normalizer registered for {api_sport_key}; known: {known}") from exc

    def keys(self) -> list[str]:
        return sorted(self._normalizers)

    def normalize_snapshot(
        self,
        api_sport_key: str,
        raw_events: list[dict[str, Any]],
        captured_at_utc: str | None = None,
    ) -> dict[str, Any]:
        return self.get(api_sport_key).normalize_snapshot(
            raw_events,
            captured_at_utc=captured_at_utc,
        )


def load_default_registry(
    active_sport_keys: Iterable[str] | None = None,
) -> NormalizationRegistry:
    return NormalizationRegistry.from_config_dir(
        DEFAULT_CONFIG_DIR,
        active_sport_keys=active_sport_keys,
    )
