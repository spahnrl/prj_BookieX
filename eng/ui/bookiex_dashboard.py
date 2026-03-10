# bookiex_dashboard.py
# Executive View — Correct Field Mapping

import streamlit as st
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo


# --------------------------------------------------
# CONFIG
# --------------------------------------------------

NBA_DAILY_DIR = Path("data/daily")
NCAAM_DAILY_DIR = Path("data/ncaam/daily")

NBA_HEADER_ICON = "assets/RS_JP_BookieX_v02.png"
NCAAM_HEADER_ICON = "assets/RS_JP_BookieX_v04_COLLEGE.png"

# Kelly / execution overlay assumptions
# Edit these as new backtesting information becomes available.
DUAL_SWEET_SPOT_WIN_PCT = 0.571
SPREAD_SWEET_SPOT_WIN_PCT = 0.546
TOTAL_SWEET_SPOT_WIN_PCT = 0.548

# Standard -110 odds
KELLY_PAYOUT_RATIO = 100 / 110

# Project root for logs/attribution_report.json
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ATTRIBUTION_REPORT_PATH = PROJECT_ROOT / "logs" / "attribution_report.json"

# Backtest reference date shown to user
EXECUTION_OVERLAY_LAST_UPDATED = "3/6/2025"

# Execution overlay reference table shown in UI
EXECUTION_OVERLAY_PERFORMANCE = [
    {"Bucket": "Dual Sweet Spot", "Games": 42, "Win%": 0.571, "ROI": 0.091},
    {"Bucket": "Spread Sweet Spot", "Games": 108, "Win%": 0.546, "ROI": 0.052},
    {"Bucket": "Total Sweet Spot", "Games": 62, "Win%": 0.548, "ROI": 0.047},
    {"Bucket": "Neutral", "Games": 50, "Win%": 0.520, "ROI": 0.033},
    {"Bucket": "Avoid", "Games": 214, "Win%": 0.486, "ROI": -0.068},
    {"Bucket": "All Games", "Games": 476, "Win%": 0.519, "ROI": -0.001},
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

files = sorted(DAILY_DIR.glob(file_pattern))


if league == "NBA":
    date_map = {f.name.split("_")[2]: f for f in files}
else:
    date_map = {f.name.split("_")[3]: f for f in files}

# Sidebar: current bankroll for Kelly sizing (replaces fixed example bankroll)
current_bankroll = st.sidebar.number_input(
    "Current Bankroll ($)",
    min_value=0,
    value=1000,
    step=100,
    help="Your actual balance for Kelly stake sizing.",
)

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

# Attribution ingestion: full report for System Health bar
def load_attribution_report() -> dict | None:
    """Read logs/attribution_report.json. Returns full report dict or None."""
    if not ATTRIBUTION_REPORT_PATH.exists():
        return None
    try:
        with open(ATTRIBUTION_REPORT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None

# System Health bar: Strategy B (Kelly) ROI% + Total P&L; green if positive, red if negative
_attribution = load_attribution_report()
_sb = (_attribution or {}).get("strategy_b_kelly") or {}
_kelly_roi = _sb.get("yield_roi_pct")
_kelly_pnl = _sb.get("total_pnl")
if _kelly_roi is not None and _kelly_pnl is not None:
    _roi_color = "#2ecc71" if (_kelly_roi or 0) >= 0 else "#e74c3c"
    _pnl_color = "#2ecc71" if (_kelly_pnl or 0) >= 0 else "#e74c3c"
    st.markdown(
        f"<div style='background: linear-gradient(90deg, #0f1c2e 0%, #1f2f4a 100%); "
        f"padding: 12px 18px; border-radius: 8px; margin-bottom: 16px;'>"
        f"<strong style='color: #fff;'>System Health</strong> — "
        f"<span style='color: #7fdbff;'>Strategy B (Kelly) ROI%</span>: "
        f"<strong style='color: {_roi_color};'>{_kelly_roi:+.2f}%</strong> &nbsp;|&nbsp; "
        f"<span style='color: #7fdbff;'>Total P&L</span>: "
        f"<strong style='color: {_pnl_color};'>${_kelly_pnl:+,.2f}</strong>"
        f"</div>",
        unsafe_allow_html=True,
    )
elif _kelly_roi is not None:
    _roi_color = "#2ecc71" if (_kelly_roi or 0) >= 0 else "#e74c3c"
    st.markdown(
        f"<div style='background: linear-gradient(90deg, #0f1c2e 0%, #1f2f4a 100%); "
        f"padding: 12px 18px; border-radius: 8px; margin-bottom: 16px;'>"
        f"<strong style='color: #fff;'>System Health</strong> — "
        f"<span style='color: #7fdbff;'>Strategy B (Kelly) ROI%</span>: "
        f"<strong style='color: {_roi_color};'>{_kelly_roi:+.2f}%</strong>"
        f"</div>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        "<div style='background: #2d2d2d; padding: 12px 18px; border-radius: 8px; margin-bottom: 16px;'>"
        "<strong style='color: #fff;'>System Health</strong> — "
        "<span style='color: #888;'>Strategy B (Kelly) ROI% / Total P&L: n/a</span> "
        "(run analysis_041_agent_attribution.py to populate)</div>",
        unsafe_allow_html=True,
    )


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

    if spread_pick == "HOME":
        return f"{home} ({spread_line:+.1f})"
    if spread_pick == "AWAY":
        return f"{away} ({-spread_line:+.1f})"
    return "No Spread Pick"


def calculate_full_kelly(win_pct: float, b: float) -> float:
    q = 1 - win_pct
    kelly = ((b * win_pct) - q) / b
    return max(kelly, 0)


def get_kelly_regime(g: dict):
    overlay = g.get("execution_overlay", {}) or {}

    if overlay.get("dual_sweet_spot"):
        return "Dual Sweet Spot", DUAL_SWEET_SPOT_WIN_PCT

    if overlay.get("spread_sweet_spot") and not overlay.get("spread_avoid"):
        return "Spread Sweet Spot", SPREAD_SWEET_SPOT_WIN_PCT

    if overlay.get("total_sweet_spot") and not overlay.get("total_avoid"):
        return "Total Sweet Spot", TOTAL_SWEET_SPOT_WIN_PCT

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

    st.markdown("## 🍀 Kelly Bet Sizing Strategy")

    st.write(
        "The Kelly section shows a **full Kelly example** using historical win rates from the current execution regime."
    )

    st.write(
        "The current regime assumptions are:\n"
        f"• **Dual Sweet Spot** win rate = {DUAL_SWEET_SPOT_WIN_PCT:.3f}\n"
        f"• **Spread Sweet Spot** win rate = {SPREAD_SWEET_SPOT_WIN_PCT:.3f}\n"
        f"• **Total Sweet Spot** win rate = {TOTAL_SWEET_SPOT_WIN_PCT:.3f}\n"
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

with open(file_path, "r", encoding="utf-8") as f:
    data = json.load(f)

games = data.get("games", [])

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

# --------------------------------------------------
# KELLY BET SIZING MODEL
# --------------------------------------------------

with st.expander("🍀 KBX Bet Sizing Strateg'ery 🌵", expanded=False):
    kelly_rows = []

    for g in games:
        identity = g.get("identity", {})
        market = g.get("market_state", {})
        model = g.get("model_output", {})
        regime_name, regime_win_pct = get_kelly_regime(g)

        if regime_name is None:
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
            pick_text = f"{total_pick} ({total_line})" if total_pick else "No Total Pick"
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
    else:
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
    st.markdown(
        f"**Execution Overlay Backtest Reference — Last Updated:** "
        f"{EXECUTION_OVERLAY_LAST_UPDATED}"
    )
    st.table(EXECUTION_OVERLAY_PERFORMANCE)


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
        key=lambda g: g["calibration_tags"]["historical_bucket_win_rate"],
        reverse=True
    )


# --------------------------------------------------
# GAMES LOOP START
# --------------------------------------------------

for g in games:
    identity = g["identity"]
    market = g["market_state"]
    model = g["model_output"]
    edge = g["edge_metrics"]
    calibration = g["calibration_tags"]
    arb = g.get("arbitration") or {}
    overlay = g.get("execution_overlay") or {}

    away = identity["away_team"]
    home = identity["home_team"]

    spread_line = market["spread_home_last"]
    total_line = market["total_last"]

    spread_pick = model.get("spread_pick")
    total_pick = model.get("total_pick")

    spread_text = format_spread_text(home, away, spread_line, spread_pick)

    if total_pick:
        total_text = f"{total_pick} ({total_line})"
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
    elif tier == "MODERATE":
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
    explanation = str(model.get("Explanation") or model.get("explanation") or "")
    is_value_peak = (
        "VALUE PEAK REACHED" in agent_reasoning
        or "VALUE PEAK REACHED" in confidence_reason
        or "VALUE PEAK REACHED" in explanation
    )
    if is_value_peak:
        badge += " 🔥 TOP AGENT PICK"

    # Matchup key: normalized to match attribution report for 1:1 tracking (full "Away @ Home")
    matchup_label = format_matchup_attribution(away, home)

    expander_label = (
        f"{matchup_label}: Take {spread_text} / {total_text}"
        f"{badge} — {tier} | {parlay_pct}%"
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
        st.write(f"Market: {spread_line} | Total {total_line}")

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

        st.write("Spread Pick:", model["spread_pick"])
        st.write("Projected Margin (Home):", safe_round(model.get("projected_margin_home", 0), 2))
        st.write("Spread Edge:", safe_round(spread_edge, 2))

        st.write("Total Pick:", model["total_pick"])
        st.write("Projected Total:", safe_round(model.get("projected_total", 0), 2))
        st.write("Total Edge:", safe_round(total_edge, 2))

        st.write("Parlay Edge Score:", safe_round(parlay_score, 2))

        st.subheader("Structure")

        st.write("Confidence Tier:", tier)
        st.write("Cluster Alignment:", model.get("cluster_alignment"))
        st.write("Arbitration Cluster:", model.get("arbitration_cluster"))

        st.write("Consensus Books:", market.get("consensus_book_count"))
        st.write("All-Time Snapshots:", market.get("all_time_snapshot_count"))

        st.write("Spread Disagreement:", arb.get("spread", {}).get("disagreement_flag"))
        st.write("Total Disagreement:", arb.get("total", {}).get("disagreement_flag"))

        st.subheader("History")

        st.write("Edge Bucket:", calibration["edge_bucket"])
        st.write(
            "Historical Win Rate:",
            safe_round(calibration.get("historical_bucket_win_rate", 0), 3)
        )

        st.write("Spread Percentile:", edge["spread_edge_percentile"])
        st.write("Total Percentile:", edge["total_edge_percentile"])

        st.subheader("Decision")
        st.subheader("Execution Overlay")

        st.write("Spread Sweet Spot:", overlay.get("spread_sweet_spot"))
        st.write("Total Sweet Spot:", overlay.get("total_sweet_spot"))
        st.write("Dual Sweet Spot:", overlay.get("dual_sweet_spot"))
        st.write("Spread Avoid:", overlay.get("spread_avoid"))
        st.write("Total Avoid:", overlay.get("total_avoid"))

        regime_name, regime_win_pct = get_kelly_regime(g)
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

        st.write("Actionability:", model["actionability"])
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

                if model_name == "MonkeyDarts_v2":
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

# --------------------------------------------------
# GAMES LOOP END
# --------------------------------------------------