import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime


PROJECT_ROOT = Path(__file__).parent.resolve()


def run_step(command, description):
    print(f"\n=== {description} START ===")
    start = datetime.now()

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8"
    )

    duration = (datetime.now() - start).total_seconds()

    if result.returncode != 0:
        print(f"❌ {description} FAILED after {duration:.2f}s")
        sys.exit(result.returncode)

    print(f"✅ {description} COMPLETE ({duration:.2f}s)")


def run_step_soft(command, description):
    """Run a NON-CRITICAL step: log clearly but warn-and-continue on failure.

    Used for the NBA pocket robustness refresh: the dashboard falls back gracefully when
    data/nba/view/nba_pocket_robustness_latest.json is missing or stale, so a failure here
    must not abort the daily run / push.
    """
    print(f"\n=== {description} START (non-blocking) ===")
    start = datetime.now()
    try:
        result = subprocess.run(command, cwd=PROJECT_ROOT, text=True, encoding="utf-8")
    except Exception as e:
        duration = (datetime.now() - start).total_seconds()
        print(f"⚠️  {description} ERROR after {duration:.2f}s: {e}")
        print("⚠️  Warn-and-continue: dashboard will fall back to its existing trust artifact (or none).")
        return

    duration = (datetime.now() - start).total_seconds()
    if result.returncode != 0:
        print(f"⚠️  {description} FAILED after {duration:.2f}s (exit {result.returncode}) — warn-and-continue.")
        print("⚠️  Dashboard trust ratings may be stale; it falls back gracefully.")
        return

    print(f"✅ {description} COMPLETE ({duration:.2f}s)")


def main():
    print("\n🚀 === BOOKIEX AUTOMATION START ===")

    try:
        # Step 1 — Core Live Run
        run_step(
            # [sys.executable, "000_RUN_ALL_NBA.py", "--mode", "LIVE"],
            [sys.executable, "000_RUN_ALL_NBA_NCAAM.py", "--mode", "LIVE"],

            "LIVE MODEL RUN"
        )

        # Pocket ROI JSON targets the *latest* backtest_* folder by mtime. NBA LIVE runs
        # build_nba_model_pockets before backtest in 000_RUN_ALL_NBA, so a fresh backtest
        # from this run would not have pockets until we run the builders again here.
        # Scripts exit 0 on FileNotFoundError when a league has no backtest yet.
        run_step(
            [sys.executable, "eng/execution/build_nba_model_pockets.py"],
            "POCKET ROI ARTIFACTS (NBA)",
        )

        # NBA pocket robustness trust ratings (NBA only; read-only recompute from the latest
        # backtest_games.json + NBA pockets just built above). Emits the stable dashboard artifact
        # data/nba/view/nba_pocket_robustness_latest.json. Non-blocking: warn-and-continue on failure.
        run_step_soft(
            [
                sys.executable, "tools/analysis/analyze_nba_pocket_robustness.py",
                "--play-in-start-date", "2026-04-14",
                "--playoff-start-date", "2026-04-18",
                "--min-keep-sample", "100",
                "--min-post-sample", "20",
                "--emit-latest",
            ],
            "POCKET ROBUSTNESS TRUST (NBA, --emit-latest)",
        )

        run_step(
            [sys.executable, "eng/execution/build_ncaam_model_pockets.py"],
            "POCKET ROI ARTIFACTS (NCAAM)",
        )

        # Step 2 — Push Daily Updates
        run_step(
            [sys.executable, "tools/push_daily.py"],
            "UPDATE + PUSH DAILY"
        )

        print("\n🎯 === BOOKIEX AUTOMATION SUCCESS ===")

    except Exception as e:
        print(f"\n❌ AUTOMATION FAILED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()