"""
model_0052_add_model.py

FINALIZATION LAYER

Reads multi-model artifact and finalizes game view.
No projection math is computed here.

RULES ENFORCED:
- No filtering
- No removal of rows
- All games retained
- Additive only
- Deterministic structure preserved
"""

import json
import csv
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# AGENT BUILD IMPORTS
from eng.decision_explainer import build_decision_explanation
from eng.eval_sanity import summarize_actions
from eng.agent_stub import agent_stub_overrides
from eng.arbitration.confidence_engine import classify_game
from eng.arbitration.confidence_gate import apply_confidence_gate


# =============================
# PATHS
# =============================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VIEW_DIR = PROJECT_ROOT / "data/view"

IN_JSON = VIEW_DIR / "nba_games_multi_model_v1.json"
OUT_JSON = VIEW_DIR / "final_game_view.json"
OUT_CSV  = VIEW_DIR / "final_game_view.csv"


# =============================
# HELPERS
# =============================

def utc_to_cst(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("America/Chicago")).isoformat()
    except Exception:
        return None


# =============================
# ARBITRATION
# =============================

def compute_arbitration(models_dict):

    spread_votes = []
    spread_weights = []
    total_votes = []
    total_weights = []

    for model in models_dict.values():

        pick = model.get("spread_pick")
        edge = model.get("spread_edge")

        if pick in ("HOME", "AWAY") and edge is not None:
            spread_votes.append(pick)
            spread_weights.append(abs(edge))

        ou = model.get("total_pick")
        total_edge = model.get("total_edge")

        if ou in ("OVER", "UNDER") and total_edge is not None:
            total_votes.append(ou)
            total_weights.append(abs(total_edge))

    def compute_side(votes, weights):

        if not votes:
            return None

        total_models = len(votes)
        most_common = max(set(votes), key=votes.count)
        directional_pct = votes.count(most_common) / total_models

        weighted_score = sum(weights)
        tier_score = directional_pct * weighted_score

        disagreement_flag = directional_pct < 1.0

        if tier_score >= 200:
            tier_level = "HIGH"
            tier_label = "Strong Conviction Consensus"
            tier_icon = "🟢"
        elif tier_score >= 75:
            tier_level = "MEDIUM"
            tier_label = "Moderate Agreement"
            tier_icon = "🟡"
        else:
            tier_level = "LOW"
            tier_label = "Weak Consensus Edge"
            tier_icon = "🟠"

        return {
            "directional_pct": round(directional_pct, 3),
            "weighted_score": round(weighted_score, 3),
            "tier_score": round(tier_score, 3),
            "tier_level": tier_level,
            "tier_label": tier_label,
            "tier_icon": tier_icon,
            "disagreement_flag": disagreement_flag
        }

    return {
        "spread": compute_side(spread_votes, spread_weights),
        "total": compute_side(total_votes, total_weights)
    }


# =============================
# CONFIDENCE CLASSIFIER
# =============================

# def classify_game(models_dict):
#
#     edge_map = {
#         name: model.get("spread_edge")
#         for name, model in models_dict.items()
#     }
#
#     baseline = edge_map.get("Joel_Baseline_v1")
#     fatigue  = edge_map.get("FatiguePlus_v3")
#     injury   = edge_map.get("InjuryModel_v2")
#
#     def sign(x):
#         if x is None:
#             return 0
#         if x > 0:
#             return 1
#         if x < 0:
#             return -1
#         return 0
#
#     baseline_sign = sign(baseline)
#
#     cluster_edges = [e for e in [fatigue, injury] if e is not None]
#     cluster_signs = set(sign(e) for e in cluster_edges if sign(e) != 0)
#
#     cluster_aligned = len(cluster_signs) == 1
#     cluster_direction = list(cluster_signs)[0] if cluster_aligned else 0
#
#     disagreement_flag = (
#         baseline_sign != 0 and
#         cluster_direction != 0 and
#         baseline_sign != cluster_direction
#     )
#
#     # Hybrid magnitude logic
#     edges_for_magnitude = [
#         abs(e) for e in [baseline, fatigue, injury]
#         if e is not None
#     ]
#
#     magnitude = max(edges_for_magnitude) if edges_for_magnitude else 0
#
#     # Keep a reference edge for primary model source
#     reference_edge = None
#     if edges_for_magnitude:
#         # Prefer fatigue edge if it matches magnitude, else Joel
#         if fatigue is not None and abs(fatigue) == magnitude:
#             reference_edge = fatigue
#         elif baseline is not None and abs(baseline) == magnitude:
#             reference_edge = baseline
#         else:
#             reference_edge = baseline
#
#     if cluster_aligned and cluster_direction != 0:
#         alignment = "CLUSTER_A"
#     elif baseline_sign != 0:
#         alignment = "BASELINE_ONLY"
#     else:
#         alignment = "NONE"
#
#     if magnitude < 2:
#         tier = "IGNORE"
#     elif cluster_aligned and magnitude >= 4:
#         tier = "HIGH"
#     elif cluster_aligned and magnitude >= 2:
#         tier = "MODERATE"
#     else:
#         tier = "LOW"
#
#     return tier, alignment, disagreement_flag, reference_edge


# =============================
# PRIMARY MODEL SOURCE
# =============================

def determine_primary_model_source(models_dict, alignment, reference_edge):

    if alignment == "CLUSTER_A" and reference_edge is not None and abs(reference_edge) >= 2:
        return "CLUSTER_A"

    joel_edge = models_dict.get("Joel_Baseline_v1", {}).get("spread_edge")

    if joel_edge is not None and abs(joel_edge) >= 2:
        return "Joel_Baseline_v1"

    return "NONE"


# =============================
# LOAD MULTI MODEL ARTIFACT
# =============================

with open(IN_JSON, "r", encoding="utf-8") as f:
    payload = json.load(f)

games = payload["games"]

ODDS_SOURCE = "LAST"

for g in games:

    joel = g.get("models", {}).get("Joel_Baseline_v1", {})

    g["spread_home"] = g.get("spread_home_last")
    g["spread_away"] = g.get("spread_away_last")
    g["total"] = g.get("total_last")
    g["moneyline_home"] = g.get("moneyline_home_last")
    g["moneyline_away"] = g.get("moneyline_away_last")
    g["odds_source_used"] = ODDS_SOURCE

    g["odds_commence_time_cst"] = utc_to_cst(g.get("odds_commence_time_utc"))

    # Joel projections flattened (unchanged behavior)
    g["Projected Home Score"] = joel.get("proj_home")
    g["Projected Away score"] = joel.get("proj_away")
    g["Total Projection"] = joel.get("total_projection")
    g["Total Bet"] = joel.get("total_pick")
    g["Home Line Projection"] = joel.get("home_line_proj")
    g["Line Bet"] = joel.get("spread_pick")
    g["Spread Edge"] = joel.get("spread_edge")
    g["Total Edge"] = joel.get("total_edge")
    g["Parlay Edge Score"] = joel.get("parlay_edge_score")
    # --------------------------------------------------
    # Selection Authority (Transitional Architecture)
    # --------------------------------------------------
    # IMPORTANT:
    # At this phase of system evolution, Joel_Baseline_v1
    # remains the deterministic selection authority.
    #
    # Multi-model arbitration currently influences:
    # - confidence tier
    # - cluster alignment
    # - execution gating
    #
    # Future architecture goal:
    # Arbitration-driven final pick selection.
    #
    # This field makes the current authority explicit
    # to prevent ambiguity in UI and downstream artifacts.
    #
    g["selection_authority"] = "Joel_Baseline_v1"

    g["Line Result"] = None

    # Arbitration
    g["arbitration"] = compute_arbitration(g.get("models", {}))

    # Confidence
    tier, alignment, flag, reference_edge = classify_game(g.get("models", {}))

    g["confidence_tier"] = tier
    g["cluster_alignment"] = alignment
    g["disagreement_flag"] = flag

    # --------------------------------------------------
    # Hybrid Actionability Layer (Option C)
    # --------------------------------------------------

    # -----------------------------
    # Actionability (Execution Only)
    # -----------------------------

    g = apply_confidence_gate(g)

    # Primary model source exposure
    g["arbitration_cluster"] = determine_primary_model_source(
        g.get("models", {}),
        alignment,
        reference_edge
    )

    # Agent explanation
    result = build_decision_explanation(g)
    g["Explanation"] = result["decision_explanation"]
    g["Decision Factors"] = result["decision_factors"]

    g = agent_stub_overrides(g)


# =============================
# WRITE JSON
# =============================

OUT_JSON.parent.mkdir(parents=True, exist_ok=True)

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(games, f, indent=2)


# =============================
# WRITE CSV
# =============================

flat_rows = []
all_fields = set()

for g in games:
    flat_rows.append(g)
    all_fields.update(g.keys())

PREFERRED_ORDER = [
    "game_id",
    "game_date",
    "home_team",
    "away_team",
    "spread_home",
    "spread_away",
    "total",
    "Total Projection",
    "Line Bet",
    "Spread Edge",
    "Total Edge",
    "Parlay Edge Score",
    "confidence_tier",
    "selection_authority"
    "primary_model_source"
]

final_fields = PREFERRED_ORDER + sorted(all_fields - set(PREFERRED_ORDER))

if flat_rows:
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=final_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat_rows)


summary = summarize_actions(games)
if summary:
    print(summary)

print("✅ model_0052_add_model complete")
print(f"📄 JSON → {OUT_JSON}")
print(f"📊 CSV  → {OUT_CSV}")
