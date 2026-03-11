"""
eng/models/ncaam_momentum5_model.py

Purpose
-------
Independent NCAA last-5 momentum model.

Contract
--------
Returns the same NBA-style / NCAA multi-model contract used by the runner:

- model_name
- total_projection
- total_distance
- total_edge
- total_pick
- home_line_proj
- spread_distance
- spread_edge
- spread_pick
- parlay_edge_score
- context_flags
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class NCAAMMomentum5Model:
    model_name: str = "ncaam_momentum5_model"
    model_version: str = "v1"

    # --------------------------------------------------
    # PUBLIC API
    # --------------------------------------------------

    def run(self, game: dict, model_results=None) -> dict:
        home_last5_for = self.safe_float(game.get("home_last5_points_for"))
        home_last5_against = self.safe_float(game.get("home_last5_points_against"))
        away_last5_for = self.safe_float(game.get("away_last5_points_for"))
        away_last5_against = self.safe_float(game.get("away_last5_points_against"))

        home_last5_margin = self.safe_float(game.get("home_last5_avg_margin"))
        away_last5_margin = self.safe_float(game.get("away_last5_avg_margin"))
        home_last5_win_pct = self.safe_float(game.get("home_last5_win_pct"))
        away_last5_win_pct = self.safe_float(game.get("away_last5_win_pct"))

        market_spread_home = self.safe_float(game.get("market_spread_home"))
        market_total = self.safe_float(game.get("market_total"))

        has_projection_inputs = all(
            value is not None
            for value in [
                home_last5_for,
                home_last5_against,
                away_last5_for,
                away_last5_against,
            ]
        )

        if has_projection_inputs:
            proj_home_score = self.mean(home_last5_for, away_last5_against)
            proj_away_score = self.mean(away_last5_for, home_last5_against)

            total_projection = self.compute_total_projection(proj_home_score, proj_away_score)
            home_line_proj = self.compute_home_line_projection(proj_home_score, proj_away_score)

            total_distance = self.compute_total_distance(total_projection, market_total)
            total_edge = self.compute_total_edge(total_projection, market_total)

            spread_distance = self.compute_spread_distance(home_line_proj, market_spread_home)
            spread_edge = self.compute_spread_edge(home_line_proj, market_spread_home)

            home_team_display = (game.get("home_team_display") or "").strip()
            away_team_display = (game.get("away_team_display") or "").strip()

            total_pick = self.pick_total(total_edge)
            spread_pick = self.pick_spread(home_team_display, away_team_display, spread_edge)

            parlay_edge_score = self.compute_parlay_edge_score(spread_edge, total_edge)

            context_flags = {
                "projection_source": "last5_momentum",
                "has_projection_inputs": True,
                "home_last5_games_in_history": game.get("home_last5_games_in_history", 0),
                "away_last5_games_in_history": game.get("away_last5_games_in_history", 0),
                "home_last5_avg_margin": self.fmt_num(home_last5_margin),
                "away_last5_avg_margin": self.fmt_num(away_last5_margin),
                "home_last5_win_pct": self.fmt_num(home_last5_win_pct),
                "away_last5_win_pct": self.fmt_num(away_last5_win_pct),
                "model_version": self.model_version,
            }
        else:
            total_projection = None
            total_distance = None
            total_edge = None
            total_pick = ""

            home_line_proj = None
            spread_distance = None
            spread_edge = None
            spread_pick = ""

            parlay_edge_score = None

            context_flags = {
                "projection_source": "last5_momentum",
                "has_projection_inputs": False,
                "home_last5_games_in_history": game.get("home_last5_games_in_history", 0),
                "away_last5_games_in_history": game.get("away_last5_games_in_history", 0),
                "home_last5_avg_margin": self.fmt_num(home_last5_margin),
                "away_last5_avg_margin": self.fmt_num(away_last5_margin),
                "home_last5_win_pct": self.fmt_num(home_last5_win_pct),
                "away_last5_win_pct": self.fmt_num(away_last5_win_pct),
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
    # MATH
    # --------------------------------------------------

    @staticmethod
    def mean(a: float, b: float) -> float:
        return (a + b) / 2.0

    @staticmethod
    def compute_total_projection(proj_home_score: Optional[float], proj_away_score: Optional[float]) -> Optional[float]:
        if proj_home_score is None or proj_away_score is None:
            return None
        return proj_home_score + proj_away_score

    @staticmethod
    def compute_home_line_projection(
        proj_home_score: Optional[float],
        proj_away_score: Optional[float],
    ) -> Optional[float]:
        """
        Negative => home favored
        Positive => away favored
        """
        if proj_home_score is None or proj_away_score is None:
            return None
        return -(proj_home_score - proj_away_score)

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