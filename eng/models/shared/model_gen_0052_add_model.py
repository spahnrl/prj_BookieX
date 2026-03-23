"""
eng/models/model_gen_0052_add_model.py

Unified finalization layer: read multi-model artifact (0051 output), apply
league-specific selection/arbitration, write final game view JSON/CSV for UI.

Uses safe string normalization (_s) for all fields that may be int/float
so downstream .strip() never crashes. NCAAM final rows merge upstream game dicts (NBA-style fat rows) with authority
overlays. Final-view CSV for both leagues uses the same column strategy
(preferred keys first, then sorted union of all row keys).

Usage:
  python eng/models/model_gen_0052_add_model.py --league nba
  python eng/models/model_gen_0052_add_model.py --league ncaam
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.run_log import set_silent, log_info, log_error
from utils.decorators import add_agent_reasoning_to_rows


# =============================================================================
# SHARED: Safe string normalization (handles int/float; no .strip() crash)
# =============================================================================

def _s(v):
    """Safe string for output: str(val).strip() if not None else \"\". Handles int/float."""
    if v is None:
        return ""
    return str(v).strip()


def safe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


# Column order for final-view CSV: shared with NBA (preferred keys first, then sorted remainder).
FINAL_VIEW_CSV_PREFERRED_ORDER = [
    "game_id", "game_date", "home_team", "away_team",
    "spread_home", "spread_away", "total",
    "Total Projection", "Line Bet", "Spread Edge", "Total Edge", "Parlay Edge Score",
    "confidence_tier", "selection_authority", "primary_model_source",
]


def write_final_view_csv(rows: list[dict], out_path: Path) -> None:
    """Write final game rows to CSV: union of all keys, NBA-aligned column order."""
    if not rows:
        return
    all_fields: set[str] = set()
    for g in rows:
        all_fields.update(g.keys())
    final_fields = FINAL_VIEW_CSV_PREFERRED_ORDER + sorted(
        all_fields - set(FINAL_VIEW_CSV_PREFERRED_ORDER)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=final_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# =============================================================================
# NBA: Arbitration, confidence, agent (unchanged logic); paths + _s from io_helpers
# =============================================================================

def run_nba() -> None:
    from utils.io_helpers import (
        get_model_runner_output_json_path,
        get_final_view_json_path,
        get_final_view_csv_path,
    )
    from eng.decision_explainer import build_decision_explanation
    from eng.eval_sanity import summarize_actions
    from eng.agent_stub import agent_stub_overrides
    from eng.arbitration.confidence_engine import classify_game
    from eng.arbitration.confidence_gate import apply_confidence_gate

    IN_JSON = get_model_runner_output_json_path("nba")
    OUT_JSON = get_final_view_json_path("nba")
    OUT_CSV = get_final_view_csv_path("nba")

    def utc_to_cst(ts):
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            return dt.astimezone(ZoneInfo("America/Chicago")).isoformat()
        except Exception:
            return None

    def compute_arbitration(models_dict):
        spread_votes, spread_weights = [], []
        total_votes, total_weights = [], []
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
                tier_level, tier_label, tier_icon = "HIGH", "Strong Conviction Consensus", "🟢"
            elif tier_score >= 75:
                tier_level, tier_label, tier_icon = "MEDIUM", "Moderate Agreement", "🟡"
            else:
                tier_level, tier_label, tier_icon = "LOW", "Weak Consensus Edge", "🟠"
            return {
                "directional_pct": round(directional_pct, 3),
                "weighted_score": round(weighted_score, 3),
                "tier_score": round(tier_score, 3),
                "tier_level": tier_level,
                "tier_label": tier_label,
                "tier_icon": tier_icon,
                "disagreement_flag": disagreement_flag,
            }
        return {"spread": compute_side(spread_votes, spread_weights), "total": compute_side(total_votes, total_weights)}

    def determine_primary_model_source(models_dict, alignment, reference_edge):
        if alignment == "CLUSTER_A" and reference_edge is not None and abs(reference_edge) >= 2:
            return "CLUSTER_A"
        joel_edge = models_dict.get("Joel_Baseline_v1", {}).get("spread_edge")
        if joel_edge is not None and abs(joel_edge) >= 2:
            return "Joel_Baseline_v1"
        return "NONE"

    if not IN_JSON.exists():
        raise FileNotFoundError(f"Missing multi-model JSON: {IN_JSON}")
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

        g["Projected Home Score"] = _s(joel.get("proj_home"))
        g["Projected Away score"] = _s(joel.get("proj_away"))
        g["Total Projection"] = _s(joel.get("total_projection"))
        g["Total Bet"] = _s(joel.get("total_pick"))
        g["Home Line Projection"] = _s(joel.get("home_line_proj"))
        g["Line Bet"] = _s(joel.get("spread_pick"))
        g["Spread Edge"] = joel.get("spread_edge")
        g["Total Edge"] = joel.get("total_edge")
        g["Parlay Edge Score"] = joel.get("parlay_edge_score")
        g["selection_authority"] = "Joel_Baseline_v1"
        g["Line Result"] = None
        g["arbitration"] = compute_arbitration(g.get("models", {}))
        tier, alignment, flag, reference_edge = classify_game(g.get("models", {}))
        g["confidence_tier"] = tier
        g["cluster_alignment"] = alignment
        g["disagreement_flag"] = flag
        g = apply_confidence_gate(g)
        g["arbitration_cluster"] = determine_primary_model_source(g.get("models", {}), alignment, reference_edge)
        result = build_decision_explanation(g)
        g["Explanation"] = result["decision_explanation"]
        g["Decision Factors"] = result["decision_factors"]
        g = agent_stub_overrides(g)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(games, f, indent=2)

    write_final_view_csv(list(games), OUT_CSV)

    summary = summarize_actions(games)
    if summary:
        log_info(summary)
    log_info("[OK] model_gen_0052 (NBA) complete")
    log_info(f"JSON -> {OUT_JSON}")
    log_info(f"CSV  -> {OUT_CSV}")


# =============================================================================
# NCAAM: Selection authority + build_final_rows (same structure as before)
# =============================================================================

def run_ncaam() -> None:
    from utils.io_helpers import (
        get_model_runner_output_json_path,
        get_final_view_json_path,
        get_final_view_csv_path,
        get_final_view_active_json_path,
    )
    from configs.leagues.league_ncaam import ensure_ncaam_dirs

    INPUT_PATH = get_model_runner_output_json_path("ncaam")
    OUTPUT_JSON = get_final_view_json_path("ncaam")
    OUTPUT_JSON_ACTIVE = get_final_view_active_json_path("ncaam")
    OUTPUT_CSV = get_final_view_csv_path("ncaam")
    SELECTION_AUTHORITY = "ncaam_avg_score_model"

    def utc_to_cst(ts):
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            return dt.astimezone(ZoneInfo("America/Chicago")).isoformat()
        except Exception:
            return None

    def line_from_last_or_market(g: dict, last_key: str, market_key: str) -> str:
        v = g.get(last_key)
        if v not in (None, ""):
            return _s(v)
        return _s(g.get(market_key))

    def load_payload() -> dict:
        if not INPUT_PATH.exists():
            raise FileNotFoundError(f"Missing multi-model JSON: {INPUT_PATH}")
        with open(INPUT_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict) or not isinstance(payload.get("games"), list):
            raise ValueError("Expected payload with 'games' list")
        return payload

    def make_explanation(game: dict, selected_model: dict) -> str:
        away_team = _s(game.get("away_team_display"))
        home_team = _s(game.get("home_team_display"))
        market_spread_home = _s(game.get("market_spread_home"))
        market_total = _s(game.get("market_total"))
        home_line_proj = _s(selected_model.get("home_line_proj"))
        total_projection = _s(selected_model.get("total_projection"))
        spread_pick = _s(selected_model.get("spread_pick"))
        total_pick = _s(selected_model.get("total_pick"))
        spread_edge = _s(selected_model.get("spread_edge"))
        total_edge = _s(selected_model.get("total_edge"))
        return (
            f"Game: {away_team} @ {home_team}\n"
            f"Authority: {SELECTION_AUTHORITY}\n"
            f"Market: Spread {market_spread_home}, Total {market_total}\n"
            f"Model Projection: Margin {home_line_proj}, Total {total_projection}\n"
            f"Spread Pick: {spread_pick} (edge {spread_edge})\n"
            f"Total Pick: {total_pick} (edge {total_edge})"
        )

    def compute_actionability(selected_model: dict) -> str:
        if _s(selected_model.get("spread_pick")) or _s(selected_model.get("total_pick")):
            return "ACTIVE"
        return "NONE"

    def compute_confidence_tier(selected_model: dict) -> str:
        spread_edge = safe_float(selected_model.get("spread_edge"))
        total_edge = safe_float(selected_model.get("total_edge"))
        candidates = [abs(x) for x in (spread_edge, total_edge) if x is not None]
        if not candidates:
            return "IGNORE"
        best = max(candidates)
        if best >= 10: return "HIGH"
        if best >= 5: return "MEDIUM"
        if best >= 2: return "LOW"
        return "IGNORE"

    def compute_confidence_reason(selected_model: dict) -> str:
        if not _s(selected_model.get("spread_pick")) and not _s(selected_model.get("total_pick")):
            return "No model signal"
        return "NCAAM MVP placeholder confidence"

    def build_final_rows(games: list[dict]) -> list[dict]:
        out = []
        for game in games:
            models = dict(game.get("models") or {})
            # Backtester expects exactly this key; ensure it exists from authority model
            if SELECTION_AUTHORITY not in models:
                for k, v in (game.get("models") or {}).items():
                    if v and (v.get("model_name") or "").strip() == SELECTION_AUTHORITY:
                        models[SELECTION_AUTHORITY] = v
                        break
            selected_model = models.get(SELECTION_AUTHORITY, {}) or {}
            # NCAAM completed-game grading uses home_points/away_points.
            # Prefer ESPN scoreboard schedule scores over summary box (004) when both exist — box can be stale/wrong.
            raw_away_points = game.get("away_score")
            if raw_away_points in (None, ""):
                raw_away_points = (
                    game.get("schedule_away_score")
                    or game.get("away_points")
                    or game.get("box_away_score")
                )
            raw_home_points = game.get("home_score")
            if raw_home_points in (None, ""):
                raw_home_points = (
                    game.get("schedule_home_score")
                    or game.get("home_points")
                    or game.get("box_home_score")
                )

            # Merge-through: preserve upstream multi-model / box / market keys (NBA-style fat rows).
            row = dict(game)
            row["models"] = models

            row["game_id"] = _s(game.get("canonical_game_id") or game.get("game_id"))
            row["away_team"] = _s(game.get("away_team_display") or game.get("away_team"))
            row["home_team"] = _s(game.get("home_team_display") or game.get("home_team"))
            row["away_score"] = _s(game.get("away_score"))
            row["home_score"] = _s(game.get("home_score"))
            row["away_points"] = _s(raw_away_points)
            row["home_points"] = _s(raw_home_points)

            # Lines: prefer snapshot LAST fields (NBA parity), else market_*.
            row["spread_home"] = line_from_last_or_market(game, "spread_home_last", "market_spread_home")
            row["spread_away"] = line_from_last_or_market(game, "spread_away_last", "market_spread_away")
            row["total"] = line_from_last_or_market(game, "total_last", "market_total")
            row["moneyline_home"] = line_from_last_or_market(game, "moneyline_home_last", "market_home_moneyline")
            row["moneyline_away"] = line_from_last_or_market(game, "moneyline_away_last", "market_away_moneyline")
            row["odds_source_used"] = row.get("odds_source_used") or "LAST"
            if not _s(row.get("odds_commence_time_cst")):
                cst = utc_to_cst(game.get("odds_commence_time_utc"))
                if cst:
                    row["odds_commence_time_cst"] = cst

            # NBA-shaped projection slots (NCAAM authority model may omit proj_home/proj_away).
            row["Projected Home Score"] = _s(selected_model.get("proj_home"))
            row["Projected Away score"] = _s(selected_model.get("proj_away"))
            row["Line Result"] = None

            row["selection_authority"] = SELECTION_AUTHORITY
            row["primary_model_source"] = SELECTION_AUTHORITY
            row["Home Line Projection"] = _s(selected_model.get("home_line_proj"))
            row["Total Projection"] = _s(selected_model.get("total_projection"))
            row["Spread Edge"] = _s(selected_model.get("spread_edge"))
            row["Total Edge"] = _s(selected_model.get("total_edge"))
            row["Parlay Edge Score"] = _s(selected_model.get("parlay_edge_score"))
            row["Line Bet"] = _s(selected_model.get("spread_pick"))
            row["Total Bet"] = _s(selected_model.get("total_pick"))
            row["Decision Factors"] = {}
            row["Explanation"] = make_explanation(game, selected_model)
            row["confidence_tier"] = compute_confidence_tier(selected_model)
            row["confidence_reason"] = compute_confidence_reason(selected_model)
            row["actionability"] = compute_actionability(selected_model)
            row["arbitration"] = {"spread": None, "total": None}
            row["arbitration_cluster"] = "NONE"
            row["cluster_alignment"] = "NONE"
            row["disagreement_flag"] = False
            row["agent_reasoning"] = ""
            out.append(row)
        out.sort(key=lambda r: (r.get("game_date", ""), r.get("game_id", "")))
        return out

    def build_active_rows(rows: list[dict]) -> list[dict]:
        return [r for r in rows if _s(r.get("actionability")) != "NONE"]

    ensure_ncaam_dirs()
    payload = load_payload()
    games = payload.get("games", [])
    final_rows = build_final_rows(games)
    add_agent_reasoning_to_rows(final_rows, league="ncaam")
    active_rows = build_active_rows(final_rows)

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(final_rows, f, indent=2)
    if OUTPUT_JSON_ACTIVE:
        with open(OUTPUT_JSON_ACTIVE, "w", encoding="utf-8") as f:
            json.dump(active_rows, f, indent=2)
    write_final_view_csv(final_rows, OUTPUT_CSV)

    joined = sum(1 for r in final_rows if (r.get("line_join_status") or "").strip().lower() == "matched")
    total = len(final_rows)
    log_info(f"Successfully joined {joined} market records to {total} boxscores.")
    if joined < 3000:
        log_error(f"ALERT: Joined count ({joined}) is below 3,000. Pipeline may be misaligned (odds vs boxscores). Continuing anyway.")

    log_info(f"Loaded games:                {len(games)}")
    log_info(f"Selection authority:         {SELECTION_AUTHORITY}")
    log_info(f"Final JSON written to:       {OUTPUT_JSON}")
    log_info(f"Active JSON written to:      {OUTPUT_JSON_ACTIVE}")
    log_info(f"Final CSV written to:        {OUTPUT_CSV}")
    log_info(f"Final rows:                  {len(final_rows)}")
    log_info(f"Active rows:                 {len(active_rows)}")


# =============================================================================
# ENTRYPOINT
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize multi-model output for UI (NBA or NCAAM)")
    parser.add_argument("--league", required=True, choices=["nba", "ncaam"])
    parser.add_argument("--silent", action="store_true", help="Only print critical errors")
    args = parser.parse_args()
    set_silent(args.silent)
    if args.league == "nba":
        run_nba()
    else:
        run_ncaam()


if __name__ == "__main__":
    main()
