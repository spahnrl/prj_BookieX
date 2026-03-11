"""
eng/models/ncaam_market_pressure_model.py

Purpose
-------
Independent NCAA market-pressure model.

Design
------
- Uses the authoritative NCAA baseline model as its source projection
- Applies a conservative pull of the baseline TOTAL toward the market total
- Keeps spread projection unchanged for MVP
- Returns the same contract as other NCAA models

Notes
-----
This is a controlled NCAA adaptation of the NBA market-pressure idea.
It assumes the baseline model has already run and is available in model_results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class NCAAMMarketPressureModel:
    model_name: str = "ncaam_market_pressure_model"
    model_version: str = "v1"

    # NCAA authoritative baseline for now
    baseline_model_name: str = "ncaam_avg_score_model"

    # Pull total projection toward market
    total_pull_weight: float = 0.25

    # --------------------------------------------------
    # PUBLIC API
    # --------------------------------------------------

    def run(self, game: dict, model_results=None) -> dict:
        model_results = model_results or {}

        baseline = model_results.get(self.baseline_model_name, {})

        baseline_total = self.safe_float(baseline.get("total_projection"))
        baseline_home_line = self.safe_float(baseline.get("home_line_proj"))

        market_total = self.safe_float(game.get("market_total"))
        market_spread_home = self.safe_float(game.get("market_spread_home"))

        has_baseline = baseline_total is not None or baseline_home_line is not None

        if baseline_total is not None and market_total is not None:
            total_projection = self.blend_total_toward_market(
                baseline_total=baseline_total,
                market_total=market_total,
                pull_weight=self.total_pull_weight,
            )
            total_distance = self.compute_total_distance(total_projection, market_total)
            total_edge = self.compute_total_edge(total_projection, market_total)
            total_pick = self.pick_total(total_edge)
        else:
            total_projection = None
            total_distance = None
            total_edge = None
            total_pick = ""

        # MVP rule: carry forward baseline spread unchanged
        if baseline_home_line is not None and market_spread_home is not None:
            home_line_proj = baseline_home_line
            spread_distance = self.compute_spread_distance(home_line_proj, market_spread_home)
            spread_edge = self.compute_spread_edge(home_line_proj, market_spread_home)

            home_team_display = (game.get("home_team_display") or "").strip()
            away_team_display = (game.get("away_team_display") or "").strip()
            spread_pick = self.pick_spread(home_team_display, away_team_display, spread_edge)
        else:
            home_line_proj = None
            spread_distance = None
            spread_edge = None
            spread_pick = ""

        parlay_edge_score = self.compute_parlay_edge_score(spread_edge, total_edge)

        context_flags = {
            "projection_source": "market_pressure",
            "baseline_model_name": self.baseline_model_name,
            "has_baseline": has_baseline,
            "total_pull_weight": self.total_pull_weight,
            "spread_logic": "carry_forward_baseline",
            "model_version": self.model_version,
        }

        return {
            "model_name": self.model_name,

            # TOTAL
            "total_projection": self.fmt_num(total_projection),
            "total_distance": self.fmt_num(total_distance),
            "total_edge": self.fmt_num(total_edge),
            "total_pick": total_pick,

            # SPREAD
            "home_line_proj": self.fmt_num(home_line_proj),
            "spread_distance": self.fmt_num(spread_distance),
            "spread_edge": self.fmt_num(spread_edge),
            "spread_pick": spread_pick,

            # AGGREGATE
            "parlay_edge_score": self.fmt_num(parlay_edge_score),

            # REQUIRED
            "context_flags": context_flags,
        }

    # --------------------------------------------------
    # CORE LOGIC
    # --------------------------------------------------

    @staticmethod
    def blend_total_toward_market(
        baseline_total: float,
        market_total: float,
        pull_weight: float,
    ) -> float:
        """
        Example:
          pull_weight = 0.25
          new_total = 75% baseline + 25% market
        """
        return (baseline_total * (1.0 - pull_weight)) + (market_total * pull_weight)

    # --------------------------------------------------
    # MATH
    # --------------------------------------------------

    @staticmethod
    def compute_total_distance(total_projection: Optional[float], market_total: Optional[float]) -> Optional[float]:
        if total_projection is None or market_total is None:
            return None
        return abs(total_projection - market_total)

    @staticmethod
    def compute_total_edge(total_projection: Optional[float], market_total: Optional[float]) -> Optional[float]:
        if total_projection is None or market_total is None:
            return None
        return total_projection - market_total

    @staticmethod
    def compute_spread_distance(home_line_proj: Optional[float], market_spread_home: Optional[float]) -> Optional[float]:
        if home_line_proj is None or market_spread_home is None:
            return None
        return abs(home_line_proj - market_spread_home)

    @staticmethod
    def compute_spread_edge(home_line_proj: Optional[float], market_spread_home: Optional[float]) -> Optional[float]:
        if home_line_proj is None or market_spread_home is None:
            return None
        return home_line_proj - market_spread_home

    @staticmethod
    def compute_parlay_edge_score(spread_edge: Optional[float], total_edge: Optional[float]) -> Optional[float]:
        values = []
        if spread_edge is not None:
            values.append(abs(spread_edge))
        if total_edge is not None:
            values.append(abs(total_edge))
        if not values:
            return None
        return sum(values)

    # --------------------------------------------------
    # PICKS
    # --------------------------------------------------

    @staticmethod
    def pick_spread(home_team_display: str, away_team_display: str, spread_edge: Optional[float]) -> str:
        if spread_edge is None:
            return ""
        if spread_edge < 0:
            return home_team_display or "HOME"
        if spread_edge > 0:
            return away_team_display or "AWAY"
        return "PUSH"

    @staticmethod
    def pick_total(total_edge: Optional[float]) -> str:
        if total_edge is None:
            return ""
        if total_edge > 0:
            return "OVER"
        if total_edge < 0:
            return "UNDER"
        return "PUSH"

    # --------------------------------------------------
    # HELPERS
    # --------------------------------------------------

    @staticmethod
    def safe_float(value) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def fmt_num(value: Optional[float]) -> str:
        if value is None:
            return ""
        if float(value).is_integer():
            return str(int(value))
        return str(round(value, 4))