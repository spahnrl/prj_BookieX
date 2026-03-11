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
    run_command("git add data/nba/daily/")
    run_command("git add data/ncaam/daily/")

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