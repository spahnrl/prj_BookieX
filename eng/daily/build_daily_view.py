# daily/build_daily_view.py

"""
build_daily_view.py

Purpose:
Build DAILY_VIEW_V1 from frozen model artifact.

Rules:
- Read-only.
- No model recomputation.
- No ingestion.
- No threshold changes.
- Deterministic output.
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
import sys
import csv



# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MODEL_ARTIFACT_PATH = PROJECT_ROOT / "data/view/final_game_view.json"
CALIBRATION_PATH = PROJECT_ROOT / "eng/calibration/calibration_snapshot_v1.json"
OUTPUT_DIR = PROJECT_ROOT / "data/daily"

SCHEMA_VERSION = "DAILY_VIEW_V1"
MODEL_VERSION = "MULTI_MODEL_V1"
CALIBRATION_VERSION = "CALIBRATION_SNAPSHOT_V1"

def utc_timestamp_str():
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

# ------------------------------------------------------------
# UTILITIES
# ------------------------------------------------------------

def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def compute_sha256(path: Path):
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        hasher.update(f.read())
    return hasher.hexdigest()


def determine_bucket(edge_value):
    abs_edge = abs(edge_value)

    if abs_edge < 1:
        return "0-1"
    elif abs_edge < 2:
        return "1-2"
    elif abs_edge < 4:
        return "2-4"
    elif abs_edge < 8:
        return "4-8"
    elif abs_edge >= 8:
        return "8+"
    else:
        return "UNKNOWN"


def determine_percentile(edge_value, percentile_definitions):
    abs_edge = abs(edge_value)

    if abs_edge >= percentile_definitions["p90"]:
        return 0.90
    elif abs_edge >= percentile_definitions["p75"]:
        return 0.75
    elif abs_edge >= percentile_definitions["p50"]:
        return 0.50
    elif abs_edge >= percentile_definitions["p25"]:
        return 0.25
    else:
        return 0.10


# ------------------------------------------------------------
# MAIN BUILD FUNCTION
# ------------------------------------------------------------
def flatten_for_csv(structured_games):
    """
    One row per model per game.
    Deterministic.
    """
    rows = []

    for g in structured_games:

        identity = g["identity"]
        market = g["market_state"]
        model_output = g["model_output"]
        edge_metrics = g["edge_metrics"]
        context = g["context_flags"]
        calibration = g["calibration_tags"]
        overrides = g["agent_overrides"]

        arbitration = g.get("arbitration") or {}
        models = g.get("models") or {}

        for model_name, model_data in models.items():

            row = {}

            # ------------------------------------
            # Core Identity
            # ------------------------------------
            row.update({
                "game_id": identity["game_id"],
                "game_date_local": identity["game_date_local"],
                "home_team": identity["home_team"],
                "away_team": identity["away_team"],
                "model_name": model_name,
            })

            # ------------------------------------
            # Market State
            # ------------------------------------
            row.update(market)

            # ------------------------------------
            # Model-Level Data
            # ------------------------------------
            row.update({
                "model_spread_edge": model_data.get("spread_edge"),
                "model_total_edge": model_data.get("total_edge"),
                "model_projected_margin": model_data.get("projected_margin_home"),
                "model_projected_total": model_data.get("projected_total"),
                "model_spread_pick": model_data.get("spread_pick"),
                "model_total_pick": model_data.get("total_pick"),
                "model_confidence": model_data.get("confidence_classification"),
            })

            # ------------------------------------
            # Arbitration
            # ------------------------------------
            row.update({
                "arbitration_spread_pick": arbitration.get("spread_pick"),
                "arbitration_total_pick": arbitration.get("total_pick"),
                "arbitration_confidence": arbitration.get("confidence_classification"),
            })

            # ------------------------------------
            # Overall Edge Metrics
            # ------------------------------------
            row.update(edge_metrics)

            # ------------------------------------
            # Context
            # ------------------------------------
            row.update(context)

            # ------------------------------------
            # Calibration
            # ------------------------------------
            row.update(calibration)

            # ------------------------------------
            # Overrides
            # ------------------------------------
            row.update(overrides)

            rows.append(row)

    return rows


def build_daily_view():

    model_data = load_json(MODEL_ARTIFACT_PATH)
    calibration = load_json(CALIBRATION_PATH)

    # Handle multi-model payload wrapper
    if isinstance(model_data, dict) and "games" in model_data:
        model_data = model_data["games"]

    # --------------------------------------------------------
    # Determine target date
    # --------------------------------------------------------

    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    else:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        available_dates = sorted(
            g["game_date"][:10]
            for g in model_data
            if g.get("game_date")
            and g["game_date"][:10] >= today_str
        )

        if not available_dates:
            print("No upcoming games available.")
            return

        target_date = available_dates[0]

    # --------------------------------------------------------
    # Filter to selected date
    # --------------------------------------------------------

    today_games = []

    for g in model_data:
        raw_date = g.get("game_date")
        if not raw_date:
            continue

        normalized_date = raw_date[:10]

        if normalized_date == target_date:
            today_games.append(g)

    today_games = sorted(today_games, key=lambda x: x["game_id"])

    structured_games = []

    # --------------------------------------------------------
    # Build structured output
    # --------------------------------------------------------

    for g in today_games:

        spread_edge = g.get("Spread Edge")
        total_edge = g.get("Total Edge")

        # Skip games without signal
        if spread_edge is None or total_edge is None:
            continue

        spread_bucket = determine_bucket(spread_edge)

        spread_percentile = determine_percentile(
            spread_edge,
            calibration["spread_edge_percentiles"]
        )

        total_percentile = determine_percentile(
            total_edge,
            calibration["total_edge_percentiles"]
        )

        bucket_win_rate = calibration["spread_bucket_win_rates"].get(
            spread_bucket,
            None
        )

        home_3pt = g.get("home_team_3pt_pct") or 0
        away_3pt = g.get("away_team_3pt_pct") or 0
        three_pt_diff = home_3pt - away_3pt

        # ------------------------------------------------
        # TEMPORAL INTEGRITY (Additive, read-only)
        # ------------------------------------------------

        schedule_date = g.get("game_date")
        tipoff_utc = g.get("odds_commence_time_utc")
        tipoff_cst = g.get("odds_commence_time_cst")
        local_day = g.get("nba_game_day_local")

        schedule_day = schedule_date[:10] if schedule_date else None

        schedule_matches_local = (
                schedule_day == local_day
        )

        utc_rollover_flag = False

        if tipoff_utc and tipoff_cst:
            utc_day = tipoff_utc[:10]
            cst_day = tipoff_cst[:10]
            utc_rollover_flag = utc_day != cst_day

        structured_games.append({

            # ------------------------------------------------
            # IDENTITY
            # ------------------------------------------------
            "identity": {
                "game_id": g["game_id"],
                "game_date_local": g.get("game_date"),
                "home_team": g.get("home_team"),
                "away_team": g.get("away_team"),
                "tip_time_cst": g.get("odds_commence_time_cst"),
                "season_type": g.get("season_type")
            },

            # ------------------------------------------------
            # MARKET
            # ------------------------------------------------
            "market_state": {
                "spread_home_last": g.get("spread_home_last"),
                "total_last": g.get("total_last"),
                "moneyline_home_last": g.get("moneyline_home_last"),
                "spread_home_consensus": g.get("spread_home_consensus"),
                "total_consensus": g.get("total_consensus"),
                "spread_home_consensus_all_time": g.get("spread_home_consensus_all_time"),
                "total_consensus_all_time": g.get("total_consensus_all_time"),
                "consensus_book_count": g.get("consensus_book_count"),
                "all_time_snapshot_count": g.get("all_time_snapshot_count")
            },

            # ------------------------------------------------
            # MODEL OUTPUT (Joel extracted)
            # ------------------------------------------------
            "model_output": {
                "projected_home_score": g.get("Projected Home Score"),
                "projected_away_score": g.get("Projected Away score"),
                "projected_margin_home": g.get("Home Line Projection"),
                "projected_total": g.get("Total Projection"),
                "spread_pick": g.get("Line Bet"),
                "total_pick": g.get("Total Bet"),
                "confidence_tier": g.get("confidence_tier"),
                "cluster_alignment": g.get("cluster_alignment"),
                "arbitration_cluster": g.get("arbitration_cluster"),
                "confidence_reason": g.get("confidence_reason"),
                "actionability": g.get("actionability")
            },

            # ------------------------------------------------
            # EDGE METRICS
            # ------------------------------------------------
            "edge_metrics": {
                "spread_edge": spread_edge,
                "total_edge": total_edge,
                "parlay_edge_score": g.get("Parlay Edge Score"),
                "spread_edge_percentile": spread_percentile,
                "total_edge_percentile": total_percentile
            },

            # ------------------------------------------------
            # ARBITRATION (Multi-Model Consensus)
            # ------------------------------------------------
            "arbitration": g.get("arbitration"),

            # ------------------------------------------------
            # FULL MODEL BREAKDOWN (No hiding)
            # ------------------------------------------------
            "models": g.get("models"),

            # ------------------------------------------------
            # AGENT OVERRIDES
            # ------------------------------------------------
            "agent_overrides": {
                "override_pick": g.get("agent_override_pick"),
                "override_reason": g.get("agent_override_reason"),
                "override_confidence_delta": g.get("agent_override_confidence_delta")
            },

            # ------------------------------------------------
            # CONTEXT FLAGS
            # ------------------------------------------------
            "context_flags": {
                "home_rest_days": g.get("home_rest_days"),
                "away_rest_days": g.get("away_rest_days"),
                "home_b2b_flag": g.get("home_rest_bucket") == "b2b",
                "away_b2b_flag": g.get("away_rest_bucket") == "b2b",
                "home_fatigue_flag": g.get("home_fatigue_flag"),
                "away_fatigue_flag": g.get("away_fatigue_flag"),
                "home_went_ot_last_game": g.get("home_went_ot"),
                "away_went_ot_last_game": g.get("away_went_ot"),
                "home_3pt_pct": g.get("home_team_3pt_pct"),
                "away_3pt_pct": g.get("away_team_3pt_pct"),
                "three_pt_diff": three_pt_diff
            },

            # ------------------------------------------------
            # CALIBRATION TAGS
            # ------------------------------------------------
            "calibration_tags": {
                "edge_bucket": spread_bucket,
                "historical_bucket_win_rate": bucket_win_rate,
                "over_under_bias_flag": g.get("over_under_bias_flag"),
                "favorite_dog_bias_flag": g.get("favorite_dog_bias_flag"),
                "model_regime_normal": g.get("model_regime_normal")
            },
            # ------------------------------------------------
            # TEMPORAL INTEGRITY
            # ------------------------------------------------
            "temporal_integrity": {
                "schedule_date_utc": schedule_date,
                "tipoff_time_utc": tipoff_utc,
                "tipoff_time_cst": tipoff_cst,
                "tipoff_local_day": local_day,
                "schedule_matches_local_day": schedule_matches_local,
                "utc_rollover_flag": utc_rollover_flag
            },
        })

    artifact_hash = compute_sha256(MODEL_ARTIFACT_PATH)

    final_output = {
        "schema_version": SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "calibration_version": CALIBRATION_VERSION,
        "generated_from_artifact_hash": artifact_hash,
        "date": target_date,
        "games": structured_games
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = OUTPUT_DIR / f"daily_view_{target_date}_v1.json"

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2)

    print(f"Daily View written: {output_path}")
    print(f"Games included: {len(structured_games)}")

    # --------------------------------------------------------
    # WRITE FULL EXPOSURE CSV
    # --------------------------------------------------------

    csv_rows = flatten_for_csv(structured_games)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    csv_output_path = OUTPUT_DIR / f"daily_view_{target_date}_v1_{timestamp}.csv"

    if csv_rows:

        # Collect union of all keys across rows
        all_fields = set()
        for r in csv_rows:
            all_fields.update(r.keys())

        fieldnames = sorted(all_fields)

        with csv_output_path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)

        print(f"Daily View CSV written: {csv_output_path}")
        print(f"Rows written: {len(csv_rows)}")

    else:
        print("No rows written to CSV.")

if __name__ == "__main__":
    build_daily_view()