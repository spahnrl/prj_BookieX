"""
push_daily.py

Purpose
-------
Stage refreshed dashboard artifacts, commit, and push to GitHub.

Assumes pipeline runs have already been completed successfully.
"""

import subprocess
import datetime
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_command(cmd):
    print(f"\n>> Running: {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print("❌ Command failed.")
        sys.exit(1)


def main():
    print("========================================")
    print("BOOKIEX DAILY PUSH")
    print("========================================")
    print(f"Project root: {PROJECT_ROOT}")

    # Stage dashboard-relevant artifacts only (exact paths, no caching).
    # NBA: data/nba/daily/ ; NCAAM: data/ncaam/daily/
    run_command("git add -f data/nba/daily/*.json")
    run_command("git add -f data/ncaam/daily/*.json")
    # Execution overlay backtest reference (all historical overlay JSONs for dashboard).
    run_command("git add -f data/nba/backtests/*/execution_overlay_performance.json")
    run_command("git add -f data/ncaam/backtests/*/execution_overlay_performance.json")
    # System Health bar (Strategy B Kelly ROI%, Total P&L).
    run_command("git add -f logs/attribution_report.json")
    run_command("git add -f logs/attribution_report_ncaam.json")
    # Agent (read-only) lane per league.
    run_command("git add -f data/nba/view/nba_agent_overlay.json")
    run_command("git add -f data/ncaam/view/ncaam_agent_overlay.json")
    # Execution Overlay "Last Updated" from latest backtest run.
    run_command("git add -f data/nba/backtests/*/backtest_summary.json")
    run_command("git add -f data/ncaam/backtests/*/backtest_summary.json")
    # Dynamic execution overlay (dashboard loads this for overlay table / Kelly).
    for _glob in (
        "data/nba/backtests/*/execution_overlay_performance_dynamic.json",
        "data/ncaam/backtests/*/execution_overlay_performance_dynamic.json",
        "data/nba/backtests/*/nba_model_pockets.json",
        "data/nba/backtests/*/nba_model_combo_pockets.json",
        "data/nba/backtests/*/nba_current_game_pocket_view.json",
        "data/nba/backtests/*/nba_live_game_pocket_view.json",
        "data/nba/backtests/*/nba_live_pocket_leaderboard.json",
        "data/nba/backtests/*/nba_best_pocket_per_game.json",
        "data/nba/backtests/*/nba_ranked_pocket_opportunities.json",
        "data/nba/backtests/*/nba_pocket_leaderboard_validation.json",
        "data/ncaam/backtests/*/ncaam_model_pockets.json",
        "data/ncaam/backtests/*/ncaam_model_combo_pockets.json",
        "data/ncaam/backtests/*/ncaam_current_game_pocket_view.json",
        "data/ncaam/backtests/*/ncaam_live_game_pocket_view.json",
        "data/ncaam/backtests/*/ncaam_live_pocket_leaderboard.json",
        "data/ncaam/backtests/*/ncaam_best_pocket_per_game.json",
        "data/ncaam/backtests/*/ncaam_ranked_pocket_opportunities.json",
        "data/ncaam/backtests/*/ncaam_pocket_leaderboard_validation.json",
    ):
        if list(PROJECT_ROOT.glob(_glob)):
            run_command(f"git add -f {_glob}")
    # UI code and runtime dependencies (stage only if present).
    for _path in (
        "eng/ui/bookiex_dashboard.py",
        "eng/execution/build_nba_model_pockets.py",
        "eng/execution/build_nba_pocket_leaderboard_validation.py",
        "eng/execution/build_ncaam_model_pockets.py",
        "eng/execution/build_ncaam_pocket_leaderboard_validation.py",
        "utils/io_helpers.py",
        "assets/RS_JP_BookieX_v02.png",
        "assets/RS_JP_BookieX_v04_COLLEGE.png",
    ):
        if (PROJECT_ROOT / _path).exists():
            run_command(f"git add -f {_path}")

    diff_result = subprocess.run("git diff --cached --quiet", shell=True, cwd=PROJECT_ROOT)

    if diff_result.returncode == 0:
        print("\nℹ️ No staged changes to commit.")
        return

    today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    commit_message = f'git commit -m "Daily dashboard push {today}"'
    run_command(commit_message)
    run_command("git push")

    print("\n✅ Dashboard artifacts pushed successfully.")
    print("Visit: https://bookiex.streamlit.app")


if __name__ == "__main__":
    main()