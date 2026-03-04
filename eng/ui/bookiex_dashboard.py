# bookiex_dashboard.py
# Executive View — Correct Field Mapping

import streamlit as st
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

DAILY_DIR = Path("data/daily")


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

# --------------------------------------------------
# LAST UPDATE (CST)
# --------------------------------------------------

last_modified_utc = datetime.fromtimestamp(
    file_path.stat().st_mtime,
    tz=ZoneInfo("UTC")
)

last_modified_cst = last_modified_utc.astimezone(
    ZoneInfo("America/Chicago")
)

last_update_str = last_modified_cst.strftime(
    "%m/%d/%Y %I:%M %p"
)

with open(file_path, "r", encoding="utf-8") as f:
    data = json.load(f)

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
    st.markdown(
        f"<div style='color:#d0d0d0; font-size:14px; margin-top:4px;'>"
        f"Last Update: {last_update_str} CST"
        f"</div>",
        unsafe_allow_html=True
    )


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

        dual = overlay.get("dual_sweet_spot")
        spread = overlay.get("spread_sweet_spot")
        total = overlay.get("total_sweet_spot")

        # Priority scoring
        if dual:
            return 3
        if spread or total:
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

    st.markdown("## 🟢 Execution Badges (Rule-Based Overlay)")

    st.write("Execution badges are triggered by specific statistical filters:")

    st.markdown("### Sweet Spot Rules")

    st.write(
        "• **Spread Sweet Spot**:\n"
        "  - |Spread Edge| between 2 and 8 points\n"
        "  - Confidence Tier HIGH or MODERATE\n"
        "  - Not flagged as market disagreement\n"
    )

    st.write(
        "• **Total Sweet Spot**:\n"
        "  - |Total Edge| between 4 and 12 points\n"
        "  - Confidence Tier HIGH or MODERATE\n"
        "  - Not in extreme total bucket (<225 or >242)\n"
    )

    st.markdown("### Badge Meaning")

    st.write(
        "• 🟢 EXECUTION+ = Spread and Total both meet sweet spot rules\n"
        "• 🟢 SPREAD+ = Spread meets sweet spot rules\n"
        "• 🟢 TOTAL+ = Total meets sweet spot rules\n"
        "• 🔴 AVOID = Falls in historically unstable edge regime\n"
        "• (no badge) = Neutral execution zone (no statistical sweet spot or avoid trigger)\n"
    )

    st.write(
        "Execution badges are derived from backtested performance pockets "
        "and represent where the model has historically performed best."
    )

    st.markdown("## 🔥 Top 2 Spread Sweet Spots")

    st.write(
        "This section identifies the two strongest spread bets on the slate "
        "based on historical sweet spot performance."
    )

    st.write(
        "Selection priority:\n"
        "• Must qualify as **Spread Sweet Spot**\n"
        "• Cannot be flagged as Avoid\n"
        "• Confidence Tier ranked HIGH > MODERATE > LOW\n"
        "• Larger spread edge ranks higher within tier\n"
    )

    st.write(
        "This is a bet-centric ranking, meaning spreads are selected "
        "across different games if they statistically rank strongest."
    )

    st.write(
        "The goal is to isolate the highest historical ROI regime "
        "without requiring same-game pairing."
    )

    st.markdown("---")

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

    st.markdown("## 💰 Expected Value & Kelly Guidance (Spread Only)")

    st.write(
        "For games that qualify as **Spread Sweet Spot**, the dashboard displays "
        "expected value and Kelly sizing guidance."
    )

    st.write(
        "These calculations are based on historical backtested performance "
        "of the Spread Sweet Spot regime."
    )

    st.markdown("### Assumptions Used")

    st.write(
        "• Historical Win Rate: 56.6%\n"
        "• Standard -110 odds\n"
        "• Risk $110 to win $100\n"
    )

    st.markdown("### What the Numbers Mean")

    st.write(
        "• **Expected Value (EV)** shows the projected percentage return "
        "per dollar risked based on historical regime performance.\n"
        "  Spread Sweet Spot historically produced ~+8–9% ROI."
    )

    st.write(
        "• **Kelly Fraction** estimates optimal bankroll sizing "
        "based on the edge and payout structure.\n"
        "  Full Kelly ≈ 8–9% of bankroll.\n"
        "  Half Kelly (more conservative) ≈ 4%."
    )

    st.write(
        "These numbers assume the historical win rate continues. "
        "If performance regresses toward 52–53%, optimal sizing shrinks significantly."
    )

    st.markdown("---")

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
# --------------------------------------------------
# 🔥 TOP SPREAD SWEET SPOTS (Strict Regime View)
# --------------------------------------------------

def spread_rank_score(g):
    overlay = g.get("execution_overlay", {})
    model = g.get("model_output", {})
    edge = g.get("edge_metrics", {})

    # Must be spread sweet spot and not avoid
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

    top_n = min(2, len(qualified_spreads))

    for _, g in qualified_spreads[:top_n]:

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

    if len(qualified_spreads) == 1:
        st.write("Only 1 qualifying Spread Sweet Spot on this slate.")

    st.markdown("---")

else:

    st.markdown("## 🔥 Top Spread Sweet Spots")
    st.write("No qualifying Spread Sweet Spots on this slate.")
    st.markdown("---")

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
    overlay = g.get("execution_overlay") or {}

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
        spread_text = f"{away} ({spread_line})"
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

    # --------------------------------------------------
    # EXECUTION BADGE (Minimal System)
    # --------------------------------------------------

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
            f"{badge} — {tier} | {parlay_pct}%",
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

        st.subheader("Execution Overlay")

        st.write("Spread Sweet Spot:", overlay.get("spread_sweet_spot"))
        st.write("Total Sweet Spot:", overlay.get("total_sweet_spot"))
        st.write("Dual Sweet Spot:", overlay.get("dual_sweet_spot"))
        st.write("Spread Avoid:", overlay.get("spread_avoid"))
        st.write("Total Avoid:", overlay.get("total_avoid"))
        # --------------------------------------------------
        # EV + Kelly (Spread Only - Informational)
        # --------------------------------------------------

        if overlay.get("spread_sweet_spot") and not overlay.get("spread_avoid"):

            HISTORICAL_P = 0.566
            b = 100 / 110  # payout ratio
            q = 1 - HISTORICAL_P

            ev_pct = (HISTORICAL_P * b) - q
            kelly = ((b * HISTORICAL_P) - q) / b

            if kelly < 0:
                kelly = 0

            st.subheader("📈 Expected Value Guidance (Spread Regime)")

            st.write(f"Historical Win Rate (Spread Sweet Spot): {HISTORICAL_P:.3f}")
            st.write(f"Expected Value per $1 Risked: {ev_pct:.3f}")
            st.write(f"Full Kelly: {kelly:.3f} (Fraction of bankroll)")
            st.write(f"Half Kelly: {kelly / 2:.3f}")

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
            final_spread = model.get("spread_pick")
            final_total = model.get("total_pick")

            for model_name, model_data in models.items():

                model_spread = model_data.get("spread_pick")
                model_total = model_data.get("total_pick")

                spread_align = model_spread == final_spread
                total_align = model_total == final_total

                # --------------------------------------------------
                # ICON LOGIC
                # --------------------------------------------------

                if spread_align and total_align:
                    icon = "🟢"
                elif spread_align and not total_align:
                    icon = "🟡 T"
                elif not spread_align and total_align:
                    icon = "🟡 S"
                else:
                    icon = "🔴"

                # Mark models excluded from arbitration
                if model_name == "MonkeyDarts_v2":
                    expander_label = f"{icon} {model_name} 🚫 (Excluded from Arbitration)"
                else:
                    expander_label = f"{icon} {model_name}"

                with st.expander(expander_label):

                    st.write("Spread Pick:", model_spread)
                    st.write("Spread Edge:", round(model_data.get("spread_edge", 0), 2))

                    st.write("Total Pick:", model_total)
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