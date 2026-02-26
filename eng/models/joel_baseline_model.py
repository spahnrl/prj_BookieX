from .base_model import BaseModel


class JoelBaselineModel(BaseModel):
    model_name = "Joel_Baseline_v1"

    @staticmethod
    def avg(a, b):
        if a is None or b is None:
            return None
        return (a + b) / 2.0

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
    def line_bet(home_line_proj, spread_home):
        if home_line_proj is None or spread_home is None:
            return None
        if home_line_proj < spread_home:
            return "HOME"
        if home_line_proj > spread_home:
            return "AWAY"
        return "PUSH"

    def run(self, game: dict) -> dict:

        haf = game.get("home_avg_points_for")
        haa = game.get("home_avg_points_against")
        aaf = game.get("away_avg_points_for")
        aaa = game.get("away_avg_points_against")

        spread_home = game.get("spread_home_last")
        market_total = game.get("total_last")

        proj_home = self.avg(haf, aaa)
        proj_away = self.avg(haa, aaf)

        if proj_home is not None and proj_away is not None:
            proj_total = proj_home + proj_away
            home_line_proj = proj_away - proj_home
        else:
            proj_total = None
            home_line_proj = None

        # ==============================
        # Edges
        # ==============================
        # spread_edge = (
        #     abs(abs(home_line_proj) - abs(spread_home))
        #     if home_line_proj is not None and spread_home is not None
        #     else None
        # )
        #
        # total_edge = (
        #     abs(proj_total - market_total)
        #     if proj_total is not None and market_total is not None
        #     else None
        # )

        # ==============================
        # SPREAD METRICS
        # ==============================

        spread_distance = (
            abs(abs(home_line_proj) - abs(spread_home))
            if home_line_proj is not None and spread_home is not None
            else None
        )

        spread_edge = (
            home_line_proj - spread_home
            if home_line_proj is not None and spread_home is not None
            else None
        )

        # ==============================
        # TOTAL METRICS
        # ==============================

        total_distance = (
            abs(proj_total - market_total)
            if proj_total is not None and market_total is not None
            else None
        )

        total_edge = (
            proj_total - market_total
            if proj_total is not None and market_total is not None
            else None
        )

        # ==============================
        # Picks
        # ==============================

        spread_pick = self.line_bet(home_line_proj, spread_home)
        ou_pick = self.total_bet(proj_total, market_total)

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

            # ---- TOTAL DOMAIN ----
            "total_projection": proj_total,
            "total_distance": total_distance,
            "total_edge": total_edge,
            "total_pick": ou_pick,

            # ---- SPREAD DOMAIN ----
            "home_line_proj": home_line_proj,
            "spread_distance": spread_distance,
            "spread_edge": spread_edge,
            "spread_pick": spread_pick,

            # ---- AGGREGATE ----
            "parlay_edge_score": parlay_edge_score,

            # ---- REQUIRED ----
            "context_flags": {
                "proj_home": proj_home,
                "proj_away": proj_away
            }
        }