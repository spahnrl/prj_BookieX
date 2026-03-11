from eng.models.base_model import BaseModel


class Momentum5GameModel(BaseModel):
    """
    Momentum5Game_v1

    Projection Logic:
    Uses last 5 games per team (location agnostic)
    to generate projected home score, away score,
    total projection, and spread projection.

    Fully ModelContract_v1 compliant.
    """

    model_name = "Momentum5Game_v1"

    # ----------------------------------------
    # BET HELPERS
    # ----------------------------------------

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

    # ----------------------------------------
    # MAIN RUN
    # ----------------------------------------

    def run(self, game: dict, model_results: dict = None) -> dict:

        # Pull last 5 (location agnostic)
        H_off = game.get("home_last5_points_for")
        H_def = game.get("home_last5_points_against")
        A_off = game.get("away_last5_points_for")
        A_def = game.get("away_last5_points_against")

        spread_home = game.get("spread_home_last")
        market_total = game.get("total_last")

        # Guard clause
        if None in (H_off, H_def, A_off, A_def):
            return self._null_output()

        # ----------------------------------------
        # PROJECTED SCORES
        # ----------------------------------------

        proj_home = (H_off + A_def) / 2.0
        proj_away = (A_off + H_def) / 2.0

        proj_total = proj_home + proj_away

        # System convention:
        # home_line_proj = Away - Home
        home_line_proj = proj_away - proj_home

        # Round for stability
        proj_total = round(proj_total, 3)
        home_line_proj = round(home_line_proj, 3)

        # ----------------------------------------
        # SPREAD METRICS
        # ----------------------------------------

        if spread_home is not None:
            spread_distance = round(abs(home_line_proj - spread_home), 3)
            spread_edge = round(home_line_proj - spread_home, 3)
            spread_pick = self.spread_bet(home_line_proj, spread_home)
        else:
            spread_distance = None
            spread_edge = None
            spread_pick = None

        # ----------------------------------------
        # TOTAL METRICS
        # ----------------------------------------

        if market_total is not None:
            total_distance = round(abs(proj_total - market_total), 3)
            total_edge = round(proj_total - market_total, 3)
            total_pick = self.total_bet(proj_total, market_total)
        else:
            total_distance = None
            total_edge = None
            total_pick = None

        # ----------------------------------------
        # PARLAY EDGE SCORE
        # ----------------------------------------

        if spread_distance is not None and total_distance is not None:
            parlay_edge_score = round(spread_distance + total_distance, 3)
        elif spread_distance is not None:
            parlay_edge_score = spread_distance
        elif total_distance is not None:
            parlay_edge_score = total_distance
        else:
            parlay_edge_score = None

        # ----------------------------------------
        # RETURN CONTRACT OUTPUT
        # ----------------------------------------

        return {
            "model_name": self.model_name,

            # TOTAL
            "total_projection": proj_total,
            "total_distance": total_distance,
            "total_edge": total_edge,
            "total_pick": total_pick,

            # SPREAD
            "home_line_proj": home_line_proj,
            "spread_distance": spread_distance,
            "spread_edge": spread_edge,
            "spread_pick": spread_pick,

            # AGGREGATE
            "parlay_edge_score": parlay_edge_score,

            # REQUIRED
            "context_flags": {
                "proj_home": round(proj_home, 3),
                "proj_away": round(proj_away, 3),
                "H_off_last5": H_off,
                "H_def_last5": H_def,
                "A_off_last5": A_off,
                "A_def_last5": A_def
            }
        }

    # ----------------------------------------
    # NULL OUTPUT
    # ----------------------------------------

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