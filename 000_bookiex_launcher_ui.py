# ============================================================
# 000_bookiex_launcher_ui.py
# BookieX Control Panel — Production Version
# ============================================================

import tkinter as tk
from tkinter import scrolledtext
import subprocess
import sys
import threading
import os
import webbrowser
from datetime import date, timedelta
from pathlib import Path

# ============================================================
# COLOR SYSTEM
# ============================================================

DARK_GREEN = "#0F3B2E"
ACCENT_GREEN = "#145A3E"
BUTTON_GREEN = "#184D3B"
TERMINAL_BG = "#111111"
TERMINAL_FG = "#00FF88"
WHITE = "#FFFFFF"

FONT_HEADER = ("Segoe UI", 16, "bold")
FONT_SECTION = ("Segoe UI", 14, "bold")
FONT_BODY = ("Segoe UI", 11)
FONT_BUTTON = ("Segoe UI", 12, "bold")
FONT_LOG = ("Consolas", 11)

# ============================================================
# ROOT WINDOW
# ============================================================

root = tk.Tk()
root.title("BookieX Control Panel")
root.geometry("1150x620")
root.configure(bg=DARK_GREEN)

# Optional Sports Betting Icon (Place .ico file in same directory)
if os.path.exists("bookiex_icon.ico"):
    root.iconbitmap("bookiex_icon.ico")

# ============================================================
# MAIN LAYOUT
# ============================================================

main_frame = tk.Frame(root, bg=DARK_GREEN)
main_frame.pack(fill="both", expand=True)

control_frame = tk.Frame(main_frame, bg=DARK_GREEN)
control_frame.pack(side="left", fill="y", padx=18, pady=18)

log_frame = tk.Frame(main_frame, bg=DARK_GREEN)
log_frame.pack(side="right", fill="both", expand=True, padx=18, pady=18)

# ============================================================
# EXECUTION LOG
# ============================================================

tk.Label(
    log_frame,
    text="Execution Log",
    font=FONT_SECTION,
    bg=DARK_GREEN,
    fg=WHITE
).pack(anchor="w", pady=(0, 6))

log_text = scrolledtext.ScrolledText(
    log_frame,
    wrap="word",
    font=FONT_LOG,
    bg=TERMINAL_BG,
    fg=TERMINAL_FG,
    insertbackground=WHITE,
    borderwidth=0,
    relief="flat"
)
log_text.pack(fill="both", expand=True)


def write_log(message: str):
    log_text.insert(tk.END, message + "\n")
    log_text.see(tk.END)


# ============================================================
# EXECUTION ENGINE
# ============================================================

def run_command(command_list):
    write_log(f"\n>>> Launching: {' '.join(command_list)}\n")

    process = subprocess.Popen(
        command_list,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    for line in process.stdout:
        write_log(line.rstrip())

    process.wait()
    write_log("\n>>> Execution Complete\n")


def launch_run_all(extra_args=""):
    mode = "LAB" if lab_mode.get() else "LIVE"
    command = [sys.executable, "000_RUN_ALL_NBA_NCAAM.py", "--mode", mode]

    parts = []
    if extra_args:
        parts.extend(extra_args.split())
    if include_future_day.get():
        n = int(future_days_var.get())
        start_d = date.today()
        end_d = start_d + timedelta(days=n)
        parts.extend(["--start-date", start_d.strftime("%Y%m%d"), "--end-date", end_d.strftime("%Y%m%d")])
    if parts:
        command += parts

    threading.Thread(
        target=run_command,
        args=(command,),
        daemon=True
    ).start()


def launch_dashboard():
    command = [sys.executable, "000_launch_bookiex_dashboard.py"]

    threading.Thread(
        target=run_command,
        args=(command,),
        daemon=True
    ).start()

def update_online_dashboard():
    command = [sys.executable, "tools/push_daily.py"]

    threading.Thread(
        target=run_command,
        args=(command,),
        daemon=True
    ).start()

# ============================================================
# HEADER
# ============================================================

tk.Label(
    control_frame,
    text="BookieX Operations",
    font=FONT_HEADER,
    bg=DARK_GREEN,
    fg=WHITE
).pack(pady=(0, 10))

# ============================================================
# LAB MODE TOGGLE
# ============================================================

lab_mode = tk.BooleanVar(value=False)

toggle_frame = tk.Frame(control_frame, bg=DARK_GREEN)
toggle_frame.pack(pady=(0, 8))

lab_toggle = tk.Checkbutton(
    toggle_frame,
    text="🧪 Enable LAB Mode (Research Mode)",
    variable=lab_mode,
    font=FONT_BODY,
    bg=DARK_GREEN,
    fg=WHITE,
    selectcolor=DARK_GREEN,
    activebackground=DARK_GREEN,
    activeforeground=WHITE
)
lab_toggle.pack(anchor="w")

# Include Future Day: toggle + dropdown (1-5 days)
include_future_day = tk.BooleanVar(value=False)
future_days_var = tk.StringVar(value="1")
future_frame = tk.Frame(control_frame, bg=DARK_GREEN)
future_frame.pack(pady=(4, 0))
future_toggle = tk.Checkbutton(
    future_frame,
    text="Include Future Day",
    variable=include_future_day,
    font=FONT_BODY,
    bg=DARK_GREEN,
    fg=WHITE,
    selectcolor=DARK_GREEN,
    activebackground=DARK_GREEN,
    activeforeground=WHITE
)
future_toggle.pack(anchor="w")
future_dropdown_frame = tk.Frame(control_frame, bg=DARK_GREEN)
future_dropdown_frame.pack(pady=(4, 0))
tk.Label(
    future_dropdown_frame,
    text="Days:",
    font=FONT_BODY,
    bg=DARK_GREEN,
    fg=WHITE
).pack(side="left", padx=(0, 6))
future_days_menu = tk.OptionMenu(
    future_dropdown_frame,
    future_days_var,
    "1", "2", "3", "4", "5"
)
future_days_menu.config(
    font=FONT_BODY,
    bg=BUTTON_GREEN,
    fg=WHITE,
    activebackground=ACCENT_GREEN,
    activeforeground=WHITE
)
future_days_menu.pack(side="left")
tk.Label(
    control_frame,
    text="(NCAAM schedule: today through today + N days)",
    font=("Segoe UI", 10),
    bg=DARK_GREEN,
    fg=WHITE
).pack(anchor="w", pady=(2, 0))

tk.Label(
    control_frame,
    text="LAB: skip ingestion, recompute + backtest. LIVE: full pipeline, latest odds.",
    justify="left",
    font=("Segoe UI", 10),
    bg=DARK_GREEN,
    fg=WHITE
).pack(pady=(0, 12))


# ============================================================
# BUTTON BUILDER
# ============================================================

def styled_button(title, args):
    btn = tk.Button(
        control_frame,
        text=title,
        width=36,
        font=FONT_BUTTON,
        bg=BUTTON_GREEN,
        fg=WHITE,
        activebackground=ACCENT_GREEN,
        activeforeground=WHITE,
        relief="flat",
        bd=0,
        cursor="hand2",
        command=lambda: launch_run_all(args)
    )
    btn.pack(pady=(0, 5))
    return btn


# ============================================================
# RUN CONTROLS
# ============================================================

styled_button("🚀 Run Full Pipeline", "")
styled_button("📊 Run Pipeline + Analysis", "--analysis")
styled_button("🔍 Analysis Only", "--analysis-only")

# ============================================================
# ONLINE UPDATE SECTION
# ============================================================

tk.Label(
    control_frame,
    text="Online Deployment",
    font=FONT_SECTION,
    bg=DARK_GREEN,
    fg=WHITE
).pack(pady=(12, 6))

update_online_btn = tk.Button(
    control_frame,
    text="🌐 Update Online Dashboard (Build + Push)",
    width=36,
    font=FONT_BUTTON,
    bg=BUTTON_GREEN,
    fg=WHITE,
    activebackground=ACCENT_GREEN,
    activeforeground=WHITE,
    relief="flat",
    bd=0,
    cursor="hand2",
    command=update_online_dashboard
)
update_online_btn.pack(pady=(0, 8))


# ============================================================
# DASHBOARD SECTION
# ============================================================

tk.Label(
    control_frame,
    text="Dashboard",
    font=FONT_SECTION,
    bg=DARK_GREEN,
    fg=WHITE
).pack(pady=(12, 6))

dashboard_btn = tk.Button(
    control_frame,
    text="📈 Launch Streamlit Dashboard (Local)",
    width=36,
    font=FONT_BUTTON,
    bg=BUTTON_GREEN,
    fg=WHITE,
    activebackground=ACCENT_GREEN,
    activeforeground=WHITE,
    relief="flat",
    bd=0,
    cursor="hand2",
    command=launch_dashboard
)
dashboard_btn.pack(pady=(0, 5))

def launch_online_dashboard():
    webbrowser.open("https://bookiex.streamlit.app")

online_dashboard_btn = tk.Button(
    control_frame,
    text="🌍 Launch Streamlit Dashboard (Online)",
    width=36,
    font=FONT_BUTTON,
    bg=BUTTON_GREEN,
    fg=WHITE,
    activebackground=ACCENT_GREEN,
    activeforeground=WHITE,
    relief="flat",
    bd=0,
    cursor="hand2",
    command=launch_online_dashboard
)
online_dashboard_btn.pack(pady=(0, 5))

# ============================================================
# NCAAM — name overrides (Odds ↔ ESPN)
# ============================================================

NCAAM_MATCH_OVERRIDES_CSV = (
    Path(__file__).resolve().parent / "data" / "ncaam" / "static" / "ncaam_match_overrides.csv"
)


def open_ncaam_match_overrides_in_excel():
    """Open match overrides CSV with the Windows default app (Excel if .csv is associated)."""
    path = NCAAM_MATCH_OVERRIDES_CSV.resolve()
    if not path.is_file():
        write_log(f"\n>>> NCAAM match overrides not found:\n    {path}\n")
        return
    if sys.platform != "win32":
        write_log("\n>>> Open-in-Excel is implemented for Windows. Open the CSV path manually.\n")
        return
    try:
        os.startfile(path)
        write_log(f"\n>>> Opened in default app (use Excel as default for .csv if needed):\n    {path}\n")
    except OSError as e:
        write_log(f"\n>>> Could not open CSV: {e}\n")


tk.Label(
    control_frame,
    text="NCAAM mapping",
    font=FONT_SECTION,
    bg=DARK_GREEN,
    fg=WHITE
).pack(pady=(12, 6))

ncaam_overrides_btn = tk.Button(
    control_frame,
    text="📋 Edit NCAAM match overrides (Excel)",
    width=36,
    font=FONT_BUTTON,
    bg=BUTTON_GREEN,
    fg=WHITE,
    activebackground=ACCENT_GREEN,
    activeforeground=WHITE,
    relief="flat",
    bd=0,
    cursor="hand2",
    command=open_ncaam_match_overrides_in_excel,
)
ncaam_overrides_btn.pack(pady=(0, 5))

# ============================================================
# START UI
# ============================================================

root.mainloop()