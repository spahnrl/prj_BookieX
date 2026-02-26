"""
confidence_engine.py

Pure confidence classification logic.

Behavior-identical to model_0052_add_model.py.

No file IO.
No JSON writing.
No side effects.
"""

def classify_game(models_dict):
    """
    Confidence classifier extracted from model_0052_add_model.py.

    Returns:
        tier (str)
        alignment (str)
        disagreement_flag (bool)
        reference_edge (float | None)
    """

    # ---------------------------------------------------------
    # Extract edges
    # ---------------------------------------------------------

    edge_map = {
        name: model.get("spread_edge")
        for name, model in models_dict.items()
    }

    baseline = edge_map.get("Joel_Baseline_v1")
    fatigue  = edge_map.get("FatiguePlus_v3")
    injury   = edge_map.get("InjuryModel_v2")

    def sign(x):
        if x is None:
            return 0
        if x > 0:
            return 1
        if x < 0:
            return -1
        return 0

    baseline_sign = sign(baseline)

    cluster_edges = [e for e in [fatigue, injury] if e is not None]
    cluster_signs = set(sign(e) for e in cluster_edges if sign(e) != 0)

    cluster_aligned = len(cluster_signs) == 1
    cluster_direction = list(cluster_signs)[0] if cluster_aligned else 0

    disagreement_flag = (
        baseline_sign != 0 and
        cluster_direction != 0 and
        baseline_sign != cluster_direction
    )

    # ---------------------------------------------------------
    # Hybrid magnitude logic
    # ---------------------------------------------------------

    edges_for_magnitude = [
        abs(e) for e in [baseline, fatigue, injury]
        if e is not None
    ]

    magnitude = max(edges_for_magnitude) if edges_for_magnitude else 0

    # ---------------------------------------------------------
    # Reference edge selection (IDENTICAL to 0052)
    # ---------------------------------------------------------

    reference_edge = None
    if edges_for_magnitude:
        if fatigue is not None and abs(fatigue) == magnitude:
            reference_edge = fatigue
        elif baseline is not None and abs(baseline) == magnitude:
            reference_edge = baseline
        else:
            reference_edge = baseline

    # ---------------------------------------------------------
    # Alignment logic (IDENTICAL to 0052)
    # ---------------------------------------------------------

    if cluster_aligned and cluster_direction != 0:
        alignment = "CLUSTER_A"
    elif baseline_sign != 0:
        alignment = "BASELINE_ONLY"
    else:
        alignment = "NONE"

    # ---------------------------------------------------------
    # Tier logic (IDENTICAL thresholds)
    # ---------------------------------------------------------

    if magnitude < 2:
        tier = "IGNORE"
    elif cluster_aligned and magnitude >= 4:
        tier = "HIGH"
    elif cluster_aligned and magnitude >= 2:
        tier = "MODERATE"
    else:
        tier = "LOW"

    return tier, alignment, disagreement_flag, reference_edge