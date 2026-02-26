from .base_model import BaseModel


class BaselineModelAdapter(BaseModel):
    model_name = "Baseline_v1"

    def run(self, game: dict) -> dict:
        """
        Assumes game already contains baseline model fields.
        We simply extract and standardize them.
        """

        return {
            "model_name": self.model_name,
            "projection": game.get("Total Projection"),
            "edge": game.get("Total Edge"),
            "context_flags": {}
        }