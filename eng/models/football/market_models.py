from __future__ import annotations

from eng.models.base_model import BaseModel


def _safe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_spread(home_line_proj, spread_home):
    if home_line_proj is None or spread_home is None:
        return ""
    if home_line_proj < spread_home:
        return "HOME"
    if home_line_proj > spread_home:
        return "AWAY"
    return ""


def _pick_total(total_projection, market_total):
    if total_projection is None or market_total is None:
        return ""
    if total_projection > market_total:
        return "OVER"
    if total_projection < market_total:
        return "UNDER"
    return ""


def _contract(model_name, home_line_proj, total_projection, spread_home, market_total, flags):
    spread_edge = None if home_line_proj is None or spread_home is None else spread_home - home_line_proj
    total_edge = None if total_projection is None or market_total is None else total_projection - market_total
    spread_distance = None if spread_edge is None else abs(spread_edge)
    total_distance = None if total_edge is None else abs(total_edge)
    return {
        "model_name": model_name,
        "total_projection": total_projection,
        "total_distance": total_distance,
        "total_edge": total_edge,
        "total_pick": _pick_total(total_projection, market_total),
        "home_line_proj": home_line_proj,
        "spread_distance": spread_distance,
        "spread_edge": spread_edge,
        "spread_pick": _pick_spread(home_line_proj, spread_home),
        "parlay_edge_score": (spread_distance or 0) + (total_distance or 0),
        "context_flags": flags,
    }


class FootballMarketConsensusModel(BaseModel):
    model_name = "Football_MarketConsensus_v1"

    def run(self, game: dict) -> dict:
        spread_home = _safe_float(game.get("spread_home_last") or game.get("spread_home"))
        total = _safe_float(game.get("total_last") or game.get("total"))
        return _contract(
            self.model_name,
            spread_home,
            total,
            spread_home,
            total,
            {"book_count": game.get("consensus_book_count"), "source": "market_consensus"},
        )


class FootballSpreadValueModel(BaseModel):
    model_name = "Football_SpreadValue_v1"
    EDGE = 0.75

    def run(self, game: dict) -> dict:
        spread_home = _safe_float(game.get("spread_home_last") or game.get("spread_home"))
        total = _safe_float(game.get("total_last") or game.get("total"))
        book_count = _safe_float(game.get("consensus_book_count")) or 0
        value_shift = 0.0
        if spread_home is not None and book_count >= 3:
            value_shift = -self.EDGE if spread_home > 0 else self.EDGE
        home_line_proj = None if spread_home is None else round(spread_home + value_shift, 3)
        return _contract(
            self.model_name,
            home_line_proj,
            total,
            spread_home,
            total,
            {"book_count": book_count, "value_shift": value_shift},
        )


class FootballTotalValueModel(BaseModel):
    model_name = "Football_TotalValue_v1"
    EDGE = 1.0

    def run(self, game: dict) -> dict:
        spread_home = _safe_float(game.get("spread_home_last") or game.get("spread_home"))
        total = _safe_float(game.get("total_last") or game.get("total"))
        book_count = _safe_float(game.get("consensus_book_count")) or 0
        projected_total = total
        if total is not None and book_count >= 3:
            projected_total = round(total + (self.EDGE if total < 45 else -self.EDGE), 3)
        return _contract(
            self.model_name,
            spread_home,
            projected_total,
            spread_home,
            total,
            {"book_count": book_count, "total_value_rule": "low_total_over_high_total_under"},
        )


class FootballLineMovementModel(BaseModel):
    model_name = "Football_LineMovement_v1"

    def run(self, game: dict) -> dict:
        spread_home = _safe_float(game.get("spread_home_last") or game.get("spread_home"))
        total = _safe_float(game.get("total_last") or game.get("total"))
        # Placeholder until opening/closing snapshots are promoted. It stays neutral but contract-valid.
        return _contract(
            self.model_name,
            spread_home,
            total,
            spread_home,
            total,
            {"movement_available": False},
        )


class FootballKeyNumberGuardModel(BaseModel):
    model_name = "Football_KeyNumberGuard_v1"
    KEY_NUMBERS = (3, 7, 10)

    def run(self, game: dict) -> dict:
        spread_home = _safe_float(game.get("spread_home_last") or game.get("spread_home"))
        total = _safe_float(game.get("total_last") or game.get("total"))
        key_risk = False
        home_line_proj = spread_home
        if spread_home is not None:
            abs_line = abs(spread_home)
            key_risk = any(abs(abs_line - key) <= 0.5 for key in self.KEY_NUMBERS)
            if key_risk:
                home_line_proj = spread_home
        return _contract(
            self.model_name,
            home_line_proj,
            total,
            spread_home,
            total,
            {"key_number_risk": key_risk, "key_numbers": list(self.KEY_NUMBERS)},
        )


class FootballMarketBlendModel(BaseModel):
    model_name = "Football_MarketBlend_v1"

    def run(self, game: dict, prior_results: dict | None = None) -> dict:
        prior_results = prior_results or {}
        spread_home = _safe_float(game.get("spread_home_last") or game.get("spread_home"))
        total = _safe_float(game.get("total_last") or game.get("total"))
        spread_models = [
            prior_results.get("Football_SpreadValue_v1", {}),
            prior_results.get("Football_LineMovement_v1", {}),
            prior_results.get("Football_KeyNumberGuard_v1", {}),
        ]
        total_models = [
            prior_results.get("Football_TotalValue_v1", {}),
            prior_results.get("Football_LineMovement_v1", {}),
        ]

        def _avg(vals):
            nums = [_safe_float(v) for v in vals]
            nums = [v for v in nums if v is not None]
            return round(sum(nums) / len(nums), 3) if nums else None

        home_line_proj = _avg([m.get("home_line_proj") for m in spread_models])
        total_projection = _avg([m.get("total_projection") for m in total_models])
        key_risk = bool((prior_results.get("Football_KeyNumberGuard_v1", {}).get("context_flags") or {}).get("key_number_risk"))
        result = _contract(
            self.model_name,
            home_line_proj,
            total_projection,
            spread_home,
            total,
            {"blend_inputs": list(prior_results), "key_number_risk": key_risk},
        )
        if key_risk and result["spread_distance"] is not None and result["spread_distance"] < 1.5:
            result["spread_pick"] = ""
            result["context_flags"]["spread_veto"] = "key_number_guard"
        return result
