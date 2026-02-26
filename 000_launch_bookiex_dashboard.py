"""
Launch BookieX Streamlit Dashboard

Usage:
    python 000_launch_bookiex_dashboard.py

This avoids remembering:
    streamlit run eng/ui/bookiex_dashboard.py
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
APP_PATH = PROJECT_ROOT / "eng" / "ui" / "bookiex_dashboard.py"

if not APP_PATH.exists():
    print(f"Dashboard not found at: {APP_PATH}")
    sys.exit(1)

try:
    subprocess.run(
        ["streamlit", "run", str(APP_PATH)],
        check=True
    )
except FileNotFoundError:
    print("Streamlit not found. Make sure your virtual environment is activated.")