# eng/models/market_pressure_model.py

from eng.models.base_model import BaseModel


class MarketPressureModel(BaseModel):
    """
    MarketPressure_v2

    Purpose:
    Apply controlled regression toward market total
    using Joel baseline as anchor.

    Fully ModelContract_v1 compliant.
    """

    model_name = "MarketPressure_v2"

    PULL_WEIGHT = 0.25  # 25% regression toward market

    @staticmethod
    def total_bet(proj_total, market_total):
        if proj_total is None or market_total is None:
            return None
        if proj_total > market_total:
            return "OVER"
        if proj_total < market_total:
            return "UNDER"
        return "PUSH"

    @staticmethod
    def spread_bet(home_line_proj, spread_home):
        if home_line_proj is None or spread_home is None:
            return None
        if home_line_proj < spread_home:
            return "HOME"
        if home_line_proj > spread_home:
            return "AWAY"
        return "PUSH"

    def run(self, game: dict, model_results: dict) -> dict:

        # -----------------------------
        # Pull baseline projection
        # -----------------------------
        baseline = model_results.get("Joel_Baseline_v1", {})

        baseline_total = baseline.get("total_projection")
        baseline_margin = baseline.get("home_line_proj")

        spread_home = game.get("spread_home_last")
        market_total = game.get("total_last")

        if baseline_total is None or baseline_margin is None:
            return self._null_output()

        # -----------------------------
        # Total regression
        # -----------------------------
        adjustment = 0.0

        if market_total is not None:
            market_gap = market_total - baseline_total
            adjustment = market_gap * self.PULL_WEIGHT

        adjusted_total = baseline_total + adjustment

        # Spread unchanged (pure total model)
        adjusted_margin = baseline_margin

        # -----------------------------
        # SPREAD METRICS
        # -----------------------------
        if spread_home is not None:
            spread_distance = abs(abs(adjusted_margin) - abs(spread_home))
            spread_edge = adjusted_margin - spread_home
            spread_pick = self.spread_bet(adjusted_margin, spread_home)
        else:
            spread_distance = None
            spread_edge = None
            spread_pick = None

        # -----------------------------
        # TOTAL METRICS
        # -----------------------------
        if market_total is not None:
            total_distance = abs(adjusted_total - market_total)
            total_edge = adjusted_total - market_total
            total_pick = self.total_bet(adjusted_total, market_total)
        else:
            total_distance = None
            total_edge = None
            total_pick = None

        # -----------------------------
        # Parlay score
        # -----------------------------
        parlay_edge_score = (
            (spread_distance or 0) + (total_distance or 0)
            if spread_distance is not None or total_distance is not None
            else None
        )

        return {
            "model_name": self.model_name,

            # ---- TOTAL ----
            "total_projection": adjusted_total,
            "total_distance": total_distance,
            "total_edge": total_edge,
            "total_pick": total_pick,

            # ---- SPREAD ----
            "home_line_proj": adjusted_margin,
            "spread_distance": spread_distance,
            "spread_edge": spread_edge,
            "spread_pick": spread_pick,

            # ---- AGGREGATE ----
            "parlay_edge_score": parlay_edge_score,

            # ---- REQUIRED ----
            "context_flags": {
                "baseline_total": baseline_total,
                "market_total": market_total,
                "adjustment": round(adjustment, 4),
                "pull_weight": self.PULL_WEIGHT
            }
        }

    def _null_output(self):
        return {
            "model_name": self.model_name,

            "total_projection": None,
            "total_distance": None,
            "total_edge": None,
            "total_pick": None,

            "home_line_proj": None,
            "spread_distance": None,
            "spread_edge": None,
            "spread_pick": None,

            "parlay_edge_score": None,

            "context_flags": {}
        }