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

# ============================================================
# COLOR SYSTEM
# ============================================================

DARK_GREEN = "#0F3B2E"
ACCENT_GREEN = "#145A3E"
BUTTON_GREEN = "#184D3B"
TERMINAL_BG = "#111111"
TERMINAL_FG = "#00FF88"
WHITE = "#FFFFFF"

FONT_HEADER = ("Segoe UI", 20, "bold")
FONT_SECTION = ("Segoe UI", 16, "bold")
FONT_BODY = ("Segoe UI", 13)
FONT_BUTTON = ("Segoe UI", 13, "bold")
FONT_LOG = ("Consolas", 12)

# ============================================================
# ROOT WINDOW
# ============================================================

root = tk.Tk()
root.title("BookieX Control Panel")
root.geometry("1150x850")
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
control_frame.pack(side="left", fill="y", padx=30, pady=30)

log_frame = tk.Frame(main_frame, bg=DARK_GREEN)
log_frame.pack(side="right", fill="both", expand=True, padx=30, pady=30)

# ============================================================
# EXECUTION LOG
# ============================================================

tk.Label(
    log_frame,
    text="Execution Log",
    font=FONT_SECTION,
    bg=DARK_GREEN,
    fg=WHITE
).pack(anchor="w", pady=(0, 10))

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
    command = [sys.executable, "000_RUN_ALL.py", "--mode", mode]

    if extra_args:
        command += extra_args.split()

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


# ============================================================
# HEADER
# ============================================================

tk.Label(
    control_frame,
    text="BookieX Operations",
    font=FONT_HEADER,
    bg=DARK_GREEN,
    fg=WHITE
).pack(pady=(0, 30))

# ============================================================
# LAB MODE TOGGLE
# ============================================================

lab_mode = tk.BooleanVar(value=False)

toggle_frame = tk.Frame(control_frame, bg=DARK_GREEN)
toggle_frame.pack(pady=(0, 20))

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

tk.Label(
    control_frame,
    text=(
        "LAB Mode:\n"
        "• Skips external ingestion\n"
        "• Recomputes features + models\n"
        "• Enables backtesting + calibration\n\n"
        "LIVE Mode:\n"
        "• Full production pipeline\n"
        "• Pulls latest odds + schedule\n"
        "• No backtesting layers"
    ),
    justify="left",
    font=FONT_BODY,
    bg=DARK_GREEN,
    fg=WHITE
).pack(pady=(0, 30))


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
    btn.pack(pady=(0, 15))
    return btn


# ============================================================
# RUN CONTROLS
# ============================================================

styled_button("🚀 Run Full Pipeline", "")
styled_button("📊 Run Pipeline + Analysis", "--analysis")
styled_button("🔍 Analysis Only", "--analysis-only")

# ============================================================
# DASHBOARD SECTION
# ============================================================

tk.Label(
    control_frame,
    text="Dashboard",
    font=FONT_SECTION,
    bg=DARK_GREEN,
    fg=WHITE
).pack(pady=(40, 15))

dashboard_btn = tk.Button(
    control_frame,
    text="📈 Launch Streamlit Dashboard",
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
dashboard_btn.pack(pady=(0, 20))

# ============================================================
# START UI
# ============================================================

root.mainloop()