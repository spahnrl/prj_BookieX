# eng/daily/build_daily_view.py

"""
build_daily_view.py — NBA-only.

Invoked by: eng/daily/build_gen_daily_view.py (with --league nba).

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

def _model_artifact_path():
    from utils.io_helpers import get_final_view_json_path
    return get_final_view_json_path("nba")

def _output_dir():
    from utils.io_helpers import get_daily_view_output_dir
    return get_daily_view_output_dir("nba")


def _calibration_path():
    from configs.leagues.league_nba import CALIBRATION_SNAPSHOT_PATH
    return CALIBRATION_SNAPSHOT_PATH


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
    """Use .get() fallbacks so missing snapshot keys (e.g. p90) don't crash the pipeline."""
    if not percentile_definitions:
        return 0.10
    abs_edge = abs(edge_value)
    p90 = percentile_definitions.get("p90", 0)
    p75 = percentile_definitions.get("p75", 0)
    p50 = percentile_definitions.get("p50", 0)
    p25 = percentile_definitions.get("p25", 0)

    if abs_edge >= p90:
        return 0.90
    elif abs_edge >= p75:
        return 0.75
    elif abs_edge >= p50:
        return 0.50
    elif abs_edge >= p25:
        return 0.25
    else:
        return 0.10


def _cluster_score(alignment):
    if not isinstance(alignment, dict):
        return None
    return round(
        3 * int(alignment.get("hot") or 0)
        + int(alignment.get("warm") or 0)
        - 0.5 * int(alignment.get("cold") or 0)
        - 0.25 * int(alignment.get("insufficient") or 0),
        4,
    )


def _best_pocket_ref(*candidates):
    rows = [c for c in candidates if isinstance(c, dict)]
    if not rows:
        return None
    rows.sort(
        key=lambda r: (
            float(r.get("roi") or -999),
            int(r.get("graded_games") or 0),
            1 if r.get("combo_kind") == "triple" else 0,
        ),
        reverse=True,
    )
    r = rows[0]
    return {
        "market_type": r.get("market_type"),
        "combo_kind": r.get("combo_kind"),
        "models_key": r.get("models_key"),
        "state_signature": r.get("state_signature"),
        "state": r.get("state"),
        "graded_games": r.get("graded_games"),
        "win_rate": r.get("win_rate"),
        "roi": r.get("roi"),
    }


def _compact_pocket_row(row):
    if not isinstance(row, dict):
        return None

    spread_alignment = row.get("spread_pocket_alignment") or {}
    total_alignment = row.get("total_pocket_alignment") or {}
    spread_score = _cluster_score(spread_alignment)
    total_score = _cluster_score(total_alignment)

    return {
        "source": "nba_current_game_pocket_view",
        "spread_cluster_score": spread_score,
        "total_cluster_score": total_score,
        "spread_pocket_alignment": dict(spread_alignment) if isinstance(spread_alignment, dict) else {},
        "total_pocket_alignment": dict(total_alignment) if isinstance(total_alignment, dict) else {},
        "best_spread_pocket": _best_pocket_ref(row.get("best_triple_spread"), row.get("best_pair_spread")),
        "best_total_pocket": _best_pocket_ref(row.get("best_triple_total"), row.get("best_pair_total")),
    }


def _load_pocket_lookup():
    root = PROJECT_ROOT / "data" / "nba" / "backtests"
    if not root.exists():
        return {}
    paths = sorted(
        root.glob("backtest_*/nba_current_game_pocket_view.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in paths:
        try:
            payload = load_json(path)
        except Exception:
            continue
        games = payload.get("games") if isinstance(payload, dict) else payload
        if not isinstance(games, list):
            continue
        out = {}
        for row in games:
            gid = str((row or {}).get("game_id") or "").strip()
            if gid:
                out[gid] = _compact_pocket_row(row)
        if out:
            return out
    return {}

# ------------------------------------------------------------
# EXECUTION OVERLAY (Deterministic, Read-Only)
# ------------------------------------------------------------


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

    model_data = load_json(_model_artifact_path())
    calibration = load_json(_calibration_path())
    pocket_lookup = _load_pocket_lookup()

    # Handle multi-model payload wrapper
    if isinstance(model_data, dict) and "games" in model_data:
        model_data = model_data["games"]

    # --------------------------------------------------------
    # Determine target date
    # --------------------------------------------------------

    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    else:
        from utils.datetime_bridge import get_default_target_slate_date, slate_date_for_game
        today_str = get_default_target_slate_date()

        slate_dates = [slate_date_for_game(g) for g in model_data]
        available_dates = sorted(set(d for d in slate_dates if d and d >= today_str))

        if not available_dates:
            print("No upcoming games available.")
            return

        target_date = available_dates[0]

    # --------------------------------------------------------
    # Filter to selected date (slate-date authority)
    # --------------------------------------------------------
    from utils.datetime_bridge import slate_date_for_game as _slate_date

    today_games = [g for g in model_data if _slate_date(g) == target_date]

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

        game_id = str(g.get("game_id") or "").strip()
        pocket = pocket_lookup.get(game_id)

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
                "all_time_snapshot_count": g.get("all_time_snapshot_count"),
                "odds_snapshot_last_utc": g.get("odds_snapshot_last_utc")
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
            # EXECUTION OVERLAY
            # ------------------------------------------------
            "execution_overlay": g.get("execution_overlay"),

            # ------------------------------------------------
            # POCKET SCORE (Read-Only Historical Pocket Lens)
            # ------------------------------------------------
            "pocket_score": (pocket or {}).get("spread_cluster_score"),
            "pocket": pocket,

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
                "utc_rollover_flag": utc_rollover_flag,
                "odds_commence_time_utc": tipoff_utc,
                "odds_commence_time_cst": tipoff_cst,
            },
        })

    artifact_hash = compute_sha256(_model_artifact_path())

    build_timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    final_output = {
        "schema_version": SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "calibration_version": CALIBRATION_VERSION,
        "generated_from_artifact_hash": artifact_hash,
        "date": target_date,
        "build_timestamp_utc": build_timestamp_utc,
        "games": structured_games
    }

    _output_dir().mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    output_path = _output_dir() / f"daily_view_{target_date}_v1.json"

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2)

    print(f"Daily View written: {output_path}")
    print(f"Games included: {len(structured_games)}")

    snapshots_dir = _output_dir() / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshots_dir / f"daily_view_{target_date}_v1_{timestamp}.json"
    with snapshot_path.open("w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2)
    print(f"Daily View snapshot written: {snapshot_path}")

    # --------------------------------------------------------
    # WRITE FULL EXPOSURE CSV
    # --------------------------------------------------------

    csv_rows = flatten_for_csv(structured_games)

    csv_output_path = _output_dir() / f"daily_view_{target_date}_v1_{timestamp}.csv"

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
