def build_decision_explanation(game: dict) -> dict:
    """
    Builds explanation based on the authoritative model selection.
    Future-proof for multi-model arbitration evolution.
    """

    model_name = game.get("selection_authority")
    models = game.get("models", {})
    model = models.get(model_name, {}) if model_name else {}

    spread_pick = model.get("spread_pick")
    total_pick = model.get("total_pick")

    # No actionable signal
    if not spread_pick and not total_pick:
        return {
            "decision_explanation": None,
            "decision_factors": {}
        }

    lines = []

    lines.append(
        f"Game: {game.get('away_team')} @ {game.get('home_team')}"
    )

    lines.append(
        f"Authority: {model_name}"
    )

    lines.append(
        f"Market: Spread {game.get('spread_home')} / {game.get('spread_away')}, "
        f"Total {game.get('total')}"
    )

    projected_margin = model.get("home_line_proj")
    projected_total = model.get("total_projection")

    lines.append(
        f"Model Projection: "
        f"Margin {projected_margin}, "
        f"Total {projected_total}"
    )

    if spread_pick:
        lines.append(
            f"Spread Pick: {spread_pick} "
            f"(edge {model.get('spread_edge')})"
        )

    if total_pick:
        lines.append(
            f"Total Pick: {total_pick} "
            f"(edge {model.get('total_edge')})"
        )

    explanation = "\n".join(lines)

    factors = {
        "model_name": model_name,
        "spread_edge": model.get("spread_edge"),
        "total_edge": model.get("total_edge"),
        "projected_margin": projected_margin,
        "projected_total": projected_total,
    }

    return {
        "decision_explanation": explanation,
        "decision_factors": factors
    }