# bookiex_dashboard.py
# Executive View — Correct Field Mapping

import streamlit as st
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

DAILY_DIR = Path("data/daily")

st.set_page_config(page_title="BookieX", layout="wide")

# --------------------------------------------------
# LOAD FILES
# --------------------------------------------------

files = sorted(DAILY_DIR.glob("daily_view_*_v1.json"))

if not files:
    st.error("No DAILY_VIEW files found.")
    st.stop()

date_map = {f.name.split("_")[2]: f for f in files}
available_dates = sorted(date_map.keys(), reverse=True)

# --------------------------------------------------
# HEADER ROW
# --------------------------------------------------

header_left, header_right = st.columns([6, 2])

with header_left:
    icon_col, title_col = st.columns([1, 8])

    with icon_col:
        st.image("assets/RS_JP_BookieX_v02.png", width=90)

    with title_col:
        st.markdown(
            "<h1 style='margin-bottom:0;'>"
            "BookieX — Today’s Games & Model View"
            "</h1>",
            unsafe_allow_html=True
        )

with header_right:
    selected_date = st.selectbox(
        "Date",
        available_dates,
        index=0
    )

# --------------------------------------------------
# LOAD SELECTED FILE
# --------------------------------------------------

file_path = date_map[selected_date]

last_modified_utc = datetime.fromtimestamp(
    file_path.stat().st_mtime,
    tz=ZoneInfo("UTC")
)

last_modified_cst = last_modified_utc.astimezone(
    ZoneInfo("America/Chicago")
)

last_update_str = last_modified_cst.strftime("%m/%d/%Y %I:%M %p")
st.write("DEBUG FILE:", file_path)
st.markdown(
    f"<div style='color:#8a8a8a; font-size:14px; margin-top:-10px;'>"
    f"Last Update: {last_update_str} CST"
    f"</div>",
    unsafe_allow_html=True
)

with open(file_path, "r", encoding="utf-8") as f:
    data = json.load(f)
games = data.get("games", [])

if not games:
    st.warning("No games available.")
    st.stop()

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

if sort_option == "Execution Quality":

    def execution_rank(g):
        overlay = g.get("execution_overlay", {})
        if overlay.get("dual_sweet_spot"):
            return 3
        if overlay.get("spread_sweet_spot") or overlay.get("total_sweet_spot"):
            return 2
        return 1

    games = sorted(games, key=execution_rank, reverse=True)

elif sort_option == "Parlay Edge":
    games = sorted(games, key=lambda g: g["edge_metrics"]["parlay_edge_score"], reverse=True)

elif sort_option == "Spread Edge":
    games = sorted(games, key=lambda g: abs(g["edge_metrics"]["spread_edge"]), reverse=True)

elif sort_option == "Total Edge":
    games = sorted(games, key=lambda g: abs(g["edge_metrics"]["total_edge"]), reverse=True)

elif sort_option == "Confidence Tier":
    tier_order = {"HIGH": 3, "MODERATE": 2, "LOW": 1, "IGNORE": 0}
    games = sorted(
        games,
        key=lambda g: tier_order.get(g["model_output"].get("confidence_tier"), 0),
        reverse=True
    )

elif sort_option == "Calibration Win Rate":
    games = sorted(
        games,
        key=lambda g: g["calibration_tags"]["historical_bucket_win_rate"],
        reverse=True
    )

# --------------------------------------------------
# TOP SPREAD SWEET SPOTS
# --------------------------------------------------

def spread_rank_score(g):
    overlay = g.get("execution_overlay", {})
    model = g.get("model_output", {})
    edge = g.get("edge_metrics", {})

    if not overlay.get("spread_sweet_spot"):
        return None
    if overlay.get("spread_avoid"):
        return None

    tier_weight = {"HIGH": 3, "MODERATE": 2, "LOW": 1, "IGNORE": 0}
    tier = model.get("confidence_tier", "LOW")
    spread_edge = abs(edge.get("spread_edge", 0))

    return tier_weight.get(tier, 0) * 100 + spread_edge


qualified_spreads = []
for g in games:
    score = spread_rank_score(g)
    if score is not None:
        qualified_spreads.append((score, g))

qualified_spreads = sorted(qualified_spreads, key=lambda x: x[0], reverse=True)

if qualified_spreads:
    st.markdown("## 🔥 Top Spread Sweet Spots")
    for _, g in qualified_spreads[:2]:
        identity = g["identity"]
        market = g["market_state"]
        model = g["model_output"]
        edge = g["edge_metrics"]

        away = identity["away_team"]
        home = identity["home_team"]

        spread_line = market["spread_home_last"]
        spread_pick = model.get("spread_pick")
        tier = model.get("confidence_tier")

        if spread_pick == "HOME":
            spread_text = f"{home} (+{spread_line})"
        elif spread_pick == "AWAY":
            spread_text = f"{away} ({spread_line})"
        else:
            spread_text = "No Spread Pick"

        spread_edge = round(edge.get("spread_edge", 0), 2)

        st.markdown(
            f"🟢 **SPREAD+** — "
            f"**{away} @ {home}** — "
            f"Take {spread_text} | {tier} | Edge: {spread_edge}"
        )

    st.markdown("---")
else:
    st.markdown("## 🔥 Top Spread Sweet Spots")
    st.write("No qualifying Spread Sweet Spots on this slate.")
    st.markdown("---")

# --------------------------------------------------
# GAMES LOOP
# --------------------------------------------------

for g in games:

    identity = g["identity"]
    market = g["market_state"]
    model = g["model_output"]
    edge = g["edge_metrics"]
    calibration = g["calibration_tags"]
    overlay = g.get("execution_overlay") or {}

    away = identity["away_team"]
    home = identity["home_team"]

    spread_line = market["spread_home_last"]
    total_line = market["total_last"]

    spread_pick = model.get("spread_pick")
    total_pick = model.get("total_pick")

    if spread_pick == "HOME":
        spread_text = f"{home} (+{spread_line})"
    elif spread_pick == "AWAY":
        spread_text = f"{away} ({spread_line})"
    else:
        spread_text = "No Spread Pick"

    total_text = f"{total_pick} ({total_line})" if total_pick else "No Total Pick"

    parlay_score = edge.get("parlay_edge_score", 0)
    spread_edge = edge.get("spread_edge", 0)
    total_edge = edge.get("total_edge", 0)

    tier = model.get("confidence_tier", "LOW")

    badge = ""
    if overlay.get("dual_sweet_spot"):
        badge = " 🟢 EXECUTION+"
    elif overlay.get("spread_sweet_spot"):
        badge = " 🟢 SPREAD+"
    elif overlay.get("total_sweet_spot"):
        badge = " 🟢 TOTAL+"
    elif overlay.get("spread_avoid") or overlay.get("total_avoid"):
        badge = " 🔴 AVOID"

    with st.expander(
        f"{away} @ {home}: Take {spread_text} / {total_text}"
        f"{badge} — {tier}",
        expanded=False
    ):
        st.write("Projected Margin (Home):", round(model["projected_margin_home"], 2))
        st.write("Spread Edge:", round(spread_edge, 2))
        st.write("Projected Total:", round(model["projected_total"], 2))
        st.write("Total Edge:", round(total_edge, 2))
        st.write("Parlay Edge Score:", round(parlay_score, 2))
        st.write("Confidence Tier:", tier)
        st.write("Historical Win Rate:", round(calibration["historical_bucket_win_rate"], 3))
        st.write("Actionability:", model["actionability"])