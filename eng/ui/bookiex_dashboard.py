# bookiex_dashboard.py
# Executive View — Correct Field Mapping

import streamlit as st
import json
from pathlib import Path

DAILY_DIR = Path("data/daily")

st.set_page_config(page_title="BookieX", layout="wide")
# st.title("🏀 BookieX — Today’s Games & Model View")
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
    st.image("assets/RS_JP_BookieX_v02.png", width=90)

with col2:
    st.markdown(
        "<h1 style='margin-bottom:0;'>BookieX — Today’s Games & Model View</h1>",
        unsafe_allow_html=True
    )

# --------------------------------------------------
# LOAD FILE
# --------------------------------------------------

files = sorted(DAILY_DIR.glob("daily_view_*_v1.json"))

if not files:
    st.error("No DAILY_VIEW files found.")
    st.stop()

date_map = {f.name.split("_")[2]: f for f in files}

selected_date = st.selectbox(
    "Select Date",
    sorted(date_map.keys(), reverse=True)
)

file_path = date_map[selected_date]

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
        "Parlay Edge",
        "Spread Edge",
        "Total Edge",
        "Confidence Tier",
        "Calibration Win Rate"
    ]
)

if sort_option == "Parlay Edge":
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
# DISPLAY
# --------------------------------------------------
# --------------------------------------------------
# FIELD GUIDE (Dummy Card)
# --------------------------------------------------

with st.expander("📘 How to Read This Dashboard", expanded=False):
    st.markdown("---")

    st.markdown("## 🧾 Top Row Summary (Game Roll-Up Line)")

    st.write(
        "Each game appears as a single summary line in this format:"
    )

    st.code(
        "Charlotte @ Indiana: Take Indiana (+13) / OVER (228.5) — HIGH | 63%"
    )

    st.write(
        "**Breakdown of the right side (HIGH | 63%)**:"
    )

    st.write(
        "• **HIGH** = Confidence Tier\n"
        "  This measures structural agreement across internal models.\n"
        "  HIGH means multiple models align directionally and the edge exceeds minimum execution thresholds."
    )

    st.write(
        "• **63%** = Overall Signal Strength\n"
        "  This is a normalized score derived from the Parlay Edge Score "
        "(spread edge + total edge combined).\n"
        "  It reflects how far the models differ from the market."
    )

    st.write(
        "The percentage is not a win probability.\n"
        "It represents magnitude of model disagreement with the sportsbook line."
    )

    st.markdown("### Interpretation")

    st.write(
        "A game showing **HIGH | 63%** means:\n"
        "- Strong multi-model structural alignment\n"
        "- Meaningful statistical deviation from the market\n"
        "- Meets internal actionability thresholds"
    )

    st.write(
        "Lower tiers (MODERATE, LOW) indicate weaker model agreement or smaller edges."
    )

    st.markdown("## 🧠 What This Dashboard Is Doing")

    st.write(
        "This page compares market betting lines to multiple internal models. "
        "We are looking for differences (called 'edges') between what sportsbooks expect "
        "and what our models project."
    )

    st.markdown("---")

    st.markdown("## 🔥 Signal Strength Bars")

    st.write(
        "**Overall Signal (Top Bar)** shows the combined strength of the opportunity. "
        "It is based on how far the models differ from the market (spread + total combined)."
    )

    st.write(
        "- Green = Strong structural agreement across models."
        "\n- Orange = Moderate agreement."
        "\n- Red = Weak agreement."
    )

    st.write(
        "**Spread Strength (Thin Blue Bar)** shows how large the model’s predicted "
        "margin differs from the market spread."
    )

    st.write(
        "**Total Strength (Thin Blue Bar)** shows how far the projected total "
        "differs from the market over/under line."
    )

    st.write(
        "Bigger bars mean larger differences. Larger differences can mean more opportunity — "
        "but not always more probability."
    )

    st.markdown("---")

    st.markdown("## 📊 Key Numbers Explained")

    st.write(
        "**Projected Margin (Home)**: "
        "How many points the model thinks the home team will win by."
    )

    st.write(
        "**Spread Edge**: "
        "Model projection minus the sportsbook line. "
        "Positive or negative direction indicates value relative to the market."
    )

    st.write(
        "**Projected Total**: "
        "How many combined points the model expects in the game."
    )

    st.write(
        "**Total Edge**: "
        "Difference between projected total and market total."
    )

    st.write(
        "**Parlay Edge Score**: "
        "Combined measure of spread and total differences. "
        "Used as a simple overall strength indicator."
    )

    st.markdown("---")

    st.markdown("## 🏗 Structure vs Decision")

    st.write(
        "**Confidence Tier** measures how strongly multiple models agree. "
        "This is structural strength — not a guarantee of outcome."
    )

    st.write(
        "**Actionability** means the edge passes a minimum threshold "
        "for execution. It does not mean it will win."
    )

    st.markdown("---")

    st.markdown("## ⚠ Important")

    st.write(
        "Large edges do not guarantee wins. "
        "This system looks for long-term statistical advantages, not certainty."
    )

# --------------------------------------------------
# GAMES
# --------------------------------------------------


# --------------------------------------------------
# GAMES LOOP START
# --------------------------------------------------

for g in games:

    # --------------------------------------------------
    # EXTRACT JSON SECTIONS (Game-Level Data)
    # --------------------------------------------------
    identity = g["identity"]
    market = g["market_state"]
    model = g["model_output"]
    edge = g["edge_metrics"]
    calibration = g["calibration_tags"]
    arb = g.get("arbitration") or {}

    # --------------------------------------------------
    # BASIC IDENTIFIERS
    # --------------------------------------------------
    away = identity["away_team"]
    home = identity["home_team"]

    spread_line = market["spread_home_last"]
    total_line = market["total_last"]

    spread_pick = model.get("spread_pick")
    total_pick = model.get("total_pick")

    # --------------------------------------------------
    # BUILD HUMAN-READABLE BET TEXT
    # --------------------------------------------------

    if spread_pick == "HOME":
        spread_text = f"{home} (+{spread_line})"
    elif spread_pick == "AWAY":
        spread_text = f"{away} (-{spread_line})"
    else:
        spread_text = "No Spread Pick"

    if total_pick:
        total_text = f"{total_pick} ({total_line})"
    else:
        total_text = "No Total Pick"

    # --------------------------------------------------
    # CALCULATE SIGNAL STRENGTH %
    # --------------------------------------------------

    parlay_score = edge.get("parlay_edge_score", 0)
    spread_edge = edge.get("spread_edge", 0)
    total_edge = edge.get("total_edge", 0)

    MAX_PARLAY = 20
    MAX_COMPONENT = 12

    parlay_pct = int(min(abs(parlay_score) / MAX_PARLAY, 1.0) * 100)
    spread_pct = int(min(abs(spread_edge) / MAX_COMPONENT, 1.0) * 100)
    total_pct = int(min(abs(total_edge) / MAX_COMPONENT, 1.0) * 100)

    tier = model.get("confidence_tier", "LOW")

    # --------------------------------------------------
    # COLOR SYSTEM (For Bars)
    # --------------------------------------------------

    if tier == "HIGH":
        main_color = "#2ecc71"
    elif tier == "MODERATE":
        main_color = "#f39c12"
    else:
        main_color = "#e74c3c"

    component_color = "#3498db"

    # --------------------------------------------------
    # GAME ROLL-UP HEADER (Collapsed View)
    # --------------------------------------------------

    with st.expander(
        f"{away} @ {home}: Take {spread_text} / {total_text} "
        f"— {tier} | {parlay_pct}%",
        expanded=False
    ):

        # --------------------------------------------------
        # BASIC GAME INFO
        # --------------------------------------------------

        st.write(f"Tipoff: {identity.get('tip_time_cst', 'N/A')}")
        st.write(f"Market: {spread_line} | Total {total_line}")

        # --------------------------------------------------
        # SIGNAL STRENGTH SECTION
        # --------------------------------------------------

        st.markdown(f"### 🔥 Signal Strength — {tier}")

        # PRIMARY PARLAY BAR
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

        # SPREAD BAR
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

        # TOTAL BAR
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

        # --------------------------------------------------
        # MODEL VS MARKET
        # --------------------------------------------------

        st.subheader("Model vs Market")

        st.write("Spread Pick:", model["spread_pick"])
        st.write("Projected Margin (Home):", round(model["projected_margin_home"], 2))
        st.write("Spread Edge:", round(spread_edge, 2))

        st.write("Total Pick:", model["total_pick"])
        st.write("Projected Total:", round(model["projected_total"], 2))
        st.write("Total Edge:", round(total_edge, 2))

        st.write("Parlay Edge Score:", round(parlay_score, 2))

        # --------------------------------------------------
        # STRUCTURE
        # --------------------------------------------------

        st.subheader("Structure")

        st.write("Confidence Tier:", tier)
        st.write("Cluster Alignment:", model.get("cluster_alignment"))
        st.write("Arbitration Cluster:", model.get("arbitration_cluster"))

        st.write("Consensus Books:", market.get("consensus_book_count"))
        st.write("All-Time Snapshots:", market.get("all_time_snapshot_count"))

        st.write("Spread Disagreement:", arb.get("spread", {}).get("disagreement_flag"))
        st.write("Total Disagreement:", arb.get("total", {}).get("disagreement_flag"))

        # --------------------------------------------------
        # HISTORY
        # --------------------------------------------------

        st.subheader("History")

        st.write("Edge Bucket:", calibration["edge_bucket"])
        st.write(
            "Historical Win Rate:",
            round(calibration["historical_bucket_win_rate"], 3)
        )

        st.write("Spread Percentile:", edge["spread_edge_percentile"])
        st.write("Total Percentile:", edge["total_edge_percentile"])

        # --------------------------------------------------
        # DECISION
        # --------------------------------------------------

        st.subheader("Decision")

        st.write("Actionability:", model["actionability"])
        st.write("Reason:", model.get("confidence_reason"))

        # --------------------------------------------------
        # WHY SECTION
        # --------------------------------------------------

        st.subheader("Why")

        st.write(
            f"Spread edge = {round(spread_edge, 2)} "
            f"(Bucket {calibration['edge_bucket']} | "
            f"Historical Win Rate {round(calibration['historical_bucket_win_rate'], 3)})"
        )

        st.write(
            f"Confidence Tier = {tier} "
            f"(Cluster: {model.get('cluster_alignment')})"
        )

        if model.get("actionability") == "ACTION":
            st.write("Execution threshold met.")
        else:
            st.write("Below execution threshold.")

        # --------------------------------------------------
        # MODEL BREAKDOWN (Nested Expanders)
        # --------------------------------------------------

        st.subheader("Model Details")

        models = g.get("models") or {}

        if not models:
            st.write("No model details available.")
        else:
            for model_name, model_data in models.items():

                # Mark models excluded from arbitration
                if model_name == "MonkeyDarts_v2":
                    expander_label = f"{model_name} 🚫 (Excluded from Arbitration)"
                else:
                    expander_label = f"{model_name}"

                with st.expander(expander_label):

                    st.write("Spread Pick:", model_data.get("spread_pick"))
                    st.write("Spread Edge:", round(model_data.get("spread_edge", 0), 2))

                    st.write("Total Pick:", model_data.get("total_pick"))
                    st.write("Total Edge:", round(model_data.get("total_edge", 0), 2))

                    if model_data.get("parlay_edge_score") is not None:
                        st.write(
                            "Parlay Edge Score:",
                            round(model_data.get("parlay_edge_score"), 2)
                        )

                    context_flags = model_data.get("context_flags")
                    if context_flags:
                        st.write("Context Flags:", context_flags)

# --------------------------------------------------
# GAMES LOOP END
# --------------------------------------------------