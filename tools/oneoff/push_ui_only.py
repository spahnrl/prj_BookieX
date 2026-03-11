"""
push_ui_only.py

Pushes ONLY the Streamlit UI file to GitHub.
No data rebuild.
No daily update.
Simple and independent.
"""

import subprocess
import datetime
import sys
import os

# Move to project root (two levels above /tools/oneoff)
import pathlib
_project_root = pathlib.Path(__file__).resolve().parents[2]
os.chdir(str(_project_root))


def run(cmd):
    print(f">> {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print("❌ Command failed.")
        sys.exit(1)


def main():
    print("========================================")
    print("BOOKIEX UI DEPLOY")
    print("========================================")

    # Stage only UI file
    run("git add eng/ui/bookiex_dashboard.py")

    # Commit
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    run(f'git commit -m "UI update {timestamp}"')

    # Push
    run("git push")

    print("\n✅ UI pushed successfully.")
    print("Streamlit will auto-redeploy.")


if __name__ == "__main__":
    main()