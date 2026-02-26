# =============================
# Confidence Gate Policy
# =============================
# These thresholds define when a model signal is actionable.
# They are intentionally owned by this agent to ensure
# deterministic, standalone behavior across pipelines.

MIN_SPREAD_EDGE = 1.0
MIN_TOTAL_EDGE = 3.0
MIN_PARLAY_EDGE = 4.0



def apply_confidence_gate(g: dict) -> dict:
    spread_edge = g.get("Spread Edge")
    total_edge = g.get("Total Edge")
    parlay_edge = g.get("Parlay Edge Score")

    spread_pick = g.get("Line Bet")
    total_pick = g.get("Total Bet")

    # No signals at all
    if not spread_pick and not total_pick:
        g["actionability"] = "NONE"
        g["confidence_reason"] = "No model signal"
        return g

    actionable_spread = (
        # spread_pick and spread_edge is not None and spread_edge >= MIN_SPREAD_EDGE
            spread_pick and spread_edge is not None and abs(spread_edge) >= MIN_SPREAD_EDGE
    )
    actionable_total = (
        # total_pick and total_edge is not None and total_edge >= MIN_TOTAL_EDGE
        total_pick and total_edge is not None and abs(total_edge) >= MIN_TOTAL_EDGE
    )

    if actionable_spread or actionable_total:
        g["actionability"] = "ACTION"
        g["confidence_reason"] = "Edge exceeds minimum threshold"
        return g

    # Parlay-only actionability (optional)
    if parlay_edge is not None and parlay_edge >= MIN_PARLAY_EDGE:
        g["actionability"] = "ACTION"
        g["confidence_reason"] = "Combined parlay edge exceeds threshold"
        return g

    g["actionability"] = "INFO"
    g["confidence_reason"] = "Signal present but edge below threshold"
    return g