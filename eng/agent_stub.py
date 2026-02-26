# prj_BookieX/eng/agent_stub.py

TIGHT_SPREAD_EDGE = 1.0
TIGHT_TOTAL_EDGE = 2.0

def agent_stub_overrides(g: dict) -> dict:
    g["agent_override_pick"] = None
    g["agent_override_reason"] = None
    g["agent_override_confidence_delta"] = None

    # Only consider ACTION or INFO
    if g.get("actionability") not in ("ACTION", "INFO"):
        return g

    spread_edge = g.get("Spread Edge")
    total_edge = g.get("Total Edge")

    # Example heuristic: tight totals only
    if (
        g.get("Total Bet")
        and total_edge is not None
        and total_edge <= TIGHT_TOTAL_EDGE
    ):
        g["agent_override_pick"] = (
            "UNDER" if g.get("Total Bet") == "OVER" else "OVER"
        )
        g["agent_override_reason"] = (
            "Tight total edge; recent shooting volatility suggests caution"
        )
        g["agent_override_confidence_delta"] = -0.5

    return g