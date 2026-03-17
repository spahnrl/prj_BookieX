# 000_RUN_ALL_NBA.py
# ============================================================
# BookieX Official Order-of-Operations Runner
# Supports:
#   --mode LIVE | LAB
#   --analysis
# ============================================================

import subprocess
import sys
import argparse
from datetime import datetime


# ------------------------------------------------------------
# ------------------------------------------------------------
# ARGUMENTS
# ------------------------------------------------------------

parser = argparse.ArgumentParser()

parser.add_argument("--mode", default="LIVE", choices=["LIVE", "LAB"])
parser.add_argument("--analysis", action="store_true")
parser.add_argument("--analysis-only", action="store_true")
parser.add_argument("--quiet", action="store_true", help="Suppress banners and summary (for combined orchestrator)")

args = parser.parse_args()

MODE = args.mode
RUN_ANALYSIS = args.analysis
ANALYSIS_ONLY = args.analysis_only
QUIET = args.quiet

# ------------------------------------------------------------
# SCRIPT LAYERS
# ------------------------------------------------------------

INGESTION = [
    "eng/pipelines/nba/a_data_static_000_nba_team_map.py",
    ("eng/pipelines/shared/b_gen_001_ingest_schedule.py", ["--league", "nba"]),
    ("eng/pipelines/shared/b_gen_003_join_schedule_teams.py", ["--league", "nba"]),
    ("eng/pipelines/shared/b_gen_004_ingest_boxscores.py", ["--league", "nba"]),
    "eng/pipelines/nba/b_data_005_ingest_player_boxscores.py",
    "eng/pipelines/nba/b_data_006_aggregate_team_3pt.py",
    "eng/pipelines/nba/b_data_007_ingest_injuries.py",
]

FEATURES = [
    "eng/pipelines/nba/c_calc_010_add_team_rest_days.py",
    "eng/pipelines/nba/c_calc_011_flag_back_to_backs.py",
    "eng/pipelines/nba/c_calc_012_compute_fatigue_score.py",
    "eng/pipelines/nba/c_calc_013_calc_rest_home_away_averages.py",
    "eng/pipelines/nba/c_calc_014_rolling_team_averages.py",
    "eng/pipelines/nba/c_calc_015_build_last5_momentum.py",
    "eng/pipelines/nba/c_calc_020_build_team_injury_impact.py",
]

CANONICAL = [
    ("eng/pipelines/shared/d_gen_021_build_canonical_games.py", ["--league", "nba"]),
    ("eng/pipelines/shared/d_gen_022_collapse_to_game_level.py", ["--league", "nba"]),
]

MARKET = [
    ("eng/pipelines/shared/e_gen_031_get_betline.py", ["--league", "nba"]),
    ("eng/pipelines/shared/e_gen_032_get_betline_flatten.py", ["--league", "nba"]),
    ("eng/pipelines/shared/f_gen_041_add_betting_lines.py", ["--league", "nba"]),
]

MODELS = [
    ("eng/models/shared/model_gen_0051_runner.py", ["--league", "nba"]),
    ("eng/models/shared/model_gen_0052_add_model.py", ["--league", "nba"]),
]

ARBITRATION = [
    # "eng/arbitration/zzz_0220-RETIRE-zzz_0223-RERETIRED-build_confidence_layer.py", Now embedded in eng/models/shared/model_gen_0052_add_model.py via eng/arbitration/confidence_engine.py
]

EVALUATION = [
    "eng/backtest/backtest_gen_runner.py",
    ("eng/analysis/analysis_039a_dynamic_sweetspot_discovery.py", ["--league", "nba"]),
    "eng/analysis/analysis_039b_execution_overlay_performance.py",
    ("eng/analysis/analysis_039b_execution_overlay_performance.py", ["--league", "nba", "--use-dynamic-sweetspots"]),
    "eng/calibration/build_calibration_snapshot.py",
    "r_101_report_backtest_vegas.py",
]

# Best-effort: on failure print warning and continue (do not fail the pipeline).
BEST_EFFORT_EVALUATION = frozenset([
    ("eng/analysis/analysis_039a_dynamic_sweetspot_discovery.py", ("--league", "nba")),
    ("eng/analysis/analysis_039b_execution_overlay_performance.py", ("--league", "nba", "--use-dynamic-sweetspots")),
])

EXECUTION = [
    "eng/execution/build_execution_overlay.py",
]

DAILY_VIEW = [
    ("eng/daily/build_gen_daily_view.py", ["--league", "nba"]),
]

ANALYSIS = [
    "eng/analysis/analysis_001_edge_distribution.py",
    "eng/analysis/analysis_002_performance_by_bucket.py",
    "eng/analysis/analysis_003_bias_detection.py",
    "eng/analysis/analysis_004_model_comparison.py",
    "eng/analysis/analysis_005_cross_model_edge_stats.py",
    "eng/analysis/analysis_006_model_performance_by_bucket.py",
    "eng/analysis/analysis_007_model_edge_correlation.py",
    "eng/analysis/analysis_008_fatigue_pass_through_check.py",
    "eng/analysis/analysis_009_fatigue_activation_rate.py",
    "eng/analysis/analysis_010_fatigue_diff_distribution.py",
    "eng/analysis/analysis_011_rest_asymmetry_check.py",
    "eng/analysis/analysis_012_rest_values_distribution.py",
    "eng/analysis/analysis_013_print_sample_fatigue_values.py",
    "eng/analysis/analysis_014_disagreement_bucket.py",
    "eng/analysis/analysis_015_confidence_backtest.py",
    "eng/analysis/analysis_016_confidence_on_backtest.py",
    "eng/analysis/analysis_017_confidence_backtest_v2.py",
    "eng/analysis/analysis_018_spread_edge_strength_curve.py",
    "eng/analysis/analysis_019_spread_direction_check.py",
    "eng/analysis/analysis_020_spread_projection_validation.py",
    "eng/analysis/analysis_021_spread_result_inversion_test.py",
    "eng/analysis/analysis_022_pick_vs_projection_alignment.py",
    "eng/analysis/analysis_024_field_presence_audit.py",
    "eng/analysis/analysis_025_true_performance_summary.py",
    "eng/analysis/analysis_026_flip_test.py",
    "eng/analysis/analysis_027_edge_sign_vs_outcome.py",
    "eng/analysis/analysis_028_simulated_corrected_mapping.py",
    "eng/analysis/analysis_029_model_pipeline_trace.py",
    "eng/analysis/analysis_030_projection_math_validation.py",
    "eng/analysis/analysis_031_spread_orientation_probe.py",
    "eng/analysis/analysis_032_projection_direction_probe.py",
    "eng/analysis/analysis_033_edge_magnitude_profit_curve.py",
    "eng/analysis/analysis_034_projection_vs_straight_up_result.py",
    "eng/analysis/analysis_035_projection_component_breakdown.py",
    "eng/analysis/analysis_036a_spread_orientation_sample.py",
    "eng/analysis/analysis_037_projection_error_by_spread.py",
    "eng/analysis/analysis_038_total_direction_bias.py",
    "eng/analysis/analysis_039b_execution_overlay_performance.py",
    "eng/analysis/analysis_040_clv_analysis.py",
]

# ------------------------------------------------------------
# MODE SWITCH
# ------------------------------------------------------------

if ANALYSIS_ONLY:
    # Only run analysis scripts
    SCRIPTS = ANALYSIS

else:
    # Build core pipeline
    if MODE == "LIVE":
        SCRIPTS = INGESTION + FEATURES + CANONICAL + MARKET + MODELS + EXECUTION + ARBITRATION + EVALUATION
    elif MODE == "LAB":
        SCRIPTS = FEATURES + CANONICAL + MODELS + ARBITRATION + EVALUATION
    else:
        raise ValueError("MODE must be LIVE or LAB")

    # Always build Daily View after core
    SCRIPTS += DAILY_VIEW

    # Append analysis if requested
    if RUN_ANALYSIS:
        SCRIPTS += ANALYSIS


# ------------------------------------------------------------
# EXECUTION ENGINE
# ------------------------------------------------------------

execution_log = []


def run_inline_audit_after_step_nba(step_path: str) -> None:
    """
    Run the integrity check for the given step (NBA). Prints INTEGRITY CHECK: PASS/FAIL.
    On mismatch raises SystemExit so the orchestrator stops like a script crash.
    """
    from pathlib import Path
    from utils.audit_helpers import audit_file_consistency, audit_csv_consistency

    project_root = Path(__file__).resolve().parent
    if "b_gen_001_ingest_schedule.py" in step_path:
        from utils.io_helpers import get_schedule_raw_path
        json_path = get_schedule_raw_path("nba")
        csv_path = json_path.parent / "nba_schedule.csv"
        r = audit_file_consistency(json_path, csv_path, "NBA Ingest (schedule)")
        if r["match_status"] != "match":
            print(f"INTEGRITY CHECK: FAIL [{r['label']}] JSON={r['json_count']} CSV={r['csv_count']}")
            sys.exit(1)
        print(f"INTEGRITY CHECK: PASS [{r['label']}] JSON={r['json_count']} CSV={r['csv_count']}")
    elif "b_gen_004_ingest_boxscores.py" in step_path:
        from configs.leagues.league_nba import BOXSCORES_TEAM_CSV_PATH, BOXSCORES_TEAM_JSON_PATH
        json_path = BOXSCORES_TEAM_JSON_PATH
        csv_path = BOXSCORES_TEAM_CSV_PATH
        r = audit_file_consistency(json_path, csv_path, "NBA Boxscores")
        if r["match_status"] != "match":
            print(f"INTEGRITY CHECK: FAIL [{r['label']}] JSON={r['json_count']} CSV={r['csv_count']}")
            sys.exit(1)
        print(f"INTEGRITY CHECK: PASS [{r['label']}] JSON={r['json_count']} CSV={r['csv_count']}")
    elif "d_gen_022_collapse_to_game_level.py" in step_path:
        from configs.leagues.league_nba import CANONICAL_CSV_PATH, GAME_LEVEL_CSV_PATH
        canonical_path = CANONICAL_CSV_PATH
        game_level_path = GAME_LEVEL_CSV_PATH
        r = audit_csv_consistency(
            canonical_path, game_level_path, "NBA Canonical (021 vs 022)", expected_derived_per_primary=0.5
        )
        if r["match_status"] != "match":
            print(f"INTEGRITY CHECK: FAIL [{r['label']}] primary={r['primary_count']} derived={r['derived_count']}")
            sys.exit(1)
        print(f"INTEGRITY CHECK: PASS [{r['label']}] primary={r['primary_count']} derived={r['derived_count']}")


def run(script_spec):
    """script_spec: str (script path) or (script path, list of extra args)."""
    if isinstance(script_spec, (list, tuple)):
        script, extra_args = script_spec[0], list(script_spec[1]) if len(script_spec) > 1 else []
        cmd = [sys.executable, script] + extra_args
    else:
        script = script_spec
        extra_args = []
        cmd = [sys.executable, script]
    start = datetime.now()

    if not QUIET:
        print(f"\n▶ RUNNING: {script}")
    process = subprocess.Popen(
        cmd,
        stdout=sys.stdout,
        stderr=sys.stderr,
        text=True
    )
    code = process.wait()

    end = datetime.now()
    duration = round((end - start).total_seconds(), 2)

    status = "SUCCESS" if code == 0 else "FAILED"

    execution_log.append({
        "script": script,
        "status": status,
        "duration_sec": duration
    })

    if code != 0:
        if (script, tuple(extra_args)) in BEST_EFFORT_EVALUATION:
            print(f"\n[WARN] Step failed (best-effort); continuing pipeline: {script}", file=sys.stderr)
            return
        print(f"\n[FAIL] FAILED: {script}")
        sys.exit(code)

    if not QUIET:
        print(f"[OK] SUCCESS: {script} ({duration}s)")
    step_path = script_spec[0] if isinstance(script_spec, (list, tuple)) else script_spec
    if any(x in step_path for x in (
        "b_gen_001_ingest_schedule.py",
        "b_gen_004_ingest_boxscores.py",
        "d_gen_022_collapse_to_game_level.py",
    )):
        run_inline_audit_after_step_nba(step_path)


def print_summary():
    print("\n================ EXECUTION SUMMARY ================")
    print(f"MODE: {MODE}")
    print(f"ANALYSIS: {RUN_ANALYSIS}")
    print("---------------------------------------------------")

    for entry in execution_log:
        print(
            f"{entry['script']:<45} "
            f"{entry['status']:<8} "
            f"{entry['duration_sec']}s"
        )

    total_time = sum(e["duration_sec"] for e in execution_log)
    print("---------------------------------------------------")
    print(f"TOTAL EXECUTION TIME: {round(total_time,2)}s")
    print("===================================================\n")


def main():
    if not QUIET:
        print(f"\n=== BOOKIEX START ({MODE} MODE) ===")
        print(f"Started: {datetime.now()}\n")

    for script in SCRIPTS:
        run(script)

    if not QUIET:
        print_summary()
        print(f"Finished: {datetime.now()}")
        print("=== COMPLETE ===\n")


if __name__ == "__main__":
    main()