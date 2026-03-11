"""
push_selected_daily_views.py

Push selected existing daily_view JSON files to GitHub without rebuilding them.

This version works even when launched directly from the tools folder path,
because all paths are anchored to the project root based on this script's location.
"""

import subprocess
import sys
from pathlib import Path


# --------------------------------------------------
# PATHS
# --------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
# NBA daily: same path as producer (configs.league_nba.DAILY_DIR)
DAILY_DIR = PROJECT_ROOT / "data" / "nba" / "daily"

# Edit this list anytime you want to push a different set of files.
TARGET_DATES = [
    "2026-03-01",
    "2026-03-02",
    "2026-03-03",
    "2026-03-04",
    "2026-03-05",
]


def run_command(cmd: str) -> None:
    print(f"\n>> {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print("❌ Command failed.")
        sys.exit(1)


def file_exists_for_date(date_str: str) -> Path:
    file_path = DAILY_DIR / f"daily_view_{date_str}_v1.json"
    if not file_path.exists():
        print(f"❌ Missing file: {file_path}")
        sys.exit(1)
    return file_path


def has_git_changes() -> bool:
    result = subprocess.run(
        "git diff --cached --quiet",
        shell=True,
        cwd=PROJECT_ROOT
    )
    return result.returncode != 0


def main() -> None:
    print("========================================")
    print("BOOKIEX PUSH SELECTED DAILY VIEWS")
    print("========================================")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Daily dir:     {DAILY_DIR}")

    files_to_push = []

    for date_str in TARGET_DATES:
        file_path = file_exists_for_date(date_str)
        files_to_push.append(file_path)

    print("\nFiles to push:")
    for file_path in files_to_push:
        print(f" - {file_path}")

    for file_path in files_to_push:
        relative_path = file_path.relative_to(PROJECT_ROOT).as_posix()
        run_command(f'git add "{relative_path}"')

    if not has_git_changes():
        print("\nℹ️ No staged changes detected. Nothing new to commit.")
        return

    commit_dates = f"{TARGET_DATES[0]} to {TARGET_DATES[-1]}"
    run_command(f'git commit -m "Backfill daily views {commit_dates}"')
    run_command("git push")

    print("\n✅ Selected daily_view files pushed successfully.")
    print("Streamlit should auto-redeploy.")


if __name__ == "__main__":
    main()