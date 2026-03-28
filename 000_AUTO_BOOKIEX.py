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