# eng/models/market_blend_model.py

from eng.models.base_model import BaseModel


class MarketBlendModel(BaseModel):
    """
    Independent blended scoring model.

    Logic:
    - Uses Joel baseline projections
    - Uses Vegas implied projections
    - Blends via fixed weight (can be tuned)
    - Outputs full ModelContract_v1 schema
    """

    model_name = "MarketBlend_v1"

    # Historical inverse-error weighting
    # (You can later make this dynamic if desired)
    VEGAS_WEIGHT = 0.49
    MODEL_WEIGHT = 0.51

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

        # ---- Pull Joel baseline ----
        baseline = model_results.get("Joel_Baseline_v1", {})
        baseline_total = baseline.get("total_projection")
        baseline_margin = baseline.get("home_line_proj")

        # ---- Market implied ----
        spread_home = game.get("spread_home_last")
        market_total = game.get("total_last")

        if spread_home is None or market_total is None:
            return self._null_output()

        vegas_home = (market_total + spread_home) / 2
        vegas_away = market_total - vegas_home

        if baseline_total is None or baseline_margin is None:
            return self._null_output()

        # Convert baseline to implied scores
        model_home = (baseline_total + baseline_margin) / 2
        model_away = baseline_total - model_home

        # ---- Blend ----
        blended_home = (
            self.VEGAS_WEIGHT * vegas_home +
            self.MODEL_WEIGHT * model_home
        )

        blended_away = (
            self.VEGAS_WEIGHT * vegas_away +
            self.MODEL_WEIGHT * model_away
        )

        blended_total = blended_home + blended_away
        blended_margin = blended_away - blended_home

        # ---- Metrics ----
        spread_distance = abs(abs(blended_margin) - abs(spread_home))
        spread_edge = blended_margin - spread_home

        total_distance = abs(blended_total - market_total)
        total_edge = blended_total - market_total

        spread_pick = self.spread_bet(blended_margin, spread_home)
        total_pick = self.total_bet(blended_total, market_total)

        parlay_edge_score = spread_distance + total_distance

        return {
            "model_name": self.model_name,

            # ---- TOTAL ----
            "total_projection": blended_total,
            "total_distance": total_distance,
            "total_edge": total_edge,
            "total_pick": total_pick,

            # ---- SPREAD ----
            "home_line_proj": blended_margin,
            "spread_distance": spread_distance,
            "spread_edge": spread_edge,
            "spread_pick": spread_pick,

            # ---- AGGREGATE ----
            "parlay_edge_score": parlay_edge_score,

            # ---- REQUIRED ----
            "context_flags": {
                "vegas_home": vegas_home,
                "vegas_away": vegas_away,
                "model_home": model_home,
                "model_away": model_away,
                "weight_vegas": self.VEGAS_WEIGHT,
                "weight_model": self.MODEL_WEIGHT
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