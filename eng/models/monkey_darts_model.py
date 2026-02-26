import random
from .base_model import BaseModel


class MonkeyDartsModel(BaseModel):
    model_name = "MonkeyDarts_v2"

    NOISE_RANGE = 10.0

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

        # Deterministic seed per game
        seed = int(game["game_id"])
        rng = random.Random(seed)

        # Independent noise for total and spread
        total_adjustment = rng.uniform(-self.NOISE_RANGE, self.NOISE_RANGE)
        spread_adjustment = rng.uniform(-self.NOISE_RANGE, self.NOISE_RANGE)

        adjusted_total = baseline_total + total_adjustment
        adjusted_margin = baseline_margin + spread_adjustment

        # # Edges
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

        # Picks
        spread_pick = self.spread_bet(adjusted_margin, spread_home)
        total_pick = self.total_bet(adjusted_total, market_total)

        # # Parlay score
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
                "total_adjustment": round(total_adjustment, 4),
                "spread_adjustment": round(spread_adjustment, 4)
            }
        }