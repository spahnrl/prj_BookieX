# 000_RUN_ALL.py
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

args = parser.parse_args()

MODE = args.mode
RUN_ANALYSIS = args.analysis
ANALYSIS_ONLY = args.analysis_only

# ------------------------------------------------------------
# SCRIPT LAYERS
# ------------------------------------------------------------

INGESTION = [
    "a_data_static_000_nba_team_map.py",
    "b_data_001_nba_schedule.py",
    "b_data_003_join_schedule_teams.py",
    "b_data_004_ingest_boxscores.py",
    "b_data_005_ingest_player_boxscores.py",
    "b_data_006_aggregate_team_3pt.py",
    "b_data_007_ingest_injuries.py",
]

FEATURES = [
    "c_calc_010_add_team_rest_days.py",
    "c_calc_011_flag_back_to_backs.py",
    "c_calc_012_compute_fatigue_score.py",
    "c_calc_013_calc_rest_home_away_averages.py",
    "c_calc_014_rolling_team_averages.py",
    "c_calc_020_build_team_injury_impact.py",
]

CANONICAL = [
    "d_nba_021_build_canonical_games.py",
    "d_nba_022_collapse_to_game_level.py",
]

MARKET = [
    "e_nba_031_get_betline.py",
    "e_nba_032_get_betline_flatten.py",
    "f_nba_0041_add_betting_lines.py",
]

MODELS = [
    "eng/models/model_0051_runner.py",
    "eng/models/model_0052_add_model.py",
]

ARBITRATION = [
    # "eng/arbitration/zzz_0220-RETIRE-zzz_0223-RERETIRED-build_confidence_layer.py", Now embedded in eng/models/model_0052_add_model.py via eng/arbitration/confidence_engine.py
]

EVALUATION = [
    "eng/backtest_runner.py",
    "eng/calibration/build_calibration_snapshot.py",
    "r_101_report_backtest_vegas.py"
]

DAILY_VIEW = [
    "eng/daily/build_daily_view.py",
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
        SCRIPTS = INGESTION + FEATURES + CANONICAL + MARKET + MODELS + ARBITRATION + EVALUATION
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


def run(script: str):
    start = datetime.now()

    print(f"\n▶ RUNNING: {script}")
    process = subprocess.Popen(
        [sys.executable, script],
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
        print(f"\n❌ FAILED: {script}")
        sys.exit(code)

    print(f"✅ SUCCESS: {script} ({duration}s)")


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
    print(f"\n=== 🚀 BOOKIEX START ({MODE} MODE) ===")
    print(f"Started: {datetime.now()}\n")

    for script in SCRIPTS:
        run(script)

    print_summary()

    print(f"Finished: {datetime.now()}")
    print("=== 🎉 COMPLETE ===\n")


if __name__ == "__main__":
    main()