from .base_model import BaseModel


class MarketPressureModel(BaseModel):
    model_name = "MarketPressure_v1"

    def run(self, game: dict) -> dict:

        base_projection = game.get("Total Projection")
        market_total = game.get("total")

        if base_projection is None:
            return {
                "model_name": self.model_name,
                "projection": None,
                "edge": None,
                "context_flags": {}
            }

        adjustment = 0.0

        if market_total is not None:
            market_gap = market_total - base_projection
            adjustment = market_gap * 0.25  # 25% controlled pull

        new_projection = base_projection + adjustment

        base_edge = game.get("Total Edge")

        if base_edge is not None:
            new_edge = base_edge + adjustment
        else:
            new_edge = None

        return {
            "model_name": self.model_name,
            "projection": new_projection,
            "edge": new_edge,
            "context_flags": {
                "market_adjustment": round(adjustment, 4)
            }
        }