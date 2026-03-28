# bookiex_dashboard.py
# Executive View — Correct Field Mapping

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import re
import streamlit as st
import json
import pandas as pd
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


# --------------------------------------------------
# CONFIG (NBA/NCAAM daily dirs: same contract as producer via io_helpers)
# --------------------------------------------------

from utils.io_helpers import get_daily_view_output_dir, get_backtest_output_root

NBA_DAILY_DIR = get_daily_view_output_dir("nba")
NCAAM_DAILY_DIR = get_daily_view_output_dir("ncaam")

NBA_HEADER_ICON = "assets/RS_JP_BookieX_v02.png"
NCAAM_HEADER_ICON = "assets/RS_JP_BookieX_v04_COLLEGE.png"

# Kelly / execution overlay assumptions
# Edit these as new backtesting information becomes available.
DUAL_SWEET_SPOT_WIN_PCT = 0.571
SPREAD_SWEET_SPOT_WIN_PCT = 0.546
TOTAL_SWEET_SPOT_WIN_PCT = 0.548

# Standard -110 odds
KELLY_PAYOUT_RATIO = 100 / 110

# Project root; attribution report path is league-specific (see _attribution_report_path_for_league).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Backtest reference date shown to user
EXECUTION_OVERLAY_LAST_UPDATED = "3/6/2025"

# Execution overlay reference table shown in UI (fallback when no JSON)
BUCKET_EXPLANATIONS_STATIC = {
    "Dual Sweet Spot": "Spread edge 1-4 pts, total edge 1-4 pts, total 225-242, spread line <10",
    "Spread Sweet Spot": "Spread edge 1-4 pts, spread line <12",
    "Total Sweet Spot": "Total edge 1-4 pts, total 225-242, spread line <12",
    "Neutral": "Outside sweet spot and avoid bands",
    "Avoid": "Spread edge >6 or spread >=12, or total edge >8 or total <225",
    "All Games": "All graded games",
}
EXECUTION_OVERLAY_PERFORMANCE = [
    {"Bucket": "Dual Sweet Spot", "Games": 42, "Win%": 0.571, "ROI": 0.091, "Explanation": BUCKET_EXPLANATIONS_STATIC["Dual Sweet Spot"]},
    {"Bucket": "Spread Sweet Spot", "Games": 108, "Win%": 0.546, "ROI": 0.052, "Explanation": BUCKET_EXPLANATIONS_STATIC["Spread Sweet Spot"]},
    {"Bucket": "Total Sweet Spot", "Games": 62, "Win%": 0.548, "ROI": 0.047, "Explanation": BUCKET_EXPLANATIONS_STATIC["Total Sweet Spot"]},
    {"Bucket": "Neutral", "Games": 50, "Win%": 0.520, "ROI": 0.033, "Explanation": BUCKET_EXPLANATIONS_STATIC["Neutral"]},
    {"Bucket": "Avoid", "Games": 214, "Win%": 0.486, "ROI": -0.068, "Explanation": BUCKET_EXPLANATIONS_STATIC["Avoid"]},
    {"Bucket": "All Games", "Games": 476, "Win%": 0.519, "ROI": -0.001, "Explanation": BUCKET_EXPLANATIONS_STATIC["All Games"]},
]

# --------------------------------------------------
# LOAD FILES
# --------------------------------------------------

league = st.selectbox("League", ["NBA", "NCAAM"], index=0)

if league == "NBA":
    DAILY_DIR = NBA_DAILY_DIR
    file_pattern = "daily_view_*_v1.json"
    header_icon_path = NBA_HEADER_ICON
else:
    DAILY_DIR = NCAAM_DAILY_DIR
    file_pattern = "daily_view_ncaam_*_v1.json"
    header_icon_path = NCAAM_HEADER_ICON

files = list(DAILY_DIR.glob(file_pattern))


def _date_from_name(path: Path, is_ncaam: bool) -> str:
    parts = path.name.split("_")
    return parts[3] if is_ncaam else parts[2]


# For each date, use the file with the latest OS modification time (e.g. 5 AM vs 5 PM run).
by_date = defaultdict(list)
for f in files:
    by_date[_date_from_name(f, league == "NCAAM")].append(f)
date_map = {d: max(flist, key=lambda p: p.stat().st_mtime) for d, flist in by_date.items()}

if not date_map:
    st.error(
        f"No daily view data for **{league}**. "
        f"Expected directory: `{DAILY_DIR.resolve()}`. "
        "Run the pipeline (and build daily view) locally, or deploy with daily view JSON files present."
    )
    st.stop()

# Sidebar: current bankroll for Kelly sizing (replaces fixed example bankroll)
current_bankroll = st.sidebar.number_input(
    "Current Bankroll ($)",
    min_value=0,
    value=1000,
    step=100,
    help="Your actual balance for Kelly stake sizing.",
)

qr_code_path = PROJECT_ROOT / "assets" / "qr-code_bookiex_v01.png"
if qr_code_path.exists():
    st.sidebar.image(str(qr_code_path), width=220)
# --------------------------------------------------
# PAGE SETUP
# --------------------------------------------------

page_title_text = f"BookieX — {league} Daily View"
st.set_page_config(page_title = page_title_text , layout="wide")

st.markdown("""
<style>
.header-container {
    background: linear-gradient(90deg, #0f1c2e 0%, #1f2f4a 100%);
    padding: 18px 25px;
    border-radius: 10px;
    margin-bottom: 25px;
}
.header-title {
    color: white;
    font-size: 32px;
    font-weight: 700;
    margin: 0;
}
</style>
""", unsafe_allow_html=True)

col1, col2 = st.columns([1, 6])

with col1:
    st.image(header_icon_path, width=90)

with col2:
    st.markdown(
        f"<h1 style='margin-bottom:0;'>{page_title_text}</h1>",
        unsafe_allow_html=True
    )

# Attribution ingestion: full report for System Health bar (league-specific path).
def _attribution_report_path_for_league(league_ui: str) -> Path:
    """Return logs/attribution_report_<league>.json for the selected league."""
    name = "attribution_report_ncaam.json" if league_ui == "NCAAM" else "attribution_report_nba.json"
    return PROJECT_ROOT / "logs" / name


def load_attribution_report(path: Path) -> dict | None:
    """Read attribution report JSON. Returns full report dict or None."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


# # System Health bar: Strategy B (Kelly) ROI% + Total P&L; green if positive, red if negative
# _attribution = load_attribution_report(_attribution_report_path_for_league(league))
# _sb = (_attribution or {}).get("strategy_b_kelly") or {}
# _kelly_roi = _sb.get("yield_roi_pct")
# _kelly_pnl = _sb.get("total_pnl")
# if _kelly_roi is not None and _kelly_pnl is not None:
#     _roi_color = "#2ecc71" if (_kelly_roi or 0) >= 0 else "#e74c3c"
#     _pnl_color = "#2ecc71" if (_kelly_pnl or 0) >= 0 else "#e74c3c"
#     st.markdown(
#         f"<div style='background: linear-gradient(90deg, #0f1c2e 0%, #1f2f4a 100%); "
#         f"padding: 12px 18px; border-radius: 8px; margin-bottom: 16px;'>"
#         f"<strong style='color: #fff;'>System Health</strong> — "
#         f"<span style='color: #7fdbff;'>Strategy B (Kelly) ROI%</span>: "
#         f"<strong style='color: {_roi_color};'>{_kelly_roi:+.2f}%</strong> &nbsp;|&nbsp; "
#         f"<span style='color: #7fdbff;'>Total P&L</span>: "
#         f"<strong style='color: {_pnl_color};'>${_kelly_pnl:+,.2f}</strong>"
#         f"</div>",
#         unsafe_allow_html=True,
#     )
# elif _kelly_roi is not None:
#     _roi_color = "#2ecc71" if (_kelly_roi or 0) >= 0 else "#e74c3c"
#     st.markdown(
#         f"<div style='background: linear-gradient(90deg, #0f1c2e 0%, #1f2f4a 100%); "
#         f"padding: 12px 18px; border-radius: 8px; margin-bottom: 16px;'>"
#         f"<strong style='color: #fff;'>System Health</strong> — "
#         f"<span style='color: #7fdbff;'>Strategy B (Kelly) ROI%</span>: "
#         f"<strong style='color: {_roi_color};'>{_kelly_roi:+.2f}%</strong>"
#         f"</div>",
#         unsafe_allow_html=True,
#     )
# else:
#     st.markdown(
#         "<div style='background: #2d2d2d; padding: 12px 18px; border-radius: 8px; margin-bottom: 16px;'>"
#         "<strong style='color: #fff;'>System Health</strong> — "
#         "<span style='color: #888;'>Strategy B (Kelly) ROI% / Total P&L: n/a</span> "
#         "(run analysis_041_agent_attribution.py to populate)</div>",
#         unsafe_allow_html=True,
#     )


# --------------------------------------------------
# HELPERS
# --------------------------------------------------


def safe_round(value, ndigits=2, default=0.0):
    try:
        if value in (None, ""):
            return default
        return round(float(value), ndigits)
    except Exception:
        return default


def safe_num(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _parse_iso_datetime(value) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _game_commence_sort_key(g: dict) -> tuple:
    """UTC timestamp for chronological schedule order; missing times last; stable tie-breaker."""
    ti = g.get("temporal_integrity") if isinstance(g.get("temporal_integrity"), dict) else {}
    ident = g.get("identity") if isinstance(g.get("identity"), dict) else {}
    for raw in (
        ti.get("odds_commence_time_utc"),
        ti.get("tipoff_time_utc"),
        ident.get("tip_time_cst"),
        ti.get("odds_commence_time_cst"),
        ti.get("tipoff_time_cst"),
        ident.get("game_date_local"),
    ):
        dt = _parse_iso_datetime(raw)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ts = dt.astimezone(timezone.utc).timestamp()
            break
    else:
        ts = float("inf")
    gid = str(
        ident.get("game_id")
        or g.get("game_id")
        or g.get("espn_game_id")
        or g.get("game_source_id")
        or ""
    )
    return (ts, gid)


def _arb_branch(arb_dict, key: str) -> dict:
    """`arbitration.spread` / `arbitration.total` may be JSON null while keys exist (e.g. NCAAM)."""
    if not isinstance(arb_dict, dict):
        return {}
    br = arb_dict.get(key)
    return br if isinstance(br, dict) else {}


def _execution_overlay_backtest_date(league_ui: str) -> str:
    """Last updated date for Execution Overlay Backtest Reference from latest backtest run; falls back to static constant."""
    try:
        league_lower = (league_ui or "").strip().lower()
        if league_lower not in ("nba", "ncaam"):
            return EXECUTION_OVERLAY_LAST_UPDATED
        root = get_backtest_output_root(league_lower)
        if not root.exists():
            return EXECUTION_OVERLAY_LAST_UPDATED
        subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
        if not subdirs:
            return EXECUTION_OVERLAY_LAST_UPDATED
        latest = max(subdirs, key=lambda d: d.stat().st_mtime)
        summary_path = latest / "backtest_summary.json"
        if not summary_path.exists():
            return EXECUTION_OVERLAY_LAST_UPDATED
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
        ts = (summary or {}).get("generated_at_utc") or ""
        if not ts:
            return EXECUTION_OVERLAY_LAST_UPDATED
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return f"{dt.month}/{dt.day}/{dt.year}"
    except Exception:
        return EXECUTION_OVERLAY_LAST_UPDATED


def _load_execution_overlay_performance(league_ui: str) -> tuple[list[dict] | None, str | None]:
    """Load execution_overlay_performance_dynamic.json only from latest backtest dir. No fallback to fixed.
    Returns (buckets, date_str) or (None, None) if dynamic file is missing, invalid, empty, or unusable."""
    try:
        league_lower = (league_ui or "").strip().lower()
        if league_lower not in ("nba", "ncaam"):
            return None, None
        root = get_backtest_output_root(league_lower)
        if not root.exists():
            return None, None
        subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
        if not subdirs:
            return None, None
        latest = max(subdirs, key=lambda d: d.stat().st_mtime)
        dynamic_path = latest / "execution_overlay_performance_dynamic.json"
        if not dynamic_path.exists():
            return None, None
        with open(dynamic_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        buckets = payload.get("buckets")
        if not buckets or not isinstance(buckets, list):
            return None, None
        ts = (payload or {}).get("generated_at_utc") or ""
        if ts:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            date_str = f"{dt.month}/{dt.day}/{dt.year}"
        else:
            date_str = None
        return buckets, date_str
    except Exception:
        return None, None


def _load_nba_pocket_artifacts() -> tuple[dict | None, dict | None, dict | None, dict | None, str | None]:
    """
    Load NBA pocket JSONs from the latest backtest directory (same mtime rule as overlay).
    Returns (model_pockets_doc, combo_doc, current_full_doc, live_slate_doc_or_none, date_label).
    Live slate file is optional if present alongside the three core artifacts.
    """
    try:
        root = get_backtest_output_root("nba")
        if not root.exists():
            return None, None, None, None, None
        subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
        if not subdirs:
            return None, None, None, None, None
        latest = max(subdirs, key=lambda d: d.stat().st_mtime)
        p1 = latest / "nba_model_pockets.json"
        p2 = latest / "nba_model_combo_pockets.json"
        p3 = latest / "nba_current_game_pocket_view.json"
        if not p1.exists() or not p2.exists() or not p3.exists():
            return None, None, None, None, None
        with open(p1, "r", encoding="utf-8") as f:
            d1 = json.load(f)
        with open(p2, "r", encoding="utf-8") as f:
            d2 = json.load(f)
        with open(p3, "r", encoding="utf-8") as f:
            d3 = json.load(f)
        live_doc = None
        p4 = latest / "nba_live_game_pocket_view.json"
        if p4.exists():
            with open(p4, "r", encoding="utf-8") as f:
                live_doc = json.load(f)
        ts = (d1 or {}).get("generated_at_utc") or ""
        date_str = None
        if ts:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            date_str = f"{dt.month}/{dt.day}/{dt.year}"
        return d1, d2, d3, live_doc, date_str
    except Exception:
        return None, None, None, None, None


_nba_pockets_doc, _nba_combo_doc, _nba_current_pockets_doc, _nba_live_pockets_doc, _nba_pockets_date = (
    _load_nba_pocket_artifacts() if league == "NBA" else (None, None, None, None, None)
)


def _load_nba_live_pocket_leaderboard() -> dict | None:
    """Optional nba_live_pocket_leaderboard.json from latest NBA backtest dir."""
    try:
        root = get_backtest_output_root("nba")
        if not root.exists():
            return None
        subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
        if not subdirs:
            return None
        latest = max(subdirs, key=lambda d: d.stat().st_mtime)
        p = latest / "nba_live_pocket_leaderboard.json"
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


_nba_live_pocket_leaderboard_doc = _load_nba_live_pocket_leaderboard() if league == "NBA" else None


def _load_nba_best_pocket_per_game() -> dict | None:
    """Optional nba_best_pocket_per_game.json from latest NBA backtest dir."""
    try:
        root = get_backtest_output_root("nba")
        if not root.exists():
            return None
        subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
        if not subdirs:
            return None
        latest = max(subdirs, key=lambda d: d.stat().st_mtime)
        p = latest / "nba_best_pocket_per_game.json"
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


_nba_best_pocket_doc = _load_nba_best_pocket_per_game() if league == "NBA" else None


def _load_nba_ranked_pocket_opportunities() -> dict | None:
    """Optional nba_ranked_pocket_opportunities.json from latest NBA backtest dir."""
    try:
        root = get_backtest_output_root("nba")
        if not root.exists():
            return None
        subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
        if not subdirs:
            return None
        latest = max(subdirs, key=lambda d: d.stat().st_mtime)
        p = latest / "nba_ranked_pocket_opportunities.json"
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


_nba_ranked_pocket_doc = _load_nba_ranked_pocket_opportunities() if league == "NBA" else None


def _load_nba_pocket_leaderboard_validation() -> dict | None:
    """Optional nba_pocket_leaderboard_validation.json from latest NBA backtest dir."""
    try:
        root = get_backtest_output_root("nba")
        if not root.exists():
            return None
        subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
        if not subdirs:
            return None
        latest = max(subdirs, key=lambda d: d.stat().st_mtime)
        p = latest / "nba_pocket_leaderboard_validation.json"
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


_nba_pocket_validation_doc = _load_nba_pocket_leaderboard_validation() if league == "NBA" else None


def _load_ncaam_pocket_artifacts() -> tuple[dict | None, dict | None, dict | None, dict | None, str | None]:
    """
    Load NCAAM pocket JSONs from the latest backtest directory (same mtime rule as overlay).
    Returns (model_pockets_doc, combo_doc, current_full_doc, live_slate_doc_or_none, date_label).
    """
    try:
        root = get_backtest_output_root("ncaam")
        if not root.exists():
            return None, None, None, None, None
        subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
        if not subdirs:
            return None, None, None, None, None
        latest = max(subdirs, key=lambda d: d.stat().st_mtime)
        p1 = latest / "ncaam_model_pockets.json"
        p2 = latest / "ncaam_model_combo_pockets.json"
        p3 = latest / "ncaam_current_game_pocket_view.json"
        if not p1.exists() or not p2.exists() or not p3.exists():
            return None, None, None, None, None
        with open(p1, "r", encoding="utf-8") as f:
            d1 = json.load(f)
        with open(p2, "r", encoding="utf-8") as f:
            d2 = json.load(f)
        with open(p3, "r", encoding="utf-8") as f:
            d3 = json.load(f)
        live_doc = None
        p4 = latest / "ncaam_live_game_pocket_view.json"
        if p4.exists():
            with open(p4, "r", encoding="utf-8") as f:
                live_doc = json.load(f)
        ts = (d1 or {}).get("generated_at_utc") or ""
        date_str = None
        if ts:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            date_str = f"{dt.month}/{dt.day}/{dt.year}"
        return d1, d2, d3, live_doc, date_str
    except Exception:
        return None, None, None, None, None


_ncaam_pockets_doc, _ncaam_combo_doc, _ncaam_current_pockets_doc, _ncaam_live_pockets_doc, _ncaam_pockets_date = (
    _load_ncaam_pocket_artifacts() if league == "NCAAM" else (None, None, None, None, None)
)


def _load_ncaam_live_pocket_leaderboard() -> dict | None:
    try:
        root = get_backtest_output_root("ncaam")
        if not root.exists():
            return None
        subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
        if not subdirs:
            return None
        latest = max(subdirs, key=lambda d: d.stat().st_mtime)
        p = latest / "ncaam_live_pocket_leaderboard.json"
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


_ncaam_live_pocket_leaderboard_doc = _load_ncaam_live_pocket_leaderboard() if league == "NCAAM" else None


def _load_ncaam_best_pocket_per_game() -> dict | None:
    try:
        root = get_backtest_output_root("ncaam")
        if not root.exists():
            return None
        subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
        if not subdirs:
            return None
        latest = max(subdirs, key=lambda d: d.stat().st_mtime)
        p = latest / "ncaam_best_pocket_per_game.json"
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


_ncaam_best_pocket_doc = _load_ncaam_best_pocket_per_game() if league == "NCAAM" else None


def _load_ncaam_ranked_pocket_opportunities() -> dict | None:
    try:
        root = get_backtest_output_root("ncaam")
        if not root.exists():
            return None
        subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
        if not subdirs:
            return None
        latest = max(subdirs, key=lambda d: d.stat().st_mtime)
        p = latest / "ncaam_ranked_pocket_opportunities.json"
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


_ncaam_ranked_pocket_doc = _load_ncaam_ranked_pocket_opportunities() if league == "NCAAM" else None


def _load_ncaam_pocket_leaderboard_validation() -> dict | None:
    try:
        root = get_backtest_output_root("ncaam")
        if not root.exists():
            return None
        subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
        if not subdirs:
            return None
        latest = max(subdirs, key=lambda d: d.stat().st_mtime)
        p = latest / "ncaam_pocket_leaderboard_validation.json"
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


_ncaam_pocket_validation_doc = _load_ncaam_pocket_leaderboard_validation() if league == "NCAAM" else None


# Load overlay performance once: dynamic-only (no fallback to fixed/stale). Used for Execution Overlay table and Kelly Win%.
_overlay_buckets, _overlay_date = _load_execution_overlay_performance(league)
_overlay_table = _overlay_buckets
_overlay_win_rate_by_bucket = {row["Bucket"]: row["Win%"] for row in _overlay_table if row.get("Win%") is not None} if _overlay_table else None
# Status by bucket: only active buckets drive authoritative Kelly sizing.
_overlay_status_by_bucket = {row["Bucket"]: row.get("status") for row in _overlay_table} if _overlay_table else {}
# Display table: all rows, null Win%/ROI as "—", Status when present (per 039b schema).
_overlay_table_display = None
if _overlay_table:
    _overlay_table_display = []
    for row in _overlay_table:
        r = {
            "Bucket": row.get("Bucket", ""),
            "Games": row.get("Games", 0),
            "Win%": row["Win%"] if row.get("Win%") is not None else "—",
            "ROI": row["ROI"] if row.get("ROI") is not None else "—",
            "Explanation": row.get("Explanation", ""),
        }
        if row.get("status") is not None:
            r["Status"] = row["status"]
        _overlay_table_display.append(r)


def format_odds_snapshot_cst(odds_snapshot_utc: str) -> str:
    if not odds_snapshot_utc:
        return "N/A"

    try:
        dt_utc = datetime.fromisoformat(odds_snapshot_utc)
        dt_cst = dt_utc.astimezone(ZoneInfo("America/Chicago"))
        return dt_cst.strftime("%Y-%m-%d %I:%M:%S %p CST")
    except Exception:
        return "N/A"


def format_matchup_short(away_team: str, home_team: str) -> str:
    away_short = away_team.split()[-1][:3].upper()
    home_short = home_team.split()[-1][:3].upper()
    return f"{away_short} @ {home_short}"


def format_matchup_attribution(away_team: str, home_team: str) -> str:
    """Normalize matchup to match attribution report format for seamless tracking (e.g. 'Oregon @ Gonzaga')."""
    away = (away_team or "").strip()
    home = (home_team or "").strip()
    return f"{away} @ {home}"


def format_spread_text(home: str, away: str, spread_line, spread_pick: str) -> str:
    try:
        spread_line = float(spread_line)
    except (TypeError, ValueError):
        return "No Spread Pick"

    pick_raw = (spread_pick or "").strip()
    pick_norm = pick_raw.upper()
    home_norm = (home or "").strip().upper()
    away_norm = (away or "").strip().upper()

    if pick_norm == "HOME" or (pick_raw and pick_raw.upper() == home_norm):
        return f"{home} ({spread_line:+.1f})"
    if pick_norm == "AWAY" or (pick_raw and pick_raw.upper() == away_norm):
        return f"{away} ({-spread_line:+.1f})"
    return "No Spread Pick"


def _pocket_index_daily_games(daily_games: list) -> dict[str, dict]:
    """Key daily JSON games by id for Pocket ROI join (NBA + NCAAM id shapes)."""
    by_id: dict[str, dict] = {}
    for g in daily_games or []:
        if not isinstance(g, dict):
            continue
        ident = g.get("identity") if isinstance(g.get("identity"), dict) else {}
        gid = str(
            ident.get("game_id")
            or g.get("game_id")
            or g.get("canonical_game_id")
            or g.get("espn_game_id")
            or ""
        ).strip()
        if gid:
            by_id[gid] = g
    return by_id


def _pocket_matchup_from_daily_game(g: dict) -> str:
    ident = g.get("identity") if isinstance(g.get("identity"), dict) else {}
    away = (
        ident.get("away_team")
        or g.get("away_team_display")
        or g.get("away_team")
        or ""
    ).strip()
    home = (
        ident.get("home_team")
        or g.get("home_team_display")
        or g.get("home_team")
        or ""
    ).strip()
    if away or home:
        return format_matchup_attribution(away, home)
    return ""


def format_pocket_recommended_bet(
    row: dict,
    daily_by_id: dict[str, dict],
) -> str:
    """
    Plain-English wager for Pocket ROI tables (UI-only; no authority change).
    Spread: '{matchup}: Take {team} ({line})' via format_spread_text.
    Total: '{matchup}: OVER|UNDER ({total})' from market_state.total_last.
    """
    gid = str(row.get("game_id") or "").strip()
    g = daily_by_id.get(gid) if gid else None

    matchup = (row.get("matchup") or "").strip()
    if g is not None:
        mm = _pocket_matchup_from_daily_game(g)
        if mm:
            matchup = mm
    if not matchup:
        matchup = "Unknown matchup"

    mt = str(row.get("market_type") or "").strip().lower()
    pt = str(row.get("pocket_type") or "").strip().lower()
    if mt != "spread" and pt.endswith("_spread"):
        mt = "spread"
    if mt != "total" and pt.endswith("_total"):
        mt = "total"
    if mt not in ("spread", "total") and row.get("spread_pick") not in (None, ""):
        mt = "spread"

    pick_raw = row.get("pick")
    if pick_raw in (None, "") and row.get("spread_pick") not in (None, ""):
        pick_raw = row.get("spread_pick")
    if pick_raw in (None, "") and row.get("total_pick") not in (None, ""):
        pick_raw = row.get("total_pick")
    pick_s = str(pick_raw).strip() if pick_raw not in (None, "") else ""

    if g is None:
        suffix = " (no matching slate row)" if gid else ""
        return f"{matchup}: {pick_s or '—'}{suffix}"

    ident = g.get("identity") if isinstance(g.get("identity"), dict) else {}
    home = (
        ident.get("home_team")
        or g.get("home_team_display")
        or g.get("home_team")
        or ""
    ).strip()
    away = (
        ident.get("away_team")
        or g.get("away_team_display")
        or g.get("away_team")
        or ""
    ).strip()
    market = g.get("market_state") if isinstance(g.get("market_state"), dict) else {}

    if mt == "spread":
        sl = market.get("spread_home_last")
        inner = format_spread_text(home, away, sl, pick_s)
        if inner == "No Spread Pick":
            extra = " (line unavailable)" if sl in (None, "") else ""
            return f"{matchup}: Take {pick_s or '—'}{extra}"
        return f"{matchup}: Take {inner}"

    if mt == "total":
        tl = market.get("total_last")
        try:
            tl_f = float(tl)
            tl_disp = f"{tl_f:.1f}"
        except (TypeError, ValueError):
            tl_disp = "—"
        pu = pick_s.upper()
        if "OVER" in pu:
            side = "OVER"
        elif "UNDER" in pu:
            side = "UNDER"
        else:
            side = pick_s or "—"
        if tl_disp == "—":
            return f"{matchup}: {side} (total line unavailable)"
        return f"{matchup}: {side} ({tl_disp})"

    return f"{matchup}: {pick_s or '—'}"


def _pocket_roi_scalar_or_none(v):
    """
    Parse a cell value as numeric ROI; None if missing or non-numeric.
    Zero is returned as 0.0 (neutral styling: no tint / no emphasis color).
    """
    if v is None or v == "":
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, str):
        t = v.strip()
        if t in ("—", "", "nan", "NaN"):
            return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return x


def _pocket_roi_css_for_display_value(v) -> str:
    """
    Subtle ROI text color for diagnostic pocket tables (UI only).
    Positive → green, negative → red, zero / missing / non-numeric → neutral.
    """
    x = _pocket_roi_scalar_or_none(v)
    if x is None:
        return ""
    if x > 0:
        return "color: #15803d;"
    if x < 0:
        return "color: #b91c1c;"
    return ""


def _pocket_roi_row_background_css(v) -> str:
    """Subtle full-row background for main Pocket ROI boards (UI only)."""
    x = _pocket_roi_scalar_or_none(v)
    if x is None:
        return ""
    if x > 0:
        return "background-color: #ecfdf5;"
    if x < 0:
        return "background-color: #fef2f2;"
    return ""


def _st_pocket_main_roi_table(
    rows: list[dict],
    roi_column: str,
    *,
    use_container_width: bool = True,
) -> None:
    """Ranked / BPP boards: tint entire row by single ROI column (pandas Styler, axis=1)."""
    df = pd.DataFrame(rows)
    if df.empty:
        st.dataframe(df, use_container_width=use_container_width, hide_index=True)
        return
    if roi_column not in df.columns:
        st.dataframe(df, use_container_width=use_container_width, hide_index=True)
        return

    def _row_styles(row: pd.Series) -> pd.Series:
        css = _pocket_roi_row_background_css(row[roi_column])
        return pd.Series([css] * len(row), index=row.index)

    styler = df.style.apply(_row_styles, axis=1).hide(axis="index")
    st.dataframe(styler, use_container_width=use_container_width)


def _st_pocket_roi_table(
    rows: list[dict],
    roi_columns: list[str],
    *,
    use_container_width: bool = True,
) -> None:
    """Diagnostic / validation tables: ROI text color on selected columns only (pandas Styler)."""
    df = pd.DataFrame(rows)
    if df.empty:
        st.dataframe(df, use_container_width=use_container_width, hide_index=True)
        return
    subset = [c for c in roi_columns if c in df.columns]
    if not subset:
        st.dataframe(df, use_container_width=use_container_width, hide_index=True)
        return

    def _style_roi_series(s: pd.Series) -> pd.Series:
        return s.map(_pocket_roi_css_for_display_value)

    styler = df.style.apply(_style_roi_series, axis=0, subset=subset).hide(axis="index")
    st.dataframe(styler, use_container_width=use_container_width)


def calculate_full_kelly(win_pct: float, b: float) -> float:
    q = 1 - win_pct
    kelly = ((b * win_pct) - q) / b
    return max(kelly, 0)


def get_kelly_regime(g: dict, win_rate_by_bucket: dict | None = None):
    overlay = g.get("execution_overlay", {}) or {}

    if overlay.get("dual_sweet_spot"):
        name = "Dual Sweet Spot"
        w = win_rate_by_bucket.get(name) if win_rate_by_bucket is not None else None
        return name, (w if w is not None else DUAL_SWEET_SPOT_WIN_PCT)

    if overlay.get("spread_sweet_spot") and not overlay.get("spread_avoid"):
        name = "Spread Sweet Spot"
        w = win_rate_by_bucket.get(name) if win_rate_by_bucket is not None else None
        return name, (w if w is not None else SPREAD_SWEET_SPOT_WIN_PCT)

    if overlay.get("total_sweet_spot") and not overlay.get("total_avoid"):
        name = "Total Sweet Spot"
        w = win_rate_by_bucket.get(name) if win_rate_by_bucket is not None else None
        return name, (w if w is not None else TOTAL_SWEET_SPOT_WIN_PCT)

    return None, None



# --------------------------------------------------
# TOP ORDER
# 1. How to Read This Dashboard
# 2. Select Date
# 3. Last Odds Update
# 4. Kelly Bet Sizing Model
# 5. Everything else below unchanged
# --------------------------------------------------

with st.expander("📘 How to Read This Dashboard", expanded=False):
    st.markdown("---")

    st.markdown("## 🧾 Top Row Summary (Game Roll-Up Line)")

    st.write("Each game appears as a single summary line in this format:")

    st.code(
        "Dallas Mavericks @ Orlando Magic: Take Dallas Mavericks (+7.5) / OVER (229.5) 🟢 SPREAD+ — HIGH | 20%"
    )

    st.write("### What each part means")

    st.write(
        "• **Dallas Mavericks @ Orlando Magic** = the matchup\n"
        "• **Take Dallas Mavericks (+7.5)** = the model’s spread side\n"
        "• **OVER (229.5)** = the model’s total pick\n"
        "• **🟢 SPREAD+ / 🟢 TOTAL+ / 🟢 EXECUTION+ / 🔴 AVOID** = execution overlay badge\n"
        "• **HIGH / MODERATE / LOW / IGNORE** = confidence tier\n"
        "• **20%** = overall signal strength based on parlay edge score"
    )

    st.write(
        "The final percentage is **not** a win probability. "
        "It is a normalized strength indicator showing how far the model differs from the market."
    )

    st.markdown("---")

    st.markdown("## 🧠 What This Dashboard Is Doing")

    st.write(
        "This dashboard compares sportsbook lines to internal model projections. "
        "It looks for differences between the market and the model. "
        "Those differences are called **edges**."
    )

    st.write(
        "The page is designed to answer four questions quickly:\n"
        "1. What is the model pick?\n"
        "2. How strong is the signal?\n"
        "3. Does the game fall into a historically favorable execution regime?\n"
        "4. What would a full Kelly example stake look like?"
    )

    st.markdown("---")

    st.markdown("## 🟢 Execution Badges")

    st.write("Execution badges are rule-based overlays derived from backtested performance groups.")

    st.write(
        "• **🟢 SPREAD+** = the game qualifies as a Spread Sweet Spot\n"
        "• **🟢 TOTAL+** = the game qualifies as a Total Sweet Spot\n"
        "• **🟢 EXECUTION+** = the game qualifies as a Dual Sweet Spot\n"
        "• **🔴 AVOID** = the game falls into a historically unstable or unfavorable regime\n"
        "• **No badge** = neutral execution zone"
    )

    st.write(
        "These are not opinions. They are triggered by rule-based filters and historical backtesting."
    )

    st.markdown("---")

    st.markdown("## 🍀 Kelly BookieX (KBX) Bet Sizing System")

    st.write(
        "The Kelly section shows a **full Kelly example** using historical win rates from the current execution regime."
    )

    if _overlay_win_rate_by_bucket is not None:
        _dual_wr = _overlay_win_rate_by_bucket.get("Dual Sweet Spot", DUAL_SWEET_SPOT_WIN_PCT)
        _spread_wr = _overlay_win_rate_by_bucket.get("Spread Sweet Spot", SPREAD_SWEET_SPOT_WIN_PCT)
        _total_wr = _overlay_win_rate_by_bucket.get("Total Sweet Spot", TOTAL_SWEET_SPOT_WIN_PCT)
        st.write(
            "The current regime assumptions are:\n"
            f"• **Dual Sweet Spot** win rate = {_dual_wr:.3f}\n"
            f"• **Spread Sweet Spot** win rate = {_spread_wr:.3f}\n"
            f"• **Total Sweet Spot** win rate = {_total_wr:.3f}\n"
            f"• **Current bankroll** = ${current_bankroll:,} (set in sidebar)\n"
            "• **Odds assumption** = standard -110"
        )
    else:
        st.warning(
            "Dynamic overlay data is unavailable for the latest backtest. "
            "Regime win rates and Kelly sizing are not from current backtest data and should not be treated as authoritative."
        )
        st.write(
            f"• **Current bankroll** = ${current_bankroll:,} (set in sidebar)\n"
            "• **Odds assumption** = standard -110"
        )

    st.write(
        "This means different regimes can produce different Kelly bet sizes. "
        "A stronger historical regime will usually produce a larger suggested bet."
    )

    st.write(
        "The Kelly table is meant to help the user understand stake sizing. "
        "It is an example model, not a guarantee of future results."
    )

    st.write(
        "If a user wants to be more conservative, they should reduce **all** Kelly bets consistently "
        "instead of adjusting individual bets independently."
    )

    st.markdown("---")

    st.markdown("## ⏱ Last Odds Update")

    st.write(
        "**Last Odds Update** shows the most recent market snapshot timestamp available in the loaded daily file."
    )

    st.write(
        "The timestamp is converted from UTC to **CST** in the UI so it is easier to interpret."
    )

    st.write(
        "This helps answer a practical question: "
        "**How recent is the market data behind the current slate?**"
    )

    st.markdown("---")

    st.markdown("## 📊 Signal Strength Bars")

    st.write(
        "**Overall Signal** is the large colored bar. "
        "It is based on the combined parlay edge score."
    )

    st.write(
        "• **Green** = stronger structural alignment\n"
        "• **Orange** = moderate structural alignment\n"
        "• **Red** = weaker structural alignment"
    )

    st.write(
        "**Spread Strength** shows the size of the spread difference between model and market."
    )

    st.write(
        "**Total Strength** shows the size of the total difference between model and market."
    )

    st.write(
        "Bigger bars mean bigger model-vs-market gaps. "
        "That can indicate more opportunity, but it does not automatically mean higher probability."
    )

    st.markdown("---")

    st.markdown("## 📌 Key Numbers Explained")

    st.write(
        "• **Projected Margin (Home)** = how many points the model expects the home team to win by\n"
        "• **Spread Edge** = model spread projection vs sportsbook spread\n"
        "• **Projected Total** = how many total points the model expects\n"
        "• **Total Edge** = model total projection vs sportsbook total\n"
        "• **Parlay Edge Score** = combined spread and total gap used as a strength indicator"
    )

    st.markdown("---")

    st.markdown("## 🏗 Structure vs Decision")

    st.write(
        "• **Confidence Tier** measures how strongly internal models align\n"
        "• **Actionability** indicates whether the signal passed minimum execution thresholds\n"
        "• **Execution Overlay** shows whether the game lands in a favorable historical regime"
    )

    st.write(
        "These concepts are related, but they are not the same. "
        "A game can have a strong edge but still not land in the best historical execution bucket."
    )

    st.markdown("---")

    st.markdown("## 🧩 Model Details")

    st.write(
        "Each game includes nested model details showing how individual models voted on the spread and total."
    )

    st.write(
        "Model icons summarize alignment:\n"
        "• **🟢** = aligns with final spread and total\n"
        "• **🟡 T** = aligns on spread, differs on total\n"
        "• **🟡 S** = differs on spread, aligns on total\n"
        "• **🔴** = differs on both"
    )

    st.write(
        "This section is useful when you want to inspect why the final recommendation looks the way it does."
    )

    st.markdown("---")

    st.markdown("## ⚠ Important")

    st.write(
        "This dashboard is designed for identifying long-run statistical advantages, not certainty."
    )

    st.write(
        "Key reminders:\n"
        "• Large edges do not guarantee wins\n"
        "• Historical win rates are context, not promises\n"
        "• Kelly sizing is an example of bankroll logic, not a command\n"
        "• Conservative users should reduce all bet sizes consistently"
    )


selected_date = st.selectbox(
    "Select Date",
    sorted(date_map.keys(), reverse=True)
)

file_path = date_map[selected_date]
# Verification: exact file loaded (visible in Streamlit logs).
print(f"[BookieX Dashboard] Loading: {file_path.resolve()}")

with open(file_path, "r", encoding="utf-8") as f:
    data = json.load(f)

games = data.get("games", [])


def _resolve_nba_pocket_slate_rows(
    full_current_doc: dict | None,
    live_doc: dict | None,
    daily_games: list,
    selected_date_str: str,
) -> tuple[list, str]:
    """
    Rows for NBA pocket slate tables: prefer live artifact when its slate_date matches the
    dashboard-selected daily date; otherwise filter full pocket view by game_id order from
    the loaded daily JSON (same source as the main game list).
    """
    full_rows = list((full_current_doc or {}).get("games") or [])
    by_id = {str(r.get("game_id", "")).strip(): r for r in full_rows if str(r.get("game_id", "")).strip()}
    ordered_ids: list[str] = []
    seen: set[str] = set()
    for g in daily_games:
        if not isinstance(g, dict):
            continue
        ident = g.get("identity") if isinstance(g.get("identity"), dict) else {}
        gid = str(ident.get("game_id") or g.get("game_id") or "").strip()
        if gid and gid not in seen:
            seen.add(gid)
            ordered_ids.append(gid)
    selected_norm = str(selected_date_str).strip()
    live_date = (live_doc or {}).get("slate_date")
    live_date_norm = str(live_date).strip() if live_date is not None else ""
    live_games = live_doc.get("games") if isinstance(live_doc, dict) else None
    if (
        isinstance(live_games, list)
        and live_games
        and live_date_norm == selected_norm
    ):
        by_live = {str(r.get("game_id", "")).strip(): r for r in live_games if str(r.get("game_id", "")).strip()}
        rows = [by_live[gid] for gid in ordered_ids if gid in by_live]
        cap = (
            f"**Live slate:** `nba_live_game_pocket_view.json` — **{len(rows)}** games "
            f"(slate **{live_date_norm}**; order follows selected daily view)."
        )
        return rows, cap
    rows = [by_id[gid] for gid in ordered_ids if gid in by_id]
    if live_doc and live_date_norm and live_date_norm != selected_norm:
        cap = (
            f"**Selected slate (**{selected_norm}**):** **{len(rows)}** games from "
            f"`nba_current_game_pocket_view.json` (live artifact is for **{live_date_norm}**)."
        )
    elif not live_doc:
        cap = (
            f"**Selected slate (**{selected_norm}**):** **{len(rows)}** games filtered from "
            f"`nba_current_game_pocket_view.json` — no `nba_live_game_pocket_view.json` in latest backtest."
        )
    else:
        cap = (
            f"**Selected slate (**{selected_norm}**):** **{len(rows)}** games filtered from "
            f"`nba_current_game_pocket_view.json`."
        )
    return rows, cap


def _resolve_ncaam_pocket_slate_rows(
    full_current_doc: dict | None,
    live_doc: dict | None,
    daily_games: list,
    selected_date_str: str,
) -> tuple[list, str]:
    """
    NCAAM pocket slate rows: same resolution as NBA, but daily `game_id` may be
    `canonical_game_id` / `espn_game_id`; artifact filenames are ncaam_*.
    """
    full_rows = list((full_current_doc or {}).get("games") or [])
    by_id = {str(r.get("game_id", "")).strip(): r for r in full_rows if str(r.get("game_id", "")).strip()}
    ordered_ids: list[str] = []
    seen: set[str] = set()
    for g in daily_games:
        if not isinstance(g, dict):
            continue
        ident = g.get("identity") if isinstance(g.get("identity"), dict) else {}
        gid = str(
            ident.get("game_id")
            or g.get("game_id")
            or g.get("canonical_game_id")
            or g.get("espn_game_id")
            or ""
        ).strip()
        if gid and gid not in seen:
            seen.add(gid)
            ordered_ids.append(gid)
    selected_norm = str(selected_date_str).strip()
    live_date = (live_doc or {}).get("slate_date")
    live_date_norm = str(live_date).strip() if live_date is not None else ""
    live_games = live_doc.get("games") if isinstance(live_doc, dict) else None
    if (
        isinstance(live_games, list)
        and live_games
        and live_date_norm == selected_norm
    ):
        by_live = {str(r.get("game_id", "")).strip(): r for r in live_games if str(r.get("game_id", "")).strip()}
        rows = [by_live[gid] for gid in ordered_ids if gid in by_live]
        cap = (
            f"**Live slate:** `ncaam_live_game_pocket_view.json` — **{len(rows)}** games "
            f"(slate **{live_date_norm}**; order follows selected daily view)."
        )
        return rows, cap
    rows = [by_id[gid] for gid in ordered_ids if gid in by_id]
    if live_doc and live_date_norm and live_date_norm != selected_norm:
        cap = (
            f"**Selected slate (**{selected_norm}**):** **{len(rows)}** games from "
            f"`ncaam_current_game_pocket_view.json` (live artifact is for **{live_date_norm}**)."
        )
    elif not live_doc:
        cap = (
            f"**Selected slate (**{selected_norm}**):** **{len(rows)}** games filtered from "
            f"`ncaam_current_game_pocket_view.json` — no `ncaam_live_game_pocket_view.json` in latest backtest."
        )
    else:
        cap = (
            f"**Selected slate (**{selected_norm}**):** **{len(rows)}** games filtered from "
            f"`ncaam_current_game_pocket_view.json`."
        )
    return rows, cap


def _render_nba_pocket_roi_view(games: list, selected_date: str) -> None:
    """
    Pocket ROI View only: ranked best-pocket board, parlay, admin, diagnostic (+ validation).
    Uses module-level NBA pocket loaders; read-only; no authority changes.
    """
    st.markdown(
        "Per-game pocket summary from the **latest NBA backtest** live leaderboard. "
        "Does not change authority or sweet-spot logic. **MonkeyDarts_v2** is excluded."
    )
    if _nba_pockets_doc is None:
        st.info(
            "No pocket artifacts found. Run the NBA pipeline through backtest, then EXECUTION "
            "(`build_nba_model_pockets.py`) to write `nba_model_pockets.json`, "
                    "`nba_live_game_pocket_view.json`, `nba_live_pocket_leaderboard.json`, `nba_best_pocket_per_game.json`, "
                    "`nba_ranked_pocket_opportunities.json`, and companions into the latest "
            "`data/nba/backtests/backtest_*/` folder."
        )
        return

    st.caption(
        f"Backtest folder: `{(_nba_pockets_doc or {}).get('source_backtest_dir', '')}` "
        f"— generated {_nba_pockets_date or 'n/a'}"
    )
    formulas = (_nba_pockets_doc or {}).get("formulas") or {}

    def _lb_hci(d):
        if not isinstance(d, dict):
            return ""
        return (
            f"H{d.get('hot', 0)}/W{d.get('warm', 0)}/"
            f"C{d.get('cold', 0)}/I{d.get('insufficient', 0)}"
        )

    def _pocket_float(v):
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _combo_roi_sort_key(r: dict):
        roi = _pocket_float(r.get("roi"))
        gr = int(r.get("graded_games") or 0)
        sc = _pocket_float(r.get("leaderboard_score")) or 0.0
        return (roi if roi is not None else -1e18, gr, sc)

    def _pass_roi_sort_key(r: dict):
        pr = _pocket_float(r.get("best_pair_spread_roi"))
        csc = _pocket_float(r.get("spread_cluster_score")) or 0.0
        lb = _pocket_float(r.get("leaderboard_score")) or 0.0
        return (pr if pr is not None else -1e18, csc, lb)

    def _cold_sort_key(r: dict):
        w = _pocket_float(r.get("warning_score")) or 0.0
        lb = _pocket_float(r.get("leaderboard_score")) or 0.0
        return (w, lb)

    _lb_sf = _nba_live_pocket_leaderboard_doc
    _rpo_resolved = _nba_ranked_pocket_doc
    _bpp_resolved = _nba_best_pocket_doc
    if _lb_sf:
        try:
            from eng.execution.build_nba_model_pockets import (
                build_nba_best_pocket_per_game_from_leaderboard,
                build_nba_ranked_pocket_opportunities,
            )

            if _rpo_resolved is None:
                _pockets_list = list(((_nba_pockets_doc or {}).get("pockets") or []))
                _rpo_resolved = build_nba_ranked_pocket_opportunities(_lb_sf, _pockets_list)
            if _bpp_resolved is None:
                _bpp_resolved = build_nba_best_pocket_per_game_from_leaderboard(_lb_sf)
        except Exception:
            pass
    _opp_rows = [r for r in ((_rpo_resolved or {}).get("opportunities") or []) if isinstance(r, dict)]
    _games_bpp = list((_bpp_resolved or {}).get("games") or [])
    _parlay_eligible_n = sum(1 for r in _opp_rows if r.get("eligible_for_parlay"))
    _pocket_daily_by_id = _pocket_index_daily_games(games)

    def _rpo_row_is_spread(r: dict) -> bool:
        mt = str(r.get("market_type") or "").strip().lower()
        if mt == "spread":
            return True
        pt = str(r.get("pocket_type") or "").strip().lower()
        return pt.endswith("_spread")

    def _rpo_row_is_total(r: dict) -> bool:
        mt = str(r.get("market_type") or "").strip().lower()
        if mt == "total":
            return True
        pt = str(r.get("pocket_type") or "").strip().lower()
        return pt.endswith("_total")

    def _rpo_cell(val, empty="—"):
        if val is None or val == "":
            return empty
        return val

    def _rpo_num(val, fmt="{:.4f}", empty="—"):
        if val is None or val == "":
            return empty
        try:
            return fmt.format(float(val))
        except (TypeError, ValueError):
            return str(val)

    def _rpo_models_col(row: dict) -> str:
        mk = row.get("models_key")
        if mk is not None and str(mk).strip():
            return str(mk).strip()
        mn = row.get("model_name")
        if mn is not None and str(mn).strip():
            return str(mn).strip()
        return "—"

    def _rpo_sig_cell(row: dict) -> str:
        s = (row.get("state_signature") or "").strip()
        if not s:
            return "—"
        return (s[:56] + "…") if len(s) > 56 else s

    st.markdown("## Ranked Pocket Opportunities")
    st.caption(
        "One row per pocket candidate from **`nba_ranked_pocket_opportunities.json`** "
        "(rebuilt in-session from the live leaderboard + **`nba_model_pockets.json`** when that file is missing). "
        "Global sort: ROI → graded games → win rate. **Rank** is the global rank in that file. Read-only."
    )
    _pocket_filter_label = "All Pockets"
    if not _opp_rows:
        st.info(
            "No ranked pocket opportunity rows yet. Run **`build_nba_model_pockets.py`** so the latest backtest folder "
            "contains **`nba_ranked_pocket_opportunities.json`**, **`nba_live_pocket_leaderboard.json`**, and **`nba_model_pockets.json`**."
        )
    else:
        _pocket_filter_label = st.radio(
            "Pocket type filter",
            ("All Pockets", "Spread Only", "Total Only"),
            index=0,
            horizontal=True,
        )
        if _pocket_filter_label == "All Pockets":
            _opp_display = list(_opp_rows)
        elif _pocket_filter_label == "Spread Only":
            _opp_display = [r for r in _opp_rows if _rpo_row_is_spread(r)]
        else:
            _opp_display = [r for r in _opp_rows if _rpo_row_is_total(r)]

        if _pocket_filter_label == "All Pockets":
            st.caption(
                "Table shows **all** markets. **Best 2-leg parlay (v1)** still uses **spread-only** legs chosen from the "
                "**full** ranked list (global order); total rows here are not parlay candidates."
            )
        elif _pocket_filter_label == "Spread Only":
            st.caption(
                "Table shows **spread** rows only (`market_type` **spread**, or combo `pocket_type` ending in `_spread`). "
                "**Parlay (v1)** uses the same spread-only rules on the **full** ranked artifact (first two distinct eligible games "
                "in global order — not necessarily the first two rows in this filtered view)."
            )
        else:
            st.caption(
                "Table shows **total** rows only (`market_type` **total**, or combo `pocket_type` ending in `_total`). "
                "**Parlay (v1)** is spread-only — switch to **All Pockets** or **Spread Only** for parlay candidates."
            )

        if (
            _lb_sf
            and str(_lb_sf.get("slate_date") or "").strip()
            and str(_lb_sf.get("slate_date") or "").strip() != str(selected_date).strip()
        ):
            st.warning(
                f"Leaderboard / pocket slate **`{_lb_sf.get('slate_date')}`** ≠ selected **`{selected_date}`**."
            )
        if not _opp_display:
            st.info(f"No rows match **{_pocket_filter_label}** for this slate.")
        else:
            _st_pocket_main_roi_table(
                [
                    {
                        "Rank": r.get("rank"),
                        "Recommended Bet": format_pocket_recommended_bet(r, _pocket_daily_by_id),
                        "Game": _rpo_cell(r.get("matchup")),
                        "Pick": _rpo_cell(r.get("pick")),
                        "Pocket Type": _rpo_cell(r.get("pocket_type")),
                        "Pocket Models": _rpo_models_col(r),
                        "State Signature": _rpo_sig_cell(r),
                        "ROI": _rpo_num(r.get("roi")),
                        "Win Rate": _rpo_num(r.get("win_rate")),
                        "Graded Games": r.get("graded_games") if r.get("graded_games") is not None else "—",
                        "Why": (r.get("reason") or "")[:280],
                        "Parlay Eligible": r.get("eligible_for_parlay"),
                    }
                    for r in _opp_display
                ],
                "ROI",
            )

    with st.expander("Best pocket per game (secondary summary)", expanded=False):
        st.caption(
            "One row per live-slate game from **`nba_best_pocket_per_game.json`**. Collapsed summary; "
            "use **Ranked Pocket Opportunities** above for the full ranked list."
        )
        if not _games_bpp:
            st.caption("No rows.")
        else:
            def _bpp_cell(val, empty="—"):
                if val is None or val == "":
                    return empty
                return val

            def _bpp_num(val, fmt="{:.4f}", empty="—"):
                if val is None or val == "":
                    return empty
                try:
                    return fmt.format(float(val))
                except (TypeError, ValueError):
                    return str(val)

            def _bpp_models_col(row: dict) -> str:
                mk = _bpp_cell(row.get("best_reference_models_key"))
                sig = (row.get("best_reference_state_signature") or "").strip()
                if not sig:
                    return mk
                sig_trim = (sig[:32] + "…") if len(sig) > 32 else sig
                if mk == "—":
                    return sig_trim
                return f"{mk} · {sig_trim}"

            def _bpp_graded_cell(row: dict):
                v = row.get("best_reference_graded_games")
                if v is None:
                    v = row.get("best_pocket_graded_games")
                if v is None or v == "":
                    return "—"
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return "—"

            _st_pocket_main_roi_table(
                [
                    {
                        "Rank": g.get("rank"),
                        "Recommended Bet": format_pocket_recommended_bet(g, _pocket_daily_by_id),
                        "Game": _bpp_cell(g.get("matchup")),
                        "Pick": _bpp_cell(g.get("spread_pick")),
                        "Best Pocket Type": _bpp_cell(g.get("best_pocket_type")),
                        "Pocket Models": _bpp_models_col(g),
                        "Pocket ROI": _bpp_num(
                            g.get("best_reference_roi")
                            if g.get("best_reference_roi") is not None
                            else g.get("best_pocket_roi")
                        ),
                        "Pocket Win Rate": _bpp_num(
                            g.get("best_reference_win_rate")
                            if g.get("best_reference_win_rate") is not None
                            else g.get("best_pocket_win_rate")
                        ),
                        "Pocket Games": _bpp_graded_cell(g),
                        "Why": (g.get("reason") or "")[:280],
                        "Parlay Eligible": g.get("eligible_for_parlay"),
                    }
                    for g in _games_bpp
                ],
                "Pocket ROI",
            )

    st.markdown("## Best 2-leg parlay (positive ROI only)")
    if not _opp_rows:
        st.caption("No ranked opportunities loaded — parlay unavailable.")
    elif _pocket_filter_label == "Total Only":
        st.caption(
            "**Parlay (v1) is spread-only.** The table above is total-market only; switch to **All Pockets** or **Spread Only** "
            "to see parlay candidates."
        )
        st.info(
            "Parlay builder is spread-only in v1. Switch to All Pockets or Spread Only to view parlay candidates."
        )
    else:
        st.caption(
            "Walks the **full** ranked opportunity list in global order (same as **`nba_ranked_pocket_opportunities.json`**). "
            "First **two** distinct **`game_id`** with **`eligible_for_parlay`** — spread-only, positive historical ROI. "
            "If **All Pockets** is selected, total rows in the table are ignored for this builder."
        )
        _seen_parlay_gid: set[str] = set()
        _parlay_legs: list[dict] = []
        for r in _opp_rows:
            if not r.get("eligible_for_parlay"):
                continue
            gid = str(r.get("game_id") or "").strip()
            if not gid or gid in _seen_parlay_gid:
                continue
            _seen_parlay_gid.add(gid)
            _parlay_legs.append(r)
            if len(_parlay_legs) >= 2:
                break
        if len(_parlay_legs) < 2:
            st.info("No positive-ROI 2-leg parlay exposed on this slate.")
        else:
            _r1, _r2 = _parlay_legs[0], _parlay_legs[1]
            _bet1 = format_pocket_recommended_bet(_r1, _pocket_daily_by_id)
            _bet2 = format_pocket_recommended_bet(_r2, _pocket_daily_by_id)
            st.markdown(
                f"**Leg 1 —** {_bet1}  \n"
                f"*{_r1.get('pocket_type')} · historical ROI {_r1.get('roi')}*"
            )
            st.markdown(
                f"**Leg 2 —** {_bet2}  \n"
                f"*{_r2.get('pocket_type')} · historical ROI {_r2.get('roi')}*"
            )
            st.caption(
                f"**Summary:** top two distinct-game spread opportunities by **global** ranked ROI "
                f"(ROIs {_r1.get('roi')} / {_r2.get('roi')} — not parlay EV math)."
            )
    st.warning(
        "**For entertainment / small-stake use only** — not a guaranteed edge, not sizing advice, "
        "not a substitute for authority logic. No bets placed or automated."
    )

    _adm_rows, _adm_cap = _resolve_nba_pocket_slate_rows(
        _nba_current_pockets_doc,
        _nba_live_pockets_doc,
        games,
        selected_date,
    )
    _adm_bt = str((_nba_pockets_doc or {}).get("source_backtest_dir") or "")
    if _lb_sf:
        _adm_bt = str(_lb_sf.get("source_backtest_dir") or _adm_bt)
    _spread_h = _spread_w = _spread_c = _spread_i = 0
    if _lb_sf:
        for _sr in _lb_sf.get("strongest_spread_cluster") or []:
            if not isinstance(_sr, dict):
                continue
            _spa = _sr.get("spread_pocket_alignment") or {}
            if isinstance(_spa, dict):
                _spread_h += int(_spa.get("hot") or 0)
                _spread_w += int(_spa.get("warm") or 0)
                _spread_c += int(_spa.get("cold") or 0)
                _spread_i += int(_spa.get("insufficient") or 0)
    _lb_mismatch = False
    if _lb_sf:
        _gct = int(_lb_sf.get("game_count") or 0)
        _lb_mismatch = _gct > 0 and _gct != len(_adm_rows)
    with st.expander("NBA pocket admin / debug (read-only)", expanded=False):
        st.code(
            "source_backtest_dir: "
            + str(_adm_bt or "—")
            + "\nsource_daily_view_path (leaderboard): "
            + str(((_lb_sf or {}).get("source_daily_view_path")) or "—")
            + "\nselected_date: "
            + str(selected_date)
            + "\nleaderboard slate_date: "
            + str(((_lb_sf or {}).get("slate_date")) or "—")
            + "\nleaderboard game_count: "
            + str(((_lb_sf or {}).get("game_count")) if _lb_sf else "—")
            + "\nslate_table_rows: "
            + str(len(_adm_rows))
            + "\nspread_align_sums_H_W_C_I: "
            + f"{_spread_h},{_spread_w},{_spread_c},{_spread_i}"
            + "\neligible_parlay_pool_count (positive ROI + pick, ranked opportunities): "
            + str(_parlay_eligible_n)
            + "\nranked_opportunity_rows: "
            + str(len(_opp_rows))
            + "\nnba_ranked_pocket_opportunities.json: "
            + (
                "loaded"
                if _nba_ranked_pocket_doc
                else "missing (rebuilt in-session if leaderboard + pockets present)"
            )
            + "\nnba_best_pocket_per_game.json: "
            + ("loaded" if _nba_best_pocket_doc else "missing (rebuilt in-session if leaderboard present)")
            + "\ngame_count_vs_slate_mismatch: "
            + ("yes" if _lb_mismatch else "no"),
            language=None,
        )
        st.markdown("**Slate resolution (live artifact vs fallback)**")
        st.markdown(_adm_cap)
        if _lb_sf and str(_lb_sf.get("slate_date") or "").strip() != str(selected_date).strip():
            st.warning("Leaderboard `slate_date` ≠ selected date — treat live tables as cross-dated.")

    with st.expander("Detailed diagnostic pocket tables (secondary)", expanded=False):
        if formulas:
            with st.expander("Formulas & thresholds", expanded=False):
                st.json(formulas)
        st.subheader("Live slate — spread-first diagnostic (secondary)")
        st.caption(
            "`nba_pocket_leaderboard_validation.json` motivated spread cluster / triple spread / pass / cold — "
            "see **Historical leaderboard validation** at the bottom of this expander."
        )
        st.caption(
            "Tables sort by **ROI → graded games → leaderboard score** (display only)."
        )
        if not _lb_sf:
            st.caption(
                "Load `nba_live_pocket_leaderboard.json` (run `build_nba_model_pockets.py`) to populate these tables."
            )
        else:
            _sf_slate = str(_lb_sf.get("slate_date") or "").strip()
            if _sf_slate and _sf_slate != str(selected_date).strip():
                st.warning(
                    f"Leaderboard slate **`{_sf_slate}`** ≠ selected **`{selected_date}`** — rows may not match today’s table."
                )

            _bts_raw = [r for r in (_lb_sf.get("best_triple_spread") or []) if isinstance(r, dict)]
            _bps_raw = [r for r in (_lb_sf.get("best_pair_spread") or []) if isinstance(r, dict)]
            _triple_by_gid = {
                str(r.get("game_id") or "").strip(): r for r in _bts_raw if str(r.get("game_id") or "").strip()
            }
            _pair_by_gid = {
                str(r.get("game_id") or "").strip(): r for r in _bps_raw if str(r.get("game_id") or "").strip()
            }

            st.markdown("##### 1 · Strongest spread cluster (ROI-informed sort via matched combo pockets)")
            _ssc_sf = [r for r in (_lb_sf.get("strongest_spread_cluster") or []) if isinstance(r, dict)]
            _ssc_rows_out = []
            for r in _ssc_sf:
                gid = str(r.get("game_id") or "").strip()
                tr = _triple_by_gid.get(gid)
                pr = _pair_by_gid.get(gid)
                tr_roi = _pocket_float(tr.get("roi")) if tr else None
                pr_roi = _pocket_float(pr.get("roi")) if pr else None
                tr_g = int(tr.get("graded_games") or 0) if tr else 0
                pr_g = int(pr.get("graded_games") or 0) if pr else 0
                proxy_roi = tr_roi if tr_roi is not None else pr_roi
                max_graded = max(tr_g, pr_g) if (tr or pr) else 0
                _ssc_rows_out.append(
                    {
                        "_sort": (
                            proxy_roi if proxy_roi is not None else -1e18,
                            max_graded,
                            _pocket_float(r.get("cluster_score")) or 0.0,
                        ),
                        "ui rank": 0,
                        "game_id": r.get("game_id"),
                        "matchup": r.get("matchup"),
                        "spread pick": r.get("spread_pick"),
                        "spread align H/W/C/I": _lb_hci(r.get("spread_pocket_alignment")),
                        "cluster score": r.get("cluster_score"),
                        "hist triple ROI": tr_roi,
                        "hist triple graded": tr_g if tr else None,
                        "hist pair ROI": pr_roi,
                        "hist pair graded": pr_g if pr else None,
                        "leaderboard score": r.get("leaderboard_score"),
                        "summary": (r.get("reason") or "")[:100],
                    }
                )
            _ssc_rows_out.sort(key=lambda x: x["_sort"], reverse=True)
            for i, row in enumerate(_ssc_rows_out, start=1):
                row["ui rank"] = i
                del row["_sort"]
            if _ssc_rows_out:
                _st_pocket_roi_table(_ssc_rows_out, ["hist triple ROI", "hist pair ROI"])
            else:
                st.caption("No rows.")

            st.markdown("##### 2 · Best triple spread combo (historical pocket stats, ROI-first)")
            _bts_sf = sorted(_bts_raw, key=_combo_roi_sort_key, reverse=True)
            if _bts_sf:
                _st_pocket_roi_table(
                    [
                        {
                            "ui rank": i,
                            "game_id": r.get("game_id"),
                            "matchup": r.get("matchup"),
                            "spread pick": r.get("spread_pick"),
                            "triple combo (models)": r.get("models_key"),
                            "pocket ROI": r.get("roi"),
                            "pocket Win%": r.get("win_rate"),
                            "pocket graded": r.get("graded_games"),
                            "combo pocket state": r.get("combo_state"),
                            "spread align": _lb_hci(r.get("spread_pocket_alignment")),
                            "leaderboard score": r.get("leaderboard_score"),
                            "summary": (r.get("reason") or "")[:100],
                        }
                        for i, r in enumerate(_bts_sf, start=1)
                    ],
                    ["pocket ROI"],
                )
            else:
                st.caption("No triple spread matches on this slate.")

            st.markdown("##### 3 · Best pair spread combo (historical pocket stats, ROI-first)")
            _bps_sf = sorted(_bps_raw, key=_combo_roi_sort_key, reverse=True)
            if _bps_sf:
                _st_pocket_roi_table(
                    [
                        {
                            "ui rank": i,
                            "game_id": r.get("game_id"),
                            "matchup": r.get("matchup"),
                            "spread pick": r.get("spread_pick"),
                            "pair combo (models)": r.get("models_key"),
                            "pocket ROI": r.get("roi"),
                            "pocket Win%": r.get("win_rate"),
                            "pocket graded": r.get("graded_games"),
                            "combo pocket state": r.get("combo_state"),
                            "spread align": _lb_hci(r.get("spread_pocket_alignment")),
                            "leaderboard score": r.get("leaderboard_score"),
                            "summary": (r.get("reason") or "")[:100],
                        }
                        for i, r in enumerate(_bps_sf, start=1)
                    ],
                    ["pocket ROI"],
                )
            else:
                st.caption("No pair spread matches on this slate.")

            st.markdown("##### 4 · Pass candidates (hist. pair ROI → cluster score)")
            _pc_sf = sorted(
                [r for r in (_lb_sf.get("pass_candidates") or []) if isinstance(r, dict)],
                key=_pass_roi_sort_key,
                reverse=True,
            )
            if _pc_sf:
                _st_pocket_roi_table(
                    [
                        {
                            "ui rank": i,
                            "game_id": r.get("game_id"),
                            "matchup": r.get("matchup"),
                            "spread pick": r.get("spread_pick"),
                            "spread cluster score": r.get("spread_cluster_score"),
                            "hist. best-pair spread ROI": r.get("best_pair_spread_roi"),
                            "leaderboard score": r.get("leaderboard_score"),
                            "spread align": _lb_hci(r.get("spread_pocket_alignment")),
                            "summary": (r.get("reason") or "")[:120],
                        }
                        for i, r in enumerate(_pc_sf, start=1)
                    ],
                    ["hist. best-pair spread ROI"],
                )
            else:
                st.caption("No pass-flagged games on this slate.")

            st.markdown("##### 5 · Cold cluster warnings (warning score; no per-game ROI)")
            _ccw_sf = sorted(
                [r for r in (_lb_sf.get("cold_cluster_warnings") or []) if isinstance(r, dict)],
                key=_cold_sort_key,
                reverse=True,
            )
            if _ccw_sf:
                st.dataframe(
                    [
                        {
                            "ui rank": i,
                            "game_id": r.get("game_id"),
                            "matchup": r.get("matchup"),
                            "warning score": r.get("warning_score"),
                            "spread align": _lb_hci(r.get("spread_pocket_alignment")),
                            "leaderboard score": r.get("leaderboard_score"),
                            "summary": (r.get("reason") or "")[:100],
                        }
                        for i, r in enumerate(_ccw_sf, start=1)
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("No rows.")

        st.markdown("---")
        st.subheader("Historical leaderboard validation (read-only)")
        _val = _nba_pocket_validation_doc
        if not _val:
            st.caption(
                "No `nba_pocket_leaderboard_validation.json` in latest backtest — run `build_nba_model_pockets.py`."
            )
        else:
            st.caption(
                f"Backtest **`{_val.get('source_backtest_dir', '')}`** · "
                f"{_val.get('n_games_with_models_blob', 0)} games with `models` (of {_val.get('n_backtest_rows', 0)} rows). "
                "Tercile splits vs full sample; -110 ROI on graded legs."
            )

            def _vrow(label: str, d: dict | None) -> dict:
                if not isinstance(d, dict):
                    return {"metric": label, "graded": None, "Win%": None, "ROI": None, "notes": "—"}
                return {
                    "metric": label,
                    "graded": d.get("graded_games"),
                    "Win%": d.get("win_rate"),
                    "ROI": d.get("roi"),
                    "notes": (d.get("sample_notes") or "")[:48],
                }

            _ps = _val.get("pair_spread_top_vs_all") or {}
            _cl = _val.get("spread_cluster_strong_vs_weak") or {}
            _pv = _val.get("pass_vs_non_pass") or {}
            _sum_spread = [
                _vrow("Pair spread combo — top tercile (score)", _ps.get("top_tercile_pair_spread_combo")),
                _vrow("Pair spread combo — all w/ pocket", _ps.get("all_with_pair_spread_combo")),
                _vrow("Authority spread — top pair tercile games", _ps.get("authority_spread_top_pair_tercile")),
                _vrow("Triple spread combo — top tercile", (_val.get("triple_spread_top_vs_all") or {}).get("top_tercile_triple_spread_combo")),
                _vrow("Triple spread combo — all w/ pocket", (_val.get("triple_spread_top_vs_all") or {}).get("all_with_triple_spread_combo")),
                _vrow("Cluster — strong (auth spread)", _cl.get("strong_spread_cluster_authority_spread")),
                _vrow("Cluster — weak (auth spread)", _cl.get("weak_spread_cluster_authority_spread")),
                _vrow("Pass candidates (auth spread)", _pv.get("pass_candidates_authority_spread")),
                _vrow("Non-pass (auth spread)", _pv.get("non_pass_authority_spread")),
            ]
            st.markdown("##### Spread / cluster / pass (historical)")
            _st_pocket_roi_table(_sum_spread, ["ROI"])

            _tot = _val.get("totals_if_sufficient") or {}
            _trows = []
            if isinstance(_tot.get("pair_total_top_tercile_combo"), dict):
                _trows.append(_vrow("Pair total combo — top tercile", _tot.get("pair_total_top_tercile_combo")))
                _trows.append(_vrow("Pair total combo — all", _tot.get("pair_total_all_with_pocket_combo")))
            if isinstance(_tot.get("triple_total_top_tercile_combo"), dict):
                _trows.append(_vrow("Triple total combo — top tercile", _tot.get("triple_total_top_tercile_combo")))
                _trows.append(_vrow("Triple total combo — all", _tot.get("triple_total_all_with_pocket_combo")))
            if _trows:
                st.markdown("##### Totals (historical, n≥30 gate)")
                _st_pocket_roi_table(_trows, ["ROI"])
            elif _tot.get("pair_total", {}).get("skipped") or _tot.get("triple_total", {}).get("skipped"):
                st.caption("Totals validation skipped (insufficient sample per artifact rules).")

            _cw = _val.get("cold_warning_high_vs_low") or {}
            _wrows = [
                _vrow("Cold warning HIGH tercile (auth spread)", _cw.get("high_warning_authority_spread")),
                _vrow("Cold warning LOW tercile (auth spread)", _cw.get("low_warning_authority_spread")),
            ]
            st.markdown("##### Cold-warning terciles (historical)")
            _st_pocket_roi_table(_wrows, ["ROI"])

def _render_ncaam_pocket_roi_view(games: list, selected_date: str) -> None:
    """
    Pocket ROI View only: ranked best-pocket board, parlay, admin, diagnostic (+ validation).
    Uses module-level NCAAM pocket loaders; read-only; no authority changes.
    """
    st.markdown(
        "Per-game pocket summary from the **latest NCAAM backtest** live leaderboard. "
        "Does not change authority or sweet-spot logic. All NCAAM runner models are included (avg, momentum, market pressure)."
    )
    if _ncaam_pockets_doc is None:
        st.info(
            "No pocket artifacts found. Run the NCAAM pipeline through backtest, then "
            "**`build_ncaam_model_pockets.py`** to write `ncaam_model_pockets.json`, "
                    "`ncaam_live_game_pocket_view.json`, `ncaam_live_pocket_leaderboard.json`, `ncaam_best_pocket_per_game.json`, "
                    "`ncaam_ranked_pocket_opportunities.json`, and companions into the latest "
            "`data/ncaam/backtests/backtest_*/` folder."
        )
        return

    st.caption(
        f"Backtest folder: `{(_ncaam_pockets_doc or {}).get('source_backtest_dir', '')}` "
        f"— generated {_ncaam_pockets_date or 'n/a'}"
    )
    formulas = (_ncaam_pockets_doc or {}).get("formulas") or {}

    def _lb_hci(d):
        if not isinstance(d, dict):
            return ""
        return (
            f"H{d.get('hot', 0)}/W{d.get('warm', 0)}/"
            f"C{d.get('cold', 0)}/I{d.get('insufficient', 0)}"
        )

    def _pocket_float(v):
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _combo_roi_sort_key(r: dict):
        roi = _pocket_float(r.get("roi"))
        gr = int(r.get("graded_games") or 0)
        sc = _pocket_float(r.get("leaderboard_score")) or 0.0
        return (roi if roi is not None else -1e18, gr, sc)

    def _pass_roi_sort_key(r: dict):
        pr = _pocket_float(r.get("best_pair_spread_roi"))
        csc = _pocket_float(r.get("spread_cluster_score")) or 0.0
        lb = _pocket_float(r.get("leaderboard_score")) or 0.0
        return (pr if pr is not None else -1e18, csc, lb)

    def _cold_sort_key(r: dict):
        w = _pocket_float(r.get("warning_score")) or 0.0
        lb = _pocket_float(r.get("leaderboard_score")) or 0.0
        return (w, lb)

    _lb_sf = _ncaam_live_pocket_leaderboard_doc
    _rpo_resolved = _ncaam_ranked_pocket_doc
    _bpp_resolved = _ncaam_best_pocket_doc
    if _lb_sf:
        try:
            from eng.execution.build_ncaam_model_pockets import (
                build_ncaam_best_pocket_per_game_from_leaderboard,
                build_ncaam_ranked_pocket_opportunities,
            )

            if _rpo_resolved is None:
                _pockets_list = list(((_ncaam_pockets_doc or {}).get("pockets") or []))
                _rpo_resolved = build_ncaam_ranked_pocket_opportunities(_lb_sf, _pockets_list)
            if _bpp_resolved is None:
                _bpp_resolved = build_ncaam_best_pocket_per_game_from_leaderboard(_lb_sf)
        except Exception:
            pass
    _opp_rows = [r for r in ((_rpo_resolved or {}).get("opportunities") or []) if isinstance(r, dict)]
    _games_bpp = list((_bpp_resolved or {}).get("games") or [])
    _parlay_eligible_n = sum(1 for r in _opp_rows if r.get("eligible_for_parlay"))
    _pocket_daily_by_id = _pocket_index_daily_games(games)

    def _rpo_row_is_spread(r: dict) -> bool:
        mt = str(r.get("market_type") or "").strip().lower()
        if mt == "spread":
            return True
        pt = str(r.get("pocket_type") or "").strip().lower()
        return pt.endswith("_spread")

    def _rpo_row_is_total(r: dict) -> bool:
        mt = str(r.get("market_type") or "").strip().lower()
        if mt == "total":
            return True
        pt = str(r.get("pocket_type") or "").strip().lower()
        return pt.endswith("_total")

    def _rpo_cell(val, empty="—"):
        if val is None or val == "":
            return empty
        return val

    def _rpo_num(val, fmt="{:.4f}", empty="—"):
        if val is None or val == "":
            return empty
        try:
            return fmt.format(float(val))
        except (TypeError, ValueError):
            return str(val)

    def _rpo_models_col(row: dict) -> str:
        mk = row.get("models_key")
        if mk is not None and str(mk).strip():
            return str(mk).strip()
        mn = row.get("model_name")
        if mn is not None and str(mn).strip():
            return str(mn).strip()
        return "—"

    def _rpo_sig_cell(row: dict) -> str:
        s = (row.get("state_signature") or "").strip()
        if not s:
            return "—"
        return (s[:56] + "…") if len(s) > 56 else s

    st.markdown("## Ranked Pocket Opportunities")
    st.caption(
        "One row per pocket candidate from **`ncaam_ranked_pocket_opportunities.json`** "
        "(rebuilt in-session from the live leaderboard + **`ncaam_model_pockets.json`** when that file is missing). "
        "Global sort: ROI → graded games → win rate. **Rank** is the global rank in that file. Read-only."
    )
    _pocket_filter_label = "All Pockets"
    if not _opp_rows:
        st.info(
            "No ranked pocket opportunity rows yet. Run **`build_ncaam_model_pockets.py`** so the latest backtest folder "
            "contains **`ncaam_ranked_pocket_opportunities.json`**, **`ncaam_live_pocket_leaderboard.json`**, and **`ncaam_model_pockets.json`**."
        )
    else:
        _pocket_filter_label = st.radio(
            "Pocket type filter",
            ("All Pockets", "Spread Only", "Total Only"),
            index=0,
            horizontal=True,
        )
        if _pocket_filter_label == "All Pockets":
            _opp_display = list(_opp_rows)
        elif _pocket_filter_label == "Spread Only":
            _opp_display = [r for r in _opp_rows if _rpo_row_is_spread(r)]
        else:
            _opp_display = [r for r in _opp_rows if _rpo_row_is_total(r)]

        if _pocket_filter_label == "All Pockets":
            st.caption(
                "Table shows **all** markets. **Best 2-leg parlay (v1)** still uses **spread-only** legs chosen from the "
                "**full** ranked list (global order); total rows here are not parlay candidates."
            )
        elif _pocket_filter_label == "Spread Only":
            st.caption(
                "Table shows **spread** rows only (`market_type` **spread**, or combo `pocket_type` ending in `_spread`). "
                "**Parlay (v1)** uses the same spread-only rules on the **full** ranked artifact (first two distinct eligible games "
                "in global order — not necessarily the first two rows in this filtered view)."
            )
        else:
            st.caption(
                "Table shows **total** rows only (`market_type` **total**, or combo `pocket_type` ending in `_total`). "
                "**Parlay (v1)** is spread-only — switch to **All Pockets** or **Spread Only** for parlay candidates."
            )

        if (
            _lb_sf
            and str(_lb_sf.get("slate_date") or "").strip()
            and str(_lb_sf.get("slate_date") or "").strip() != str(selected_date).strip()
        ):
            st.warning(
                f"Leaderboard / pocket slate **`{_lb_sf.get('slate_date')}`** ≠ selected **`{selected_date}`**."
            )
        if not _opp_display:
            st.info(f"No rows match **{_pocket_filter_label}** for this slate.")
        else:
            _st_pocket_main_roi_table(
                [
                    {
                        "Rank": r.get("rank"),
                        "Recommended Bet": format_pocket_recommended_bet(r, _pocket_daily_by_id),
                        "Game": _rpo_cell(r.get("matchup")),
                        "Pick": _rpo_cell(r.get("pick")),
                        "Pocket Type": _rpo_cell(r.get("pocket_type")),
                        "Pocket Models": _rpo_models_col(r),
                        "State Signature": _rpo_sig_cell(r),
                        "ROI": _rpo_num(r.get("roi")),
                        "Win Rate": _rpo_num(r.get("win_rate")),
                        "Graded Games": r.get("graded_games") if r.get("graded_games") is not None else "—",
                        "Why": (r.get("reason") or "")[:280],
                        "Parlay Eligible": r.get("eligible_for_parlay"),
                    }
                    for r in _opp_display
                ],
                "ROI",
            )

    with st.expander("Best pocket per game (secondary summary)", expanded=False):
        st.caption(
            "One row per live-slate game from **`ncaam_best_pocket_per_game.json`**. Collapsed summary; "
            "use **Ranked Pocket Opportunities** above for the full ranked list."
        )
        if not _games_bpp:
            st.caption("No rows.")
        else:
            def _bpp_cell(val, empty="—"):
                if val is None or val == "":
                    return empty
                return val

            def _bpp_num(val, fmt="{:.4f}", empty="—"):
                if val is None or val == "":
                    return empty
                try:
                    return fmt.format(float(val))
                except (TypeError, ValueError):
                    return str(val)

            def _bpp_models_col(row: dict) -> str:
                mk = _bpp_cell(row.get("best_reference_models_key"))
                sig = (row.get("best_reference_state_signature") or "").strip()
                if not sig:
                    return mk
                sig_trim = (sig[:32] + "…") if len(sig) > 32 else sig
                if mk == "—":
                    return sig_trim
                return f"{mk} · {sig_trim}"

            def _bpp_graded_cell(row: dict):
                v = row.get("best_reference_graded_games")
                if v is None:
                    v = row.get("best_pocket_graded_games")
                if v is None or v == "":
                    return "—"
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return "—"

            _st_pocket_main_roi_table(
                [
                    {
                        "Rank": g.get("rank"),
                        "Recommended Bet": format_pocket_recommended_bet(g, _pocket_daily_by_id),
                        "Game": _bpp_cell(g.get("matchup")),
                        "Pick": _bpp_cell(g.get("spread_pick")),
                        "Best Pocket Type": _bpp_cell(g.get("best_pocket_type")),
                        "Pocket Models": _bpp_models_col(g),
                        "Pocket ROI": _bpp_num(
                            g.get("best_reference_roi")
                            if g.get("best_reference_roi") is not None
                            else g.get("best_pocket_roi")
                        ),
                        "Pocket Win Rate": _bpp_num(
                            g.get("best_reference_win_rate")
                            if g.get("best_reference_win_rate") is not None
                            else g.get("best_pocket_win_rate")
                        ),
                        "Pocket Games": _bpp_graded_cell(g),
                        "Why": (g.get("reason") or "")[:280],
                        "Parlay Eligible": g.get("eligible_for_parlay"),
                    }
                    for g in _games_bpp
                ],
                "Pocket ROI",
            )

    st.markdown("## Best 2-leg parlay (positive ROI only)")
    if not _opp_rows:
        st.caption("No ranked opportunities loaded — parlay unavailable.")
    elif _pocket_filter_label == "Total Only":
        st.caption(
            "**Parlay (v1) is spread-only.** The table above is total-market only; switch to **All Pockets** or **Spread Only** "
            "to see parlay candidates."
        )
        st.info(
            "Parlay builder is spread-only in v1. Switch to All Pockets or Spread Only to view parlay candidates."
        )
    else:
        st.caption(
            "Walks the **full** ranked opportunity list in global order (same as **`ncaam_ranked_pocket_opportunities.json`**). "
            "First **two** distinct **`game_id`** with **`eligible_for_parlay`** — spread-only, positive historical ROI. "
            "If **All Pockets** is selected, total rows in the table are ignored for this builder."
        )
        _seen_parlay_gid: set[str] = set()
        _parlay_legs: list[dict] = []
        for r in _opp_rows:
            if not r.get("eligible_for_parlay"):
                continue
            gid = str(r.get("game_id") or "").strip()
            if not gid or gid in _seen_parlay_gid:
                continue
            _seen_parlay_gid.add(gid)
            _parlay_legs.append(r)
            if len(_parlay_legs) >= 2:
                break
        if len(_parlay_legs) < 2:
            st.info("No positive-ROI 2-leg parlay exposed on this slate.")
        else:
            _r1, _r2 = _parlay_legs[0], _parlay_legs[1]
            _bet1 = format_pocket_recommended_bet(_r1, _pocket_daily_by_id)
            _bet2 = format_pocket_recommended_bet(_r2, _pocket_daily_by_id)
            st.markdown(
                f"**Leg 1 —** {_bet1}  \n"
                f"*{_r1.get('pocket_type')} · historical ROI {_r1.get('roi')}*"
            )
            st.markdown(
                f"**Leg 2 —** {_bet2}  \n"
                f"*{_r2.get('pocket_type')} · historical ROI {_r2.get('roi')}*"
            )
            st.caption(
                f"**Summary:** top two distinct-game spread opportunities by **global** ranked ROI "
                f"(ROIs {_r1.get('roi')} / {_r2.get('roi')} — not parlay EV math)."
            )
    st.warning(
        "**For entertainment / small-stake use only** — not a guaranteed edge, not sizing advice, "
        "not a substitute for authority logic. No bets placed or automated."
    )

    _adm_rows, _adm_cap = _resolve_ncaam_pocket_slate_rows(
        _ncaam_current_pockets_doc,
        _ncaam_live_pockets_doc,
        games,
        selected_date,
    )
    _adm_bt = str((_ncaam_pockets_doc or {}).get("source_backtest_dir") or "")
    if _lb_sf:
        _adm_bt = str(_lb_sf.get("source_backtest_dir") or _adm_bt)
    _spread_h = _spread_w = _spread_c = _spread_i = 0
    if _lb_sf:
        for _sr in _lb_sf.get("strongest_spread_cluster") or []:
            if not isinstance(_sr, dict):
                continue
            _spa = _sr.get("spread_pocket_alignment") or {}
            if isinstance(_spa, dict):
                _spread_h += int(_spa.get("hot") or 0)
                _spread_w += int(_spa.get("warm") or 0)
                _spread_c += int(_spa.get("cold") or 0)
                _spread_i += int(_spa.get("insufficient") or 0)
    _lb_mismatch = False
    if _lb_sf:
        _gct = int(_lb_sf.get("game_count") or 0)
        _lb_mismatch = _gct > 0 and _gct != len(_adm_rows)
    with st.expander("NCAAM pocket admin / debug (read-only)", expanded=False):
        st.code(
            "source_backtest_dir: "
            + str(_adm_bt or "—")
            + "\nsource_daily_view_path (leaderboard): "
            + str(((_lb_sf or {}).get("source_daily_view_path")) or "—")
            + "\nselected_date: "
            + str(selected_date)
            + "\nleaderboard slate_date: "
            + str(((_lb_sf or {}).get("slate_date")) or "—")
            + "\nleaderboard game_count: "
            + str(((_lb_sf or {}).get("game_count")) if _lb_sf else "—")
            + "\nslate_table_rows: "
            + str(len(_adm_rows))
            + "\nspread_align_sums_H_W_C_I: "
            + f"{_spread_h},{_spread_w},{_spread_c},{_spread_i}"
            + "\neligible_parlay_pool_count (positive ROI + pick, ranked opportunities): "
            + str(_parlay_eligible_n)
            + "\nranked_opportunity_rows: "
            + str(len(_opp_rows))
            + "\nncaam_ranked_pocket_opportunities.json: "
            + (
                "loaded"
                if _ncaam_ranked_pocket_doc
                else "missing (rebuilt in-session if leaderboard + pockets present)"
            )
            + "\nncaam_best_pocket_per_game.json: "
            + ("loaded" if _ncaam_best_pocket_doc else "missing (rebuilt in-session if leaderboard present)")
            + "\ngame_count_vs_slate_mismatch: "
            + ("yes" if _lb_mismatch else "no"),
            language=None,
        )
        st.markdown("**Slate resolution (live artifact vs fallback)**")
        st.markdown(_adm_cap)
        if _lb_sf and str(_lb_sf.get("slate_date") or "").strip() != str(selected_date).strip():
            st.warning("Leaderboard `slate_date` ≠ selected date — treat live tables as cross-dated.")

    with st.expander("Detailed diagnostic pocket tables (secondary)", expanded=False):
        if formulas:
            with st.expander("Formulas & thresholds", expanded=False):
                st.json(formulas)
        st.subheader("Live slate — spread-first diagnostic (secondary)")
        st.caption(
            "`ncaam_pocket_leaderboard_validation.json` motivated spread cluster / triple spread / pass / cold — "
            "see **Historical leaderboard validation** at the bottom of this expander."
        )
        st.caption(
            "Tables sort by **ROI → graded games → leaderboard score** (display only)."
        )
        if not _lb_sf:
            st.caption(
                "Load `ncaam_live_pocket_leaderboard.json` (run `build_ncaam_model_pockets.py`) to populate these tables."
            )
        else:
            _sf_slate = str(_lb_sf.get("slate_date") or "").strip()
            if _sf_slate and _sf_slate != str(selected_date).strip():
                st.warning(
                    f"Leaderboard slate **`{_sf_slate}`** ≠ selected **`{selected_date}`** — rows may not match today’s table."
                )

            _bts_raw = [r for r in (_lb_sf.get("best_triple_spread") or []) if isinstance(r, dict)]
            _bps_raw = [r for r in (_lb_sf.get("best_pair_spread") or []) if isinstance(r, dict)]
            _triple_by_gid = {
                str(r.get("game_id") or "").strip(): r for r in _bts_raw if str(r.get("game_id") or "").strip()
            }
            _pair_by_gid = {
                str(r.get("game_id") or "").strip(): r for r in _bps_raw if str(r.get("game_id") or "").strip()
            }

            st.markdown("##### 1 · Strongest spread cluster (ROI-informed sort via matched combo pockets)")
            _ssc_sf = [r for r in (_lb_sf.get("strongest_spread_cluster") or []) if isinstance(r, dict)]
            _ssc_rows_out = []
            for r in _ssc_sf:
                gid = str(r.get("game_id") or "").strip()
                tr = _triple_by_gid.get(gid)
                pr = _pair_by_gid.get(gid)
                tr_roi = _pocket_float(tr.get("roi")) if tr else None
                pr_roi = _pocket_float(pr.get("roi")) if pr else None
                tr_g = int(tr.get("graded_games") or 0) if tr else 0
                pr_g = int(pr.get("graded_games") or 0) if pr else 0
                proxy_roi = tr_roi if tr_roi is not None else pr_roi
                max_graded = max(tr_g, pr_g) if (tr or pr) else 0
                _ssc_rows_out.append(
                    {
                        "_sort": (
                            proxy_roi if proxy_roi is not None else -1e18,
                            max_graded,
                            _pocket_float(r.get("cluster_score")) or 0.0,
                        ),
                        "ui rank": 0,
                        "game_id": r.get("game_id"),
                        "matchup": r.get("matchup"),
                        "spread pick": r.get("spread_pick"),
                        "spread align H/W/C/I": _lb_hci(r.get("spread_pocket_alignment")),
                        "cluster score": r.get("cluster_score"),
                        "hist triple ROI": tr_roi,
                        "hist triple graded": tr_g if tr else None,
                        "hist pair ROI": pr_roi,
                        "hist pair graded": pr_g if pr else None,
                        "leaderboard score": r.get("leaderboard_score"),
                        "summary": (r.get("reason") or "")[:100],
                    }
                )
            _ssc_rows_out.sort(key=lambda x: x["_sort"], reverse=True)
            for i, row in enumerate(_ssc_rows_out, start=1):
                row["ui rank"] = i
                del row["_sort"]
            if _ssc_rows_out:
                _st_pocket_roi_table(_ssc_rows_out, ["hist triple ROI", "hist pair ROI"])
            else:
                st.caption("No rows.")

            st.markdown("##### 2 · Best triple spread combo (historical pocket stats, ROI-first)")
            _bts_sf = sorted(_bts_raw, key=_combo_roi_sort_key, reverse=True)
            if _bts_sf:
                _st_pocket_roi_table(
                    [
                        {
                            "ui rank": i,
                            "game_id": r.get("game_id"),
                            "matchup": r.get("matchup"),
                            "spread pick": r.get("spread_pick"),
                            "triple combo (models)": r.get("models_key"),
                            "pocket ROI": r.get("roi"),
                            "pocket Win%": r.get("win_rate"),
                            "pocket graded": r.get("graded_games"),
                            "combo pocket state": r.get("combo_state"),
                            "spread align": _lb_hci(r.get("spread_pocket_alignment")),
                            "leaderboard score": r.get("leaderboard_score"),
                            "summary": (r.get("reason") or "")[:100],
                        }
                        for i, r in enumerate(_bts_sf, start=1)
                    ],
                    ["pocket ROI"],
                )
            else:
                st.caption("No triple spread matches on this slate.")

            st.markdown("##### 3 · Best pair spread combo (historical pocket stats, ROI-first)")
            _bps_sf = sorted(_bps_raw, key=_combo_roi_sort_key, reverse=True)
            if _bps_sf:
                _st_pocket_roi_table(
                    [
                        {
                            "ui rank": i,
                            "game_id": r.get("game_id"),
                            "matchup": r.get("matchup"),
                            "spread pick": r.get("spread_pick"),
                            "pair combo (models)": r.get("models_key"),
                            "pocket ROI": r.get("roi"),
                            "pocket Win%": r.get("win_rate"),
                            "pocket graded": r.get("graded_games"),
                            "combo pocket state": r.get("combo_state"),
                            "spread align": _lb_hci(r.get("spread_pocket_alignment")),
                            "leaderboard score": r.get("leaderboard_score"),
                            "summary": (r.get("reason") or "")[:100],
                        }
                        for i, r in enumerate(_bps_sf, start=1)
                    ],
                    ["pocket ROI"],
                )
            else:
                st.caption("No pair spread matches on this slate.")

            st.markdown("##### 4 · Pass candidates (hist. pair ROI → cluster score)")
            _pc_sf = sorted(
                [r for r in (_lb_sf.get("pass_candidates") or []) if isinstance(r, dict)],
                key=_pass_roi_sort_key,
                reverse=True,
            )
            if _pc_sf:
                _st_pocket_roi_table(
                    [
                        {
                            "ui rank": i,
                            "game_id": r.get("game_id"),
                            "matchup": r.get("matchup"),
                            "spread pick": r.get("spread_pick"),
                            "spread cluster score": r.get("spread_cluster_score"),
                            "hist. best-pair spread ROI": r.get("best_pair_spread_roi"),
                            "leaderboard score": r.get("leaderboard_score"),
                            "spread align": _lb_hci(r.get("spread_pocket_alignment")),
                            "summary": (r.get("reason") or "")[:120],
                        }
                        for i, r in enumerate(_pc_sf, start=1)
                    ],
                    ["hist. best-pair spread ROI"],
                )
            else:
                st.caption("No pass-flagged games on this slate.")

            st.markdown("##### 5 · Cold cluster warnings (warning score; no per-game ROI)")
            _ccw_sf = sorted(
                [r for r in (_lb_sf.get("cold_cluster_warnings") or []) if isinstance(r, dict)],
                key=_cold_sort_key,
                reverse=True,
            )
            if _ccw_sf:
                st.dataframe(
                    [
                        {
                            "ui rank": i,
                            "game_id": r.get("game_id"),
                            "matchup": r.get("matchup"),
                            "warning score": r.get("warning_score"),
                            "spread align": _lb_hci(r.get("spread_pocket_alignment")),
                            "leaderboard score": r.get("leaderboard_score"),
                            "summary": (r.get("reason") or "")[:100],
                        }
                        for i, r in enumerate(_ccw_sf, start=1)
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("No rows.")

        st.markdown("---")
        st.subheader("Historical leaderboard validation (read-only)")
        _val = _ncaam_pocket_validation_doc
        if not _val:
            st.caption(
                "No `ncaam_pocket_leaderboard_validation.json` in latest backtest — run `build_ncaam_model_pockets.py`."
            )
        else:
            st.caption(
                f"Backtest **`{_val.get('source_backtest_dir', '')}`** · "
                f"{_val.get('n_games_with_models_blob', 0)} games with `models` (of {_val.get('n_backtest_rows', 0)} rows). "
                "Tercile splits vs full sample; -110 ROI on graded legs."
            )

            def _vrow(label: str, d: dict | None) -> dict:
                if not isinstance(d, dict):
                    return {"metric": label, "graded": None, "Win%": None, "ROI": None, "notes": "—"}
                return {
                    "metric": label,
                    "graded": d.get("graded_games"),
                    "Win%": d.get("win_rate"),
                    "ROI": d.get("roi"),
                    "notes": (d.get("sample_notes") or "")[:48],
                }

            _ps = _val.get("pair_spread_top_vs_all") or {}
            _cl = _val.get("spread_cluster_strong_vs_weak") or {}
            _pv = _val.get("pass_vs_non_pass") or {}
            _sum_spread = [
                _vrow("Pair spread combo — top tercile (score)", _ps.get("top_tercile_pair_spread_combo")),
                _vrow("Pair spread combo — all w/ pocket", _ps.get("all_with_pair_spread_combo")),
                _vrow("Authority spread — top pair tercile games", _ps.get("authority_spread_top_pair_tercile")),
                _vrow("Triple spread combo — top tercile", (_val.get("triple_spread_top_vs_all") or {}).get("top_tercile_triple_spread_combo")),
                _vrow("Triple spread combo — all w/ pocket", (_val.get("triple_spread_top_vs_all") or {}).get("all_with_triple_spread_combo")),
                _vrow("Cluster — strong (auth spread)", _cl.get("strong_spread_cluster_authority_spread")),
                _vrow("Cluster — weak (auth spread)", _cl.get("weak_spread_cluster_authority_spread")),
                _vrow("Pass candidates (auth spread)", _pv.get("pass_candidates_authority_spread")),
                _vrow("Non-pass (auth spread)", _pv.get("non_pass_authority_spread")),
            ]
            st.markdown("##### Spread / cluster / pass (historical)")
            _st_pocket_roi_table(_sum_spread, ["ROI"])

            _tot = _val.get("totals_if_sufficient") or {}
            _trows = []
            if isinstance(_tot.get("pair_total_top_tercile_combo"), dict):
                _trows.append(_vrow("Pair total combo — top tercile", _tot.get("pair_total_top_tercile_combo")))
                _trows.append(_vrow("Pair total combo — all", _tot.get("pair_total_all_with_pocket_combo")))
            if isinstance(_tot.get("triple_total_top_tercile_combo"), dict):
                _trows.append(_vrow("Triple total combo — top tercile", _tot.get("triple_total_top_tercile_combo")))
                _trows.append(_vrow("Triple total combo — all", _tot.get("triple_total_all_with_pocket_combo")))
            if _trows:
                st.markdown("##### Totals (historical, n≥30 gate)")
                _st_pocket_roi_table(_trows, ["ROI"])
            elif _tot.get("pair_total", {}).get("skipped") or _tot.get("triple_total", {}).get("skipped"):
                st.caption("Totals validation skipped (insufficient sample per artifact rules).")

            _cw = _val.get("cold_warning_high_vs_low") or {}
            _wrows = [
                _vrow("Cold warning HIGH tercile (auth spread)", _cw.get("high_warning_authority_spread")),
                _vrow("Cold warning LOW tercile (auth spread)", _cw.get("low_warning_authority_spread")),
            ]
            st.markdown("##### Cold-warning terciles (historical)")
            _st_pocket_roi_table(_wrows, ["ROI"])


# --------------------------------------------------
# AGENT OVERLAY (read-only): load by league, join by game_id
# --------------------------------------------------
_overlay_path = PROJECT_ROOT / "data" / ("ncaam" if league == "NCAAM" else "nba") / "view" / (
    "ncaam_agent_overlay.json" if league == "NCAAM" else "nba_agent_overlay.json"
)
_overlay_by_game_id = {}
_overlay_data = None
if _overlay_path.exists():
    try:
        with open(_overlay_path, "r", encoding="utf-8") as f:
            _overlay_data = json.load(f)
        _overlay_games = _overlay_data.get("games") or []
        for _og in _overlay_games:
            _gid = _og.get("game_id")
            if _gid is not None and str(_gid).strip():
                _overlay_by_game_id[str(_gid).strip()] = _og
    except Exception:
        pass


def _overlay_slate_date_from_source_artifact(overlay_root: dict) -> str | None:
    """Extract slate date (YYYY-MM-DD) from overlay source_artifact path. Returns None if missing or unparseable."""
    if not overlay_root or not isinstance(overlay_root, dict):
        return None
    path_str = overlay_root.get("source_artifact") or ""
    if not path_str or not isinstance(path_str, str):
        return None
    # Basename: daily_view_2026-03-12_v1.json or daily_view_ncaam_2026-03-12_v1.json
    name = Path(path_str).name
    match = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    return match.group(1) if match else None


_overlay_status = "missing"  # missing | match | mismatch | unknown
_overlay_slate_date = None
if not _overlay_path.exists():
    _overlay_status = "missing"
elif _overlay_data is None:
    _overlay_status = "unknown"
else:
    _overlay_slate_date = _overlay_slate_date_from_source_artifact(_overlay_data)
    if _overlay_slate_date is None:
        _overlay_status = "unknown"
    elif _overlay_slate_date == selected_date:
        _overlay_status = "match"
    else:
        _overlay_status = "mismatch"

if not games:
    st.warning("No games available.")
    st.stop()

odds_snapshot_last_utc = None
for g in games:
    market_state = g.get("market_state", {})
    odds_snapshot_last_utc = market_state.get("odds_snapshot_last_utc")
    if odds_snapshot_last_utc:
        break

last_odds_update_cst = format_odds_snapshot_cst(odds_snapshot_last_utc)

st.markdown(f"**Last Odds Update:** {last_odds_update_cst}")

# Agent overlay vs selected slate: match / missing / stale (read-only status)
if _overlay_status == "match":
    st.caption(f"Agent overlay: matches selected slate ({selected_date})")
elif _overlay_status == "missing":
    st.caption("Agent overlay: not loaded")
elif _overlay_status == "mismatch":
    st.caption(f"Agent overlay: built for **{_overlay_slate_date}**; selected slate is **{selected_date}** — may be stale")
else:
    st.caption("Agent overlay: loaded; slate date unknown — may not match selected slate")

if league in ("NBA", "NCAAM"):
    slate_dashboard_view = st.radio(
        "Dashboard view",
        ("Standard Slate View", "Pocket ROI View"),
        index=0,
        horizontal=True,
        help="Pocket ROI View shows the pocket leaderboard lens only (read-only).",
    )
else:
    slate_dashboard_view = "Standard Slate View"

if league == "NBA" and slate_dashboard_view == "Pocket ROI View":
    st.caption(
        "**Pocket ROI lens** — backtest-derived pocket board for the selected slate; read-only; does not change authority. "
        "**MonkeyDarts_v2** excluded upstream."
    )
    _render_nba_pocket_roi_view(games, selected_date)
    st.stop()

if league == "NCAAM" and slate_dashboard_view == "Pocket ROI View":
    st.caption(
        "**Pocket ROI lens** — NCAAM backtest-derived pocket board for the selected slate; read-only; does not change authority. "
        "Models: avg score, momentum, market pressure (no injury layer)."
    )
    _render_ncaam_pocket_roi_view(games, selected_date)
    st.stop()

if league == "NBA" and slate_dashboard_view == "Standard Slate View":
    st.caption(
        "**NBA pockets:** use **Pocket ROI View** for ranked best-pocket per game and positive-ROI parlay diagnostics."
    )

if league == "NCAAM" and slate_dashboard_view == "Standard Slate View":
    st.caption(
        "**NCAAM pockets:** use **Pocket ROI View** for ranked best-pocket per game and positive-ROI parlay diagnostics."
    )

# --------------------------------------------------
# KELLY BET SIZING MODEL
# --------------------------------------------------

with st.expander("🍀 KBX Bet Sizing System 🌵", expanded=False):
    if _overlay_buckets is None:
        st.warning(
            "Dynamic overlay data is unavailable for the latest backtest. "
            "Suggested Bet Sizing is not available — sweet-spot-based Kelly assumptions are not shown as authoritative."
        )
        st.markdown(
            "Run backtest and analysis_039b with `--use-dynamic-sweetspots` for this league to enable Execution Overlay and Kelly sizing from current backtest data."
        )
        kelly_rows = []
    else:
        kelly_rows = []
        for g in games:
            identity = g.get("identity", {})
            market = g.get("market_state", {})
            model = g.get("model_output", {})
            regime_name, regime_win_pct = get_kelly_regime(g, _overlay_win_rate_by_bucket)

            if regime_name is None:
                continue
            # Kelly eligibility gate:
            # - NBA: require bucket status == "active" (existing behavior).
            # - NCAAM: allow sizing for per-game sweet-spot regimes even if the latest
            #   bucket classification is "near_miss" (per-game badge qual != bucket status).
            if league == "NBA" and _overlay_status_by_bucket.get(regime_name) != "active":
                continue

            away = identity.get("away_team", "Away")
            home = identity.get("home_team", "Home")

            spread_line = market.get("spread_home_last")
            total_line = market.get("total_last")

            spread_pick = model.get("spread_pick")
            total_pick = model.get("total_pick")
            models_allingment = model.get("confidence_tier")

            full_kelly = calculate_full_kelly(regime_win_pct, KELLY_PAYOUT_RATIO)
            bet_amount = round(current_bankroll * full_kelly)

            if regime_name == "Total Sweet Spot":
                if total_pick and total_line is not None:
                    pick_text = f"{total_pick} ({total_line})"
                elif total_pick:
                    pick_text = f"{total_pick} (—)"
                else:
                    pick_text = "No Total Pick"
            else:
                pick_text = format_spread_text(home, away, spread_line, spread_pick)

            kelly_rows.append({
                "Game": format_matchup_short(away, home),
                "Pick": pick_text,
                "Regime": regime_name,
                "Bet $": f"${bet_amount}",
                "Models Align": models_allingment,
            })

    st.markdown("### Suggested Bet Sizing")

    if kelly_rows:
        st.table(kelly_rows)

        total_plays = len(kelly_rows)
        total_exposure = sum(int(row["Bet $"].replace("$", "")) for row in kelly_rows)

        st.markdown(
            f"**Portfolio:** {total_plays} plays | **Exposure:** ${total_exposure}"
        )
    elif _overlay_buckets is not None:
        st.write("No qualifying Sweet Spot bets to size.")

    st.markdown(
        "<sub>"
        f"1. Uses current bankroll (sidebar) = ${current_bankroll:,}. "
        "2. Full Kelly shown using the historical win rate of the qualifying regime. "
        "3. Historical win rate is context, not guarantee. "
        "4. Conservative mode should scale all bets evenly, such as 50% Kelly or 25% Kelly."
        "</sub>",
        unsafe_allow_html=True
    )

    st.markdown("---")
    _overlay_updated = (_overlay_date if _overlay_date else None) or _execution_overlay_backtest_date(league)
    st.markdown(
        f"**Execution Overlay Backtest Reference — Last Updated:** "
        f"{_overlay_updated}"
    )
    if _overlay_buckets is None:
        st.info(
            "Dynamic sweet-spot data is unavailable for the latest backtest. "
            "Run backtest and analysis_039b with `--use-dynamic-sweetspots` to populate this section."
        )
    else:
        st.table(_overlay_table_display)


# --------------------------------------------------
# SORT
# --------------------------------------------------

sort_option = st.selectbox(
    "Sort Games By",
    [
        "Schedule Order",
        "Execution Quality",
        "Parlay Edge",
        "Spread Edge",
        "Total Edge",
        "Confidence Tier",
        "Calibration Win Rate"
    ]
)

if sort_option == "Schedule Order":
    games = sorted(games, key=_game_commence_sort_key)

elif sort_option == "Execution Quality":

    def execution_rank(g):
        overlay = g.get("execution_overlay", {})

        dual = overlay.get("dual_sweet_spot")
        spread = overlay.get("spread_sweet_spot")
        total = overlay.get("total_sweet_spot")

        if dual:
            return 3
        if spread or total:
            return 2
        return 1

    games = sorted(games, key=execution_rank, reverse=True)

elif sort_option == "Parlay Edge":
    games = sorted(
        games,
        key=lambda g: safe_num((g.get("edge_metrics") or {}).get("parlay_edge_score"), 0.0),
        reverse=True
    )

elif sort_option == "Spread Edge":
    games = sorted(
        games,
        key=lambda g: abs(safe_num((g.get("edge_metrics") or {}).get("spread_edge"), 0.0)),
        reverse=True
    )

elif sort_option == "Total Edge":
    games = sorted(
        games,
        key=lambda g: abs(safe_num((g.get("edge_metrics") or {}).get("total_edge"), 0.0)),
        reverse=True
    )

elif sort_option == "Calibration Win Rate":
    games = sorted(
        games,
        key=lambda g: safe_num(
            (g.get("calibration_tags") or {}).get("historical_bucket_win_rate"),
            0.0,
        ),
        reverse=True,
    )


# --------------------------------------------------
# GAMES LOOP START
# --------------------------------------------------


def _ncaam_result_with_margin(result_txt: str, margin_raw):
    r = (result_txt or "").strip()
    if not r:
        return "—"
    ru = r.upper()
    if ru == "WIN":
        prefix = "✅ "
    elif ru == "LOSS":
        prefix = "❌ "
    elif ru == "PUSH":
        prefix = "➖ "
    else:
        prefix = ""
    if margin_raw is None:
        return f"{prefix}{r}" if prefix else r
    try:
        mv = float(margin_raw)
    except (TypeError, ValueError):
        return f"{prefix}{r}" if prefix else r
    body = f"{r}x{mv:g}"
    return f"{prefix}{body}" if prefix else body


for g in games:
    identity = g.get("identity") or {}
    market = g.get("market_state") or {}
    model = g.get("model_output") or {}
    edge = g.get("edge_metrics") or {}
    calibration = g.get("calibration_tags") or {}
    _arb_raw = g.get("arbitration")
    arb = _arb_raw if isinstance(_arb_raw, dict) else {}
    overlay = g.get("execution_overlay") or {}

    away = identity.get("away_team", "Away")
    home = identity.get("home_team", "Home")

    spread_line = market.get("spread_home_last")
    total_line = market.get("total_last")

    spread_pick = model.get("spread_pick")
    total_pick = model.get("total_pick")

    spread_text = format_spread_text(home, away, spread_line, spread_pick)

    if total_pick:
        total_text = (
            f"{total_pick} ({total_line})" if total_line is not None else f"{total_pick} (—)"
        )
    else:
        total_text = "No Total Pick"

    parlay_score = safe_num(edge.get("parlay_edge_score", 0), 0.0)
    spread_edge = safe_num(edge.get("spread_edge", 0), 0.0)
    total_edge = safe_num(edge.get("total_edge", 0), 0.0)

    MAX_PARLAY = 20
    MAX_COMPONENT = 12

    parlay_pct = int(min(abs(parlay_score) / MAX_PARLAY, 1.0) * 100)
    spread_pct = int(min(abs(spread_edge) / MAX_COMPONENT, 1.0) * 100)
    total_pct = int(min(abs(total_edge) / MAX_COMPONENT, 1.0) * 100)

    tier = model.get("confidence_tier", "LOW")

    if tier == "HIGH":
        main_color = "#2ecc71"
    elif tier in ("MODERATE", "MEDIUM"):
        main_color = "#f39c12"
    else:
        main_color = "#e74c3c"

    component_color = "#3498db"

    badge = ""

    if overlay.get("dual_sweet_spot"):
        badge = " 🟢 EXECUTION+"
    elif overlay.get("spread_sweet_spot"):
        badge = " 🟢 SPREAD+"
    elif overlay.get("total_sweet_spot"):
        badge = " 🟢 TOTAL+"
    elif overlay.get("spread_avoid") or overlay.get("total_avoid"):
        badge = " 🔴 AVOID"

    # Agentic: VALUE PEAK REACHED in agent_reasoning or confidence_reason -> TOP AGENT PICK + highlight
    agent_reasoning = str(model.get("agent_reasoning") or g.get("agent_reasoning") or "")
    confidence_reason = str(model.get("confidence_reason") or "")
    explanation = str(
        model.get("Explanation")
        or model.get("explanation")
        or g.get("Explanation")
        or ""
    )
    is_value_peak = (
        "VALUE PEAK REACHED" in agent_reasoning
        or "VALUE PEAK REACHED" in confidence_reason
        or "VALUE PEAK REACHED" in explanation
    )
    if is_value_peak:
        badge += " 🔥 TOP AGENT PICK"

    # Matchup key: normalized to match attribution report for 1:1 tracking (full "Away @ Home")
    matchup_label = format_matchup_attribution(away, home)

    # Agent overlay lookup (used for compact summary at top and detail section at bottom)
    # _game_id = (identity.get("game_id") if isinstance(identity, dict) else None) or g.get("game_id")

    # NCAAM often leaves identity.game_id empty; row-level espn_game_id / game_source_id are populated instead.
    _game_id = (
            (identity.get("game_id") if isinstance(identity, dict) else None)
            or g.get("game_id")
            or g.get("espn_game_id")
            or g.get("game_source_id")
    )
    _agent_row = _overlay_by_game_id.get(str(_game_id).strip(), None) if _game_id else None

    # NCAAM: spread/total grading vs line (full detail in expander).
    sr_ncaam = str(g.get("selected_spread_result") or "").strip() if league == "NCAAM" else ""
    tr_ncaam = str(g.get("selected_total_result") or "").strip() if league == "NCAAM" else ""
    # NCAAM: S/T vs line on roll-up when grading exists (matches zzz_0322-01-bookiex_dashboard.py).
    result_suffix = ""
    if league == "NCAAM" and (sr_ncaam or tr_ncaam):
        _sr_disp = (
            _ncaam_result_with_margin(sr_ncaam, g.get("selected_spread_margin_abs"))
            if sr_ncaam
            else "—"
        )
        _tr_disp = (
            _ncaam_result_with_margin(tr_ncaam, g.get("selected_total_margin_abs"))
            if tr_ncaam
            else "—"
        )
        result_suffix = f" || S = {_sr_disp} / T = {_tr_disp}"

    expander_label = (
        f"{matchup_label}: Take {spread_text} / {total_text}"
        f"{badge} — {tier} | {parlay_pct}%{result_suffix}"
    )
    if is_value_peak:
        st.markdown(
            "<div style='background: linear-gradient(90deg, rgba(46, 204, 113, 0.35) 0%, rgba(46, 204, 113, 0.15) 100%); "
            "border-left: 5px solid #2ecc71; border-radius: 6px; padding: 6px 12px; margin-bottom: 6px; "
            "font-weight: 600; color: #1a5f2a;'>🔥 TOP AGENT PICK — VALUE PEAK REACHED</div>",
            unsafe_allow_html=True,
        )
    with st.expander(expander_label, expanded=False):
        st.write(f"Tipoff: {identity.get('tip_time_cst', 'N/A')}")
        _sl_disp = spread_line if spread_line is not None else "—"
        _tl_disp = total_line if total_line is not None else "—"
        st.write(f"Market: {_sl_disp} | Total {_tl_disp}")
        # Final box score: NCAAM post games only (same as zzz_0322-01-bookiex_dashboard.py).
        if league == "NCAAM" and str(g.get("status_state") or "").strip().lower() == "post":
            away_points = g.get("away_points")
            home_points = g.get("home_points")
            actual_total = g.get("actual_total")
            if away_points is not None and home_points is not None and actual_total is not None:
                st.write(f"Final: Score {away_points:g} @ {home_points:g} | Total {actual_total:g}")
        st.markdown(f"**Game ID:** `{_game_id}`")
        if league == "NCAAM" and (sr_ncaam or tr_ncaam):
            st.markdown("### Grading vs line (authority)")
            _sr_d = (
                _ncaam_result_with_margin(sr_ncaam, g.get("selected_spread_margin_abs"))
                if sr_ncaam
                else "—"
            )
            _tr_d = (
                _ncaam_result_with_margin(tr_ncaam, g.get("selected_total_margin_abs"))
                if tr_ncaam
                else "—"
            )
            st.write(f"Spread (selected pick): {_sr_d}")
            st.write(f"Total (selected pick): {_tr_d}")

        # Compact agent summary (read-only); visible at top of expander for quick scan
        if _agent_row:
            _pick = _agent_row.get("agent_pick") or "—"
            _agrees = _agent_row.get("agent_agrees_with_baseline")
            _agrees_txt = "Yes" if _agrees is True else ("No" if _agrees is False else "—")
            _action = _agent_row.get("agent_recommended_action") or "—"
            _override = "Yes" if _agent_row.get("agent_override_applied") else "No"
            st.caption(
                f"**Agent (read-only):** Pick: {_pick} | Agrees: {_agrees_txt} | Action: {_action} | Override: {_override}"
            )
        else:
            st.caption("**Agent (read-only):** — (no overlay for this game)")
        st.markdown(f"### 🔥 Signal Strength — {tier}")

        st.markdown(
            f"""
            <div style="background-color:#eee; border-radius:8px; padding:3px; margin-bottom:6px;">
                <div style="
                    width:{parlay_pct}%;
                    background-color:{main_color};
                    height:22px;
                    border-radius:6px;
                    text-align:center;
                    color:white;
                    font-size:12px;
                    font-weight:bold;">
                    Overall {parlay_pct}%
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

        st.markdown(
            f"""
            <div style="background-color:#f4f4f4; border-radius:6px; padding:2px; margin-bottom:4px;">
                <div style="
                    width:{spread_pct}%;
                    background-color:{component_color};
                    height:12px;
                    border-radius:4px;">
                </div>
            </div>
            <small>Spread Strength ({round(spread_edge, 2)})</small>
            """,
            unsafe_allow_html=True
        )

        st.markdown(
            f"""
            <div style="background-color:#f4f4f4; border-radius:6px; padding:2px; margin-bottom:4px;">
                <div style="
                    width:{total_pct}%;
                    background-color:{component_color};
                    height:12px;
                    border-radius:4px;">
                </div>
            </div>
            <small>Total Strength ({round(total_edge, 2)})</small>
            """,
            unsafe_allow_html=True
        )

        st.subheader("Model vs Market")

        st.write("Spread Pick:", model.get("spread_pick"))
        st.write("Projected Margin (Home):", safe_round(model.get("projected_margin_home", 0), 2))
        st.write("Spread Edge:", safe_round(spread_edge, 2))

        st.write("Total Pick:", model.get("total_pick"))
        st.write("Projected Total:", safe_round(model.get("projected_total", 0), 2))
        st.write("Total Edge:", safe_round(total_edge, 2))
        _ph = model.get("projected_home_score")
        _pa = model.get("projected_away_score")
        if _ph is not None or _pa is not None:
            st.write(
                "Projected score (away @ home):",
                f"{_pa if _pa is not None else '—'} @ {_ph if _ph is not None else '—'}",
            )

        st.write("Parlay Edge Score:", safe_round(parlay_score, 2))

        st.subheader("Structure")

        st.write("Confidence Tier:", tier)
        st.write("Cluster Alignment:", model.get("cluster_alignment"))
        st.write("Arbitration Cluster:", model.get("arbitration_cluster"))

        st.write("Consensus Books:", market.get("consensus_book_count"))
        st.write("All-Time Snapshots:", market.get("all_time_snapshot_count"))

        st.write(
            "Spread Disagreement:",
            _arb_branch(arb, "spread").get("disagreement_flag"),
        )
        st.write(
            "Total Disagreement:",
            _arb_branch(arb, "total").get("disagreement_flag"),
        )

        st.subheader("History")

        st.write("Edge Bucket:", calibration.get("edge_bucket"))
        st.write(
            "Historical Win Rate:",
            safe_round(calibration.get("historical_bucket_win_rate", 0), 3)
        )

        st.write("Spread Percentile:", edge.get("spread_edge_percentile"))
        st.write("Total Percentile:", edge.get("total_edge_percentile"))

        st.subheader("Decision")
        st.subheader("Execution Overlay")

        st.write("Spread Sweet Spot:", overlay.get("spread_sweet_spot"))
        st.write("Total Sweet Spot:", overlay.get("total_sweet_spot"))
        st.write("Dual Sweet Spot:", overlay.get("dual_sweet_spot"))
        st.write("Spread Avoid:", overlay.get("spread_avoid"))
        st.write("Total Avoid:", overlay.get("total_avoid"))

        regime_name, regime_win_pct = get_kelly_regime(g, _overlay_win_rate_by_bucket)
        if regime_name is not None:
            full_kelly = calculate_full_kelly(regime_win_pct, KELLY_PAYOUT_RATIO)

            st.subheader("📈 Expected Value Guidance")
            st.write(f"Kelly Regime: {regime_name}")
            st.write(f"Historical Win Rate: {regime_win_pct:.3f}")
            st.write(f"Full Kelly: {full_kelly:.3f} (Fraction of bankroll)")
            st.write(
                f"Example Bet on ${current_bankroll:,}: "
                f"${round(current_bankroll * full_kelly)}"
            )

        st.write("Actionability:", model.get("actionability"))
        st.write("Reason:", model.get("confidence_reason"))

        st.subheader("Why")

        st.write(
            f"Spread edge = {safe_round(spread_edge, 2)} "
            f"(Bucket {calibration.get('edge_bucket', 'N/A')} | "
            f"Historical Win Rate {safe_round(calibration.get('historical_bucket_win_rate', 0), 3)})"
        )

        st.write(
            f"Confidence Tier = {tier} "
            f"(Cluster: {model.get('cluster_alignment')})"
        )

        if model.get("actionability") == "ACTION":
            st.write("Execution threshold met.")
        else:
            st.write("Below execution threshold.")

        st.subheader("Model Details")

        models = g.get("models") or {}

        if not models:
            st.write("No model details available.")
        else:
            final_spread = model.get("spread_pick")
            final_total = model.get("total_pick")

            for model_name, model_data in models.items():
                model_spread = model_data.get("spread_pick")
                model_total = model_data.get("total_pick")

                spread_align = model_spread == final_spread
                total_align = model_total == final_total

                if spread_align and total_align:
                    icon = "🟢"
                elif spread_align and not total_align:
                    icon = "🟡 T"
                elif not spread_align and total_align:
                    icon = "🟡 S"
                else:
                    icon = "🔴"

                if model_name == "MonkeyDarts_v2" and league == "NBA":
                    expander_label = f"{icon} {model_name} 🚫 (Excluded from Arbitration)"
                else:
                    expander_label = f"{icon} {model_name}"

                with st.expander(expander_label):
                    st.write("Spread Pick:", model_spread)
                    st.write("Spread Edge:", safe_round(model_data.get("spread_edge", 0), 2))

                    st.write("Total Pick:", model_total)
                    st.write("Total Edge:", safe_round(model_data.get("total_edge", 0), 2))

                    if model_data.get("parlay_edge_score") not in (None, ""):
                        st.write(
                            "Parlay Edge Score:",
                            safe_round(model_data.get("parlay_edge_score", 0), 2)
                        )

                    context_flags = model_data.get("context_flags")
                    if context_flags:
                        st.write("Context Flags:", context_flags)

        # Agent overlay (read-only): detail section (compact summary is at top of expander)
        st.subheader("Agent (read-only)")
        if _agent_row:
            st.write("Agent Pick:", _agent_row.get("agent_pick"), f"({_agent_row.get('agent_pick_type', '')})")
            st.write("Agrees with baseline:", _agent_row.get("agent_agrees_with_baseline"))
            st.write("Agent reasoning:", _agent_row.get("agent_reasoning") or "—")
            st.write("Recommended action:", _agent_row.get("agent_recommended_action") or "—")
            if _agent_row.get("agent_override_applied"):
                st.write("Override applied: Yes")
                if _agent_row.get("agent_override_reason"):
                    st.write("Override reason:", _agent_row.get("agent_override_reason"))
            else:
                st.write("Override applied: No")
        else:
            st.caption("No overlay data for this game.")

# --------------------------------------------------
# GAMES LOOP END
# --------------------------------------------------
