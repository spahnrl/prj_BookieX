from .base_model import BaseModel


class FatiguePlusModel(BaseModel):
    model_name = "FatiguePlus_v3"

    SPREAD_WEIGHT = 1.75
    TOTAL_DIRECTIONAL_WEIGHT = 0.9
    TOTAL_PACE_WEIGHT = 0.6

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

        baseline = model_results.get("Joel_Baseline_v1", {})

        baseline_total = baseline.get("total_projection")
        baseline_margin = baseline.get("home_line_proj")

        spread_home = game.get("spread_home_last")
        market_total = game.get("total_last")

        fatigue_diff = game.get("fatigue_diff_home_minus_away", 0.0)
        home_fatigue = game.get("home_fatigue_score", 0.0)
        away_fatigue = game.get("away_fatigue_score", 0.0)

        if baseline_total is None or baseline_margin is None:
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
        # ==============================
        # Spread Adjustment
        # ==============================

        spread_adjustment = self.SPREAD_WEIGHT * fatigue_diff
        adjusted_margin = baseline_margin + spread_adjustment

        # ==============================
        # Total Adjustment
        # ==============================

        abs_total_fatigue = home_fatigue + away_fatigue

        directional_total_adjustment = (
            -self.TOTAL_DIRECTIONAL_WEIGHT * abs(fatigue_diff)
        )

        pace_adjustment = (
            -self.TOTAL_PACE_WEIGHT * abs_total_fatigue
        )

        total_adjustment = directional_total_adjustment + pace_adjustment
        adjusted_total = baseline_total + total_adjustment

        # ==============================
        # Edges
        # ==============================

        # spread_edge = (
        #     abs(abs(adjusted_margin) - abs(spread_home))
        #     if spread_home is not None
        #     else None
        # )
        #
        # total_edge = (
        #     abs(adjusted_total - market_total)
        #     if market_total is not None
        #     else None
        # )
        # ==============================
        # SPREAD METRICS
        # ==============================

        spread_distance = (
            abs(abs(adjusted_margin) - abs(spread_home))
            if spread_home is not None
            else None
        )

        spread_edge = (
            adjusted_margin - spread_home
            if spread_home is not None
            else None
        )

        # ==============================
        # TOTAL METRICS
        # ==============================

        total_distance = (
            abs(adjusted_total - market_total)
            if market_total is not None
            else None
        )

        total_edge = (
            adjusted_total - market_total
            if market_total is not None
            else None
        )

        # ==============================
        # Picks
        # ==============================

        spread_pick = self.spread_bet(adjusted_margin, spread_home)
        total_pick = self.total_bet(adjusted_total, market_total)

        # ==============================
        # Parlay Score
        # ==============================

        # parlay_edge_score = (
        #     (spread_edge or 0) + (total_edge or 0)
        #     if spread_edge is not None or total_edge is not None
        #     else None
        # )
        parlay_edge_score = (
            (spread_distance or 0) + (total_distance or 0)
            if spread_distance is not None or total_distance is not None
            else None
        )

        return {
            "model_name": self.model_name,

            "total_projection": adjusted_total,
            "total_distance": total_distance,
            "total_edge": total_edge,
            "total_pick": total_pick,

            "home_line_proj": adjusted_margin,
            "spread_distance": spread_distance,
            "spread_edge": spread_edge,
            "spread_pick": spread_pick,

            "parlay_edge_score": parlay_edge_score,

            "context_flags": {
                "fatigue_diff": fatigue_diff,
                "spread_adjustment": spread_adjustment,
                "total_adjustment": total_adjustment,
                "home_fatigue": home_fatigue,
                "away_fatigue": away_fatigue
            }
        }