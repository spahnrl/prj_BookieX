class BaseModel:
    model_name: str = "BASE"

    def run(self, game: dict) -> dict:
        """
        Input:
            Immutable game-level dict.

        Returns:
            {
                "model_name": str,
                "projection": float,
                "edge": float,
                "context_flags": dict (optional)
            }
        """
        raise NotImplementedError