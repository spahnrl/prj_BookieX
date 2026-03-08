"""
update_and_push_daily.py

Runs full daily update cycle:
1. Build NBA + NCAAM pipeline outputs
2. Add daily/view artifacts
3. Commit with timestamp
4. Push to GitHub

This updates the live Streamlit dashboard automatically.
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
    print("BOOKIEX DAILY ONLINE UPDATE")
    print("========================================")
    print(f"Project root: {PROJECT_ROOT}")

    # 1️⃣ Build both leagues
    run_command("python 000_RUN_ALL_NBA_NCAA.py")

    # 2️⃣ Git add relevant refreshed artifacts
    run_command("git add data/daily/")
    run_command("git add data/view/")
    run_command("git add data/ncaam/daily/")
    run_command("git add data/ncaam/view/")
    run_command("git add data/ncaam/backtests/")
    run_command("git add data/ncaam/model/")

    # 3️⃣ Commit if there are staged changes
    diff_result = subprocess.run("git diff --cached --quiet", shell=True, cwd=PROJECT_ROOT)

    if diff_result.returncode == 0:
        print("\nℹ️ No staged changes to commit.")
    else:
        today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        commit_message = f'git commit -m "Daily NBA + NCAAM update {today}"'
        run_command(commit_message)

        # 4️⃣ Push
        run_command("git push")

    print("\n✅ Online dashboard updated successfully.")
    print("Visit: https://bookiex.streamlit.app")


if __name__ == "__main__":
    main()