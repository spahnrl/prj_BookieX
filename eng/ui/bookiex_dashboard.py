# bookiex_dashboard.py
# Executive View — Correct Field Mapping

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import os
import re
import requests
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
from eng.normalization.config import load_league_config

NBA_DAILY_DIR = get_daily_view_output_dir("nba")
NCAAM_DAILY_DIR = get_daily_view_output_dir("ncaam")

NBA_HEADER_ICON = "assets/RS_JP_BookieX_v02.png"
NCAAM_HEADER_ICON = "assets/RS_JP_BookieX_v04_COLLEGE.png"
DEFAULT_HEADER_ICON = NBA_HEADER_ICON

# Kelly / execution overlay assumptions
# Edit these as new backtesting information becomes available.
DUAL_SWEET_SPOT_WIN_PCT = 0.571
SPREAD_SWEET_SPOT_WIN_PCT = 0.546
TOTAL_SWEET_SPOT_WIN_PCT = 0.548

# Standard -110 odds
KELLY_PAYOUT_RATIO = 100 / 110

# Project root; attribution report path is league-specific (see _attribution_report_path_for_league).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
NORMALIZATION_CONFIG_DIR = PROJECT_ROOT / "configs" / "normalization" / "leagues"

try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
except Exception:
    pass

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

NBA_MODEL_LANES = [
    "Joel_Baseline_v1",
    "MarketPressure_v2",
    "MarketBlend_v1",
    "Momentum5Game_v1",
    "FatiguePlus_v3",
    "InjuryModel_v2",
    "MonkeyDarts_v2",
]
NCAAM_MODEL_LANES = [
    "ncaam_avg_score_model",
    "ncaam_momentum5_model",
    "ncaam_market_pressure_model",
]
NEW_LEAGUE_MODEL_STATUS = {
    "WNBA": {
        "template": "NBA",
        "lanes": NBA_MODEL_LANES,
        "notes": "WNBA is presented with the same model contract and display surface as NBA: baseline, market pressure, blend, momentum, fatigue, injury, and benchmark lanes.",
    },
    "NHL": {
        "template": "NCAAM",
        "lanes": NCAAM_MODEL_LANES,
        "notes": "NHL is presented with the same model contract and display surface as NCAAM: average score, last-5 momentum, and market pressure.",
    },
    "MLB": {
        "template": "WNBA",
        "lanes": [
            "MLB_MarketConsensus_v1",
            "MLB_SpreadValue_v1",
            "MLB_TotalValue_v1",
            "MLB_MarketValueBlend_v1",
        ],
        "notes": "MLB is presented with the same market-value daily contract as WNBA: consensus, run-line value, total value, and blended market-value lanes.",
    },
}

# --------------------------------------------------
# LOAD FILES
# --------------------------------------------------

def _load_dashboard_league_options() -> list[dict]:
    """Load enabled league options from normalization configs for the Streamlit selector."""
    label_by_key = {
        "mlb": "Baseball - MLB",
        "nba": "Basketball - NBA",
        "ncaam": "Basketball - NCAAM",
        "wnba": "Basketball - WNBA",
        "nhl": "Hockey - NHL",
    }
    display_by_key = {
        "mlb": "MLB",
        "nba": "NBA",
        "ncaam": "NCAAM",
        "wnba": "WNBA",
        "nhl": "NHL",
    }
    fallback = [
        {"label": label_by_key[key], "league_key": key, "display_name": display_by_key[key]}
        for key in ("mlb", "nba", "ncaam", "wnba", "nhl")
    ]
    if not NORMALIZATION_CONFIG_DIR.exists():
        return fallback

    options_by_label = {option["label"]: option for option in fallback}
    for path in sorted(NORMALIZATION_CONFIG_DIR.glob("*.json")):
        if ".sample" in path.name:
            continue
        try:
            config = load_league_config(path)
        except Exception:
            continue
        if not config.enabled:
            continue
        key = config.league_key.lower()
        if key not in label_by_key:
            continue
        label = label_by_key[key]
        options_by_label[label] = {
            "label": label,
            "league_key": key,
            "display_name": display_by_key[key],
        }
    return [options_by_label[label] for label in sorted(options_by_label)]


LEAGUE_OPTIONS = _load_dashboard_league_options()
_league_by_label = {option["label"]: option for option in LEAGUE_OPTIONS}
league_label = st.selectbox("League", list(_league_by_label), index=0)
league_meta = _league_by_label[league_label]
league_key = league_meta["league_key"]
league = league_meta["display_name"]

if league == "NBA":
    DAILY_DIR = NBA_DAILY_DIR
    file_pattern = "daily_view_*_v1.json"
    header_icon_path = NBA_HEADER_ICON
elif league == "NCAAM":
    DAILY_DIR = NCAAM_DAILY_DIR
    file_pattern = "daily_view_ncaam_*_v1.json"
    header_icon_path = NCAAM_HEADER_ICON
else:
    DAILY_DIR = PROJECT_ROOT / "data" / league_key / "daily"
    file_pattern = f"daily_view_{league_key}_*_v1.json"
    header_icon_path = DEFAULT_HEADER_ICON

files = list(DAILY_DIR.glob(file_pattern))

BRIDGE_SLATE_WARNING = (
    "Bridge slate only - not a predictive model output. No pick, edge, confidence, ROI, "
    "or backtest result has been generated yet."
)
BRIDGE_SLATE_COLUMNS = [
    "game_date",
    "commence_time",
    "display_matchup",
    "away_team",
    "home_team",
    "away_team_key",
    "home_team_key",
    "bookmaker_count",
    "market_count",
    "has_h2h",
    "has_spreads",
    "has_totals",
    "has_schedule_match",
    "status",
    "completed",
]

LIVE_ODDS_REGISTRY = {
    "NBA": {"sport_key": "basketball_nba", "enabled": True},
    "NCAAM": {"sport_key": "basketball_ncaab", "enabled": True},
    "NCAAB": {"sport_key": "basketball_ncaab", "enabled": True},
    "WNBA": {"sport_key": "basketball_wnba", "enabled": True},
    "NHL": {"sport_key": "icehockey_nhl", "enabled": True},
    "MLB": {"sport_key": "baseball_mlb", "enabled": True},
}
LIVE_ODDS_MARKETS = "h2h,spreads,totals"
LIVE_ODDS_REGION = "us"
LIVE_ODDS_FORMAT = "american"
LIVE_ODDS_URL = "https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
LIVE_ODDS_COLUMNS = [
    "sport",
    "commence_time",
    "away_team",
    "home_team",
    "bookmaker",
    "moneyline_away",
    "moneyline_home",
    "spread_away",
    "spread_away_price",
    "spread_home",
    "spread_home_price",
    "total",
    "over_price",
    "under_price",
    "last_update",
    "event_id",
]


def _get_odds_api_key_for_dashboard() -> str | None:
    key = os.getenv("ODDS_API_KEY")
    if key:
        return key
    try:
        key = st.secrets.get("ODDS_API_KEY")
    except Exception:
        key = None
    return str(key).strip() if key else None


def _live_requests_get(url: str, **kwargs):
    try:
        import certifi

        kwargs.setdefault("verify", certifi.where())
    except Exception:
        pass
    try:
        return requests.get(url, **kwargs)
    except requests.exceptions.SSLError:
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        kwargs["verify"] = False
        return requests.get(url, **kwargs)


def _market_by_key(bookmaker: dict) -> dict:
    markets = bookmaker.get("markets") if isinstance(bookmaker, dict) else []
    if not isinstance(markets, list):
        return {}
    return {
        str(market.get("key") or "").strip().lower(): market
        for market in markets
        if isinstance(market, dict)
    }


def _outcome_for_name(market: dict | None, name: str) -> dict:
    if not isinstance(market, dict):
        return {}
    outcomes = market.get("outcomes")
    if not isinstance(outcomes, list):
        return {}
    target = str(name or "").strip().lower()
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        if str(outcome.get("name") or "").strip().lower() == target:
            return outcome
    return {}


def _normalize_live_odds_rows(sport_label: str, events: list) -> list[dict]:
    rows = []
    for event in events:
        if not isinstance(event, dict):
            continue
        away_team = event.get("away_team") or ""
        home_team = event.get("home_team") or ""
        bookmakers = event.get("bookmakers") if isinstance(event.get("bookmakers"), list) else []
        for bookmaker in bookmakers:
            market_lookup = _market_by_key(bookmaker)
            h2h = market_lookup.get("h2h")
            spreads = market_lookup.get("spreads")
            totals = market_lookup.get("totals")

            away_ml = _outcome_for_name(h2h, away_team)
            home_ml = _outcome_for_name(h2h, home_team)
            away_spread = _outcome_for_name(spreads, away_team)
            home_spread = _outcome_for_name(spreads, home_team)
            over_total = _outcome_for_name(totals, "Over")
            under_total = _outcome_for_name(totals, "Under")

            last_update = (
                bookmaker.get("last_update")
                or (h2h or {}).get("last_update")
                or (spreads or {}).get("last_update")
                or (totals or {}).get("last_update")
                or ""
            )
            rows.append(
                {
                    "sport": sport_label,
                    "commence_time": event.get("commence_time") or "",
                    "away_team": away_team,
                    "home_team": home_team,
                    "bookmaker": bookmaker.get("title") or bookmaker.get("key") or "",
                    "moneyline_away": away_ml.get("price", ""),
                    "moneyline_home": home_ml.get("price", ""),
                    "spread_away": away_spread.get("point", ""),
                    "spread_away_price": away_spread.get("price", ""),
                    "spread_home": home_spread.get("point", ""),
                    "spread_home_price": home_spread.get("price", ""),
                    "total": over_total.get("point", under_total.get("point", "")),
                    "over_price": over_total.get("price", ""),
                    "under_price": under_total.get("price", ""),
                    "last_update": last_update,
                    "event_id": event.get("id") or "",
                }
            )
    return rows


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_live_odds_for_dashboard(
    sport_label: str,
    sport_key: str,
    api_key: str,
) -> dict:
    url = LIVE_ODDS_URL.format(sport_key=sport_key)
    params = {
        "apiKey": api_key,
        "regions": LIVE_ODDS_REGION,
        "markets": LIVE_ODDS_MARKETS,
        "oddsFormat": LIVE_ODDS_FORMAT,
        "dateFormat": "iso",
    }
    fetch_time = datetime.now(timezone.utc).isoformat()
    try:
        response = _live_requests_get(url, params=params, timeout=20)
        status_code = response.status_code
        if not response.ok:
            body = (response.text or "").strip()
            if len(body) > 400:
                body = body[:400] + "..."
            return {
                "ok": False,
                "status_code": status_code,
                "error": f"The Odds API returned HTTP {status_code}: {body}",
                "events": [],
                "rows": [],
                "fetch_time_utc": fetch_time,
            }
        events = response.json()
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "error": f"The Odds API request failed: {exc}",
            "events": [],
            "rows": [],
            "fetch_time_utc": fetch_time,
        }

    if not isinstance(events, list):
        return {
            "ok": False,
            "status_code": status_code,
            "error": "The Odds API response was not a list of events.",
            "events": [],
            "rows": [],
            "fetch_time_utc": fetch_time,
        }

    rows = _normalize_live_odds_rows(sport_label, events)
    return {
        "ok": True,
        "status_code": status_code,
        "error": None,
        "events": events,
        "rows": rows,
        "fetch_time_utc": fetch_time,
    }


def _render_live_odds_section(sport_label: str) -> bool:
    registry = LIVE_ODDS_REGISTRY.get(sport_label)
    if not registry or not registry.get("enabled"):
        return False

    sport_key = str(registry.get("sport_key") or "").strip()
    st.subheader("Live Odds")
    st.caption(
        "Source: The Odds API v4 odds endpoint. "
        f"Markets: `{LIVE_ODDS_MARKETS}` | Region: `{LIVE_ODDS_REGION}` | Odds: `{LIVE_ODDS_FORMAT}`"
    )

    if st.button("Refresh live odds", key=f"{sport_label.lower()}_live_odds_refresh"):
        _fetch_live_odds_for_dashboard.clear()

    api_key = _get_odds_api_key_for_dashboard()
    if not api_key:
        st.error(
            "Live odds are unavailable because `ODDS_API_KEY` is not configured in the "
            "environment or Streamlit secrets."
        )
        return False

    result = _fetch_live_odds_for_dashboard(sport_label, sport_key, api_key)
    events = result.get("events") or []
    rows = result.get("rows") or []

    with st.expander("Live odds diagnostics", expanded=False):
        st.write("Selected sport:", sport_label)
        st.write("Sport key:", sport_key)
        st.write("Events returned:", len(events))
        st.write("Normalized rows:", len(rows))
        st.write("Last API fetch time:", result.get("fetch_time_utc") or "")
        st.write("Markets requested:", LIVE_ODDS_MARKETS)
        st.write("Region requested:", LIVE_ODDS_REGION)
        st.write("HTTP status:", result.get("status_code") or "N/A")

    if not result.get("ok"):
        st.error(result.get("error") or "The Odds API request failed.")
        return False

    if not events:
        st.info(f"No upcoming/live {sport_label} games were returned by The Odds API right now.")
        return False

    if not rows:
        st.warning(
            f"The Odds API returned {len(events)} {sport_label} event(s), but no bookmaker odds rows "
            "were available for h2h, spreads, or totals."
        )
        return False

    st.success(f"Loaded {len(events)} {sport_label} event(s) and {len(rows)} bookmaker odds row(s).")
    display_df = pd.DataFrame(rows, columns=LIVE_ODDS_COLUMNS).fillna("").astype(str)
    st.dataframe(display_df, width="stretch", hide_index=True)
    return True


def _bridge_slate_path(selected_league_key: str) -> Path:
    return PROJECT_ROOT / "data" / selected_league_key / "daily" / f"{selected_league_key}_daily_slate_bridge.json"


def _load_bridge_slate(selected_league_key: str) -> tuple[dict | None, Path, str | None]:
    path = _bridge_slate_path(selected_league_key)
    if not path.exists():
        return None, path, f"No bridge slate data for {selected_league_key.upper()}. Expected file: `{path.resolve()}`."
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        return None, path, f"Bridge slate file exists but could not be loaded: `{path.resolve()}`. Error: {exc}"
    if not isinstance(payload, dict):
        return None, path, f"Bridge slate file has an invalid shape: `{path.resolve()}`."
    games = payload.get("games")
    if not isinstance(games, list):
        return None, path, f"Bridge slate file is missing a `games` list: `{path.resolve()}`."
    return payload, path, None


def _render_bridge_slate_page() -> None:
    payload, bridge_path, error = _load_bridge_slate(league_key)

    current_bankroll_bridge = st.sidebar.number_input(
        "Current Bankroll ($)",
        min_value=0,
        value=1000,
        step=100,
        help="Your actual balance. Bridge slates do not calculate Kelly sizing yet.",
        key=f"{league_key}_bridge_bankroll",
    )
    qr_code_bridge_path = PROJECT_ROOT / "assets" / "qr-code_bookiex_v01.png"
    if qr_code_bridge_path.exists():
        st.sidebar.image(str(qr_code_bridge_path), width=220)

    col1, col2 = st.columns([1, 6])
    with col1:
        if Path(header_icon_path).exists():
            st.image(header_icon_path, width=90)
    with col2:
        st.markdown(
            f"<h1 style='margin-bottom:0;'>BookieX - {league} Odds Slate</h1>",
            unsafe_allow_html=True,
        )
        st.caption("Live odds first; local bridge artifact remains available below as a non-model fallback.")

    live_rows_displayed = _render_live_odds_section(league)

    st.markdown("---")
    st.subheader("Bridge Slate Artifact")
    st.caption(f"Source: `{bridge_path}`")

    if error:
        st.warning(error)
        return

    st.warning(BRIDGE_SLATE_WARNING)

    is_model_output = bool(payload.get("is_model_output"))
    is_roi_output = bool(payload.get("is_roi_output"))
    games = payload.get("games") or []
    record_count = int(payload.get("record_count") or len(games))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Slate Games", record_count)
    c2.metric("Model Output", "No" if not is_model_output else "Yes")
    c3.metric("ROI Output", "No" if not is_roi_output else "Yes")
    c4.metric("Current Bankroll", f"${current_bankroll_bridge:,}")

    rows = []
    for game in games:
        if not isinstance(game, dict):
            continue
        rows.append({column: game.get(column, "") for column in BRIDGE_SLATE_COLUMNS})

    if not rows:
        st.warning(f"Bridge slate loaded, but no game records were present in `{bridge_path.resolve()}`.")
        return

    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption(
        "Displayed fields come directly from the daily slate bridge artifact. "
        "No pick, edge, confidence, ROI, model score, or backtest-derived field is calculated here."
    )


def _render_new_league_model_status_page() -> None:
    status = NEW_LEAGUE_MODEL_STATUS.get(
        league,
        {
            "template": "NCAAM",
            "lanes": NCAAM_MODEL_LANES,
            "notes": f"{league} is configured in the UI, but its league-specific model artifacts have not been generated yet.",
        },
    )

    sidebar_bankroll = st.sidebar.number_input(
        "Current Bankroll ($)",
        min_value=0,
        value=1000,
        step=100,
        help="Your actual balance for Kelly stake sizing.",
        key=f"{league_key}_pending_bankroll",
    )
    qr_code_pending_path = PROJECT_ROOT / "assets" / "qr-code_bookiex_v01.png"
    if qr_code_pending_path.exists():
        st.sidebar.image(str(qr_code_pending_path), width=220)

    col1, col2 = st.columns([1, 6])
    with col1:
        if Path(header_icon_path).exists():
            st.image(header_icon_path, width=90)
    with col2:
        st.markdown(
            f"<h1 style='margin-bottom:0;'>BookieX - {league} Daily View</h1>",
            unsafe_allow_html=True,
        )
        st.caption(
            f"NBA-style dashboard shell. Model outputs and ROI stay disabled until real "
            f"{league} daily-view and backtest artifacts exist."
        )

    st.warning(
        f"{league} is available in the League dropdown, but no generated daily-view file exists yet at "
        f"`{DAILY_DIR.resolve()}`."
    )

    slate_dashboard_view = st.radio(
        "Dashboard view",
        ("Standard Slate View", "Pocket ROI View"),
        index=0,
        horizontal=True,
        help="Matches the NBA/NCAAM view switch; values are pending until league artifacts exist.",
    )

    st.markdown("**Last Odds Update:** Pending odds artifact")
    st.caption(f"{league} pockets: use Pocket ROI View for ranked best-pocket per game and positive-ROI diagnostics once backtests exist.")

    if slate_dashboard_view == "Pocket ROI View":
        st.caption(
            f"**Pocket ROI lens** - {league}; same presentation as {status['template']}, but waiting on "
            f"`{league_key}_model_pockets.json`, `{league_key}_ranked_pocket_opportunities.json`, "
            f"and `{league_key}_best_pocket_per_game.json`."
        )
        st.markdown("Per-game pocket summary from the **latest WNBA backtest** live leaderboard. Does not change authority or sweet-spot logic.")
        st.markdown("## Ranked Pocket Opportunities")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Rank": "Pending",
                        "Recommended Bet": "Pending daily view",
                        "Pocket Type": "Pending backtest",
                        "Pocket Models": " / ".join(status["lanes"]),
                        "State Signature": "Pending settled sample",
                        "ROI": "Pending",
                        "Win Rate": "Pending",
                        "Graded Games": "Pending",
                        "Why": f"Run the {league} pipeline/backtest to calculate the NCAAM-style pocket board.",
                        "Parlay Eligible": "Pending",
                    }
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        st.markdown("## Best 2-leg parlay (positive ROI only)")
        st.info(
            "Parlay builder is disabled until ranked pocket opportunities have positive historical ROI."
        )
        with st.expander("Best pocket per game (secondary summary)", expanded=False):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Rank": "Pending",
                            "Recommended Bet": "Pending daily view",
                            "Best Pocket Type": "Pending",
                            "Pocket Models": " / ".join(status["lanes"]),
                            "Pocket ROI": "Pending",
                            "Pocket Win Rate": "Pending",
                            "Pocket Games": "Pending",
                            "Why": f"Run the {league} pipeline/backtest to calculate NBA-style pocket summaries.",
                            "Parlay Eligible": "Pending",
                        }
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        st.subheader("Historical leaderboard validation (read-only)")
        st.dataframe(
            pd.DataFrame(
                [
                    {"metric": "Pair spread combo - top tercile", "graded": "Pending", "Win%": "Pending", "ROI": "Pending", "notes": "Requires pocket validation artifact"},
                    {"metric": "Cluster - strong authority spread", "graded": "Pending", "Win%": "Pending", "ROI": "Pending", "notes": "Requires settled backtest results"},
                    {"metric": "Pass candidates authority spread", "graded": "Pending", "Win%": "Pending", "ROI": "Pending", "notes": "Requires ranked opportunity artifact"},
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        return

    st.subheader("ROI / Predictive Value Surface")
    st.write(
        "These are the same decision-support slots used by the NCAAM dashboard. "
        "They are visible here now, but remain uncalculated until the league has settled-game backtests "
        "and pocket artifacts."
    )
    roi_rows = [
        {
            "Metric": "Execution Overlay ROI",
            "NBA/NCAAM Source": "analysis_039b execution overlay",
            "Display Contract": "Bucket, Games, Win%, ROI, Status",
            "Current Value": "Pending artifact",
            "Required Input": f"data/{league_key}/backtests/backtest_*/execution_overlay_performance.json",
        },
        {
            "Metric": "Pocket ROI",
            "NBA/NCAAM Source": "model pocket leaderboard",
            "Display Contract": "Rank, Recommended Bet, ROI, Win Rate, Graded Games",
            "Current Value": "Pending artifact",
            "Required Input": f"data/{league_key}/backtests/backtest_*/{league_key}_ranked_pocket_opportunities.json",
        },
        {
            "Metric": "Best Pocket Per Game",
            "NBA/NCAAM Source": "best pocket per game board",
            "Display Contract": "Best Pocket Type, Pocket ROI, Pocket Win Rate, Pocket Games",
            "Current Value": "Pending artifact",
            "Required Input": f"data/{league_key}/backtests/backtest_*/{league_key}_best_pocket_per_game.json",
        },
        {
            "Metric": "Pocket Validation ROI",
            "NBA/NCAAM Source": "leaderboard validation",
            "Display Contract": "Validation segment, Graded, Win%, ROI",
            "Current Value": "Pending artifact",
            "Required Input": f"data/{league_key}/backtests/backtest_*/{league_key}_pocket_leaderboard_validation.json",
        },
        {
            "Metric": "Kelly / Bankroll Sizing",
            "NBA/NCAAM Source": "overlay win-rate by bucket",
            "Display Contract": "Current Bankroll, Win%, Kelly %, Stake",
            "Current Value": "Pending ROI + Win%",
            "Required Input": "Positive, validated Win% by execution bucket",
        },
    ]
    st.dataframe(pd.DataFrame(roi_rows), width="stretch", hide_index=True)

    with st.expander("KBX Bet Sizing System", expanded=False):
        st.warning(
            "Dynamic overlay data is unavailable for this league. Suggested Bet Sizing is pending "
            "until WNBA/NHL backtests populate execution bucket Win% and ROI."
        )
        st.markdown("### Suggested Bet Sizing")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Game": "Pending daily view",
                        "Pick": "Pending model edge",
                        "Regime": "Pending execution overlay",
                        "Bet $": "Pending",
                        "Models Align": "Pending",
                    }
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        st.markdown(
            "<sub>"
            f"1. Uses current bankroll (sidebar) = ${sidebar_bankroll:,}. "
            "2. Full Kelly will use historical win rate of the qualifying regime once available. "
            "3. Historical win rate is context, not guarantee."
            "</sub>",
            unsafe_allow_html=True,
        )

    st.subheader("Replicated Model Surface")
    st.write(status["notes"])
    model_rows = [
        {
            "Model Lane": model_name,
            "Source Template": status["template"],
            "UI Status": "Visible",
            "Calculation Status": "Waiting on league-specific input artifacts",
        }
        for model_name in status["lanes"]
    ]
    st.dataframe(pd.DataFrame(model_rows), width="stretch", hide_index=True)

    st.subheader("Model vs Market")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Field": "Spread Pick",
                    "NCAAM Contract": "selected model spread_pick",
                    "Current Value": "Pending",
                },
                {
                    "Field": "Projected Margin (Home)",
                    "NCAAM Contract": "home_line_proj",
                    "Current Value": "Pending",
                },
                {
                    "Field": "Spread Edge",
                    "NCAAM Contract": "spread_edge",
                    "Current Value": "Pending",
                },
                {
                    "Field": "Total Pick",
                    "NCAAM Contract": "total_pick",
                    "Current Value": "Pending",
                },
                {
                    "Field": "Projected Total",
                    "NCAAM Contract": "total_projection",
                    "Current Value": "Pending",
                },
                {
                    "Field": "Total Edge",
                    "NCAAM Contract": "total_edge",
                    "Current Value": "Pending",
                },
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    st.subheader("Pending Slate Preview")
    with st.expander(f"Pending {league} matchup card", expanded=True):
        st.write("Tipoff: Pending")
        st.write("Market: Pending spread | Total Pending")
        st.markdown("### Signal Strength - Pending")
        st.progress(0, text="Overall pending")
        st.progress(0, text="Spread Strength pending")
        st.progress(0, text="Total Strength pending")
        st.subheader("Model vs Market")
        st.write("Spread Pick:", "Pending")
        st.write("Projected Margin (Home):", "Pending")
        st.write("Spread Edge:", "Pending")
        st.write("Total Pick:", "Pending")
        st.write("Projected Total:", "Pending")
        st.write("Total Edge:", "Pending")
        st.subheader("Full Model Breakdown")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Model": model_name,
                        "Spread Pick": "Pending",
                        "Home Line Projection": "Pending",
                        "Spread Edge": "Pending",
                        "Total Pick": "Pending",
                        "Total Projection": "Pending",
                        "Total Edge": "Pending",
                    }
                    for model_name in status["lanes"]
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    st.subheader("Required Artifact Contract")
    artifact_rows = [
        {"Artifact": "Daily view JSON", "Expected Path": str(DAILY_DIR / file_pattern), "Status": "Missing"},
        {"Artifact": "Odds normalization config", "Expected Path": str(NORMALIZATION_CONFIG_DIR), "Status": "Present"},
        {"Artifact": "Final model view", "Expected Path": str(PROJECT_ROOT / "data" / league_key / "view"), "Status": "Missing"},
        {"Artifact": "Backtest outputs", "Expected Path": str(PROJECT_ROOT / "data" / league_key / "backtests"), "Status": "Missing"},
    ]
    st.dataframe(pd.DataFrame(artifact_rows), width="stretch", hide_index=True)

    st.info(
        "This page is intentionally not inventing picks. The next build pass needs to generate "
        f"`daily_view_{league_key}_<date>_v1.json` from real {league} schedule, odds, and model artifacts."
    )


def _date_from_name(path: Path, is_ncaam: bool) -> str:
    parts = path.name.split("_")
    if len(parts) >= 5 and parts[0] == "daily" and parts[1] == "view":
        return parts[3] if is_ncaam or parts[2] == league_key else parts[2]
    return parts[3] if is_ncaam else parts[2]


# For each date, use the file with the latest OS modification time (e.g. 5 AM vs 5 PM run).
by_date = defaultdict(list)
for f in files:
    by_date[_date_from_name(f, league == "NCAAM")].append(f)
date_map = {d: max(flist, key=lambda p: p.stat().st_mtime) for d, flist in by_date.items()}

if league in ("WNBA", "MLB"):
    new_daily_page_view = st.radio(
        f"{league} page",
        ("Daily View", "Live Odds Slate"),
        index=0,
        horizontal=True,
        help=(
            "Daily View uses the generated "
            f"{league} daily-view artifact and mirrors the NBA dashboard structure. "
            "Live Odds Slate keeps the current Odds API board."
        ),
    )
    if new_daily_page_view == "Live Odds Slate":
        _render_bridge_slate_page()
        st.stop()


def _resolve_pocket_recommended_bet_daily_games(
    games_selected: list,
    selected_date: str,
    leaderboard_doc: dict | None,
) -> tuple[list, str]:
    """
    Daily rows used to join pocket opportunities → lines/teams for **Recommended Bet**.

    Ranked/BPP rows come from artifacts keyed to the leaderboard's ``slate_date``. The dashboard
    ``games`` list is for **Select Date**. When those differ, load that slate's daily JSON from
    ``date_map`` so ``game_id`` joins resolve (UI-only).

    Returns:
        (games_for_index, join_mode) where join_mode is:
        - ``aligned`` — use ``games_selected`` (leaderboard date missing or matches selected).
        - ``leaderboard_slate`` — loaded games for leaderboard ``slate_date``.
        - ``mismatch_no_file`` — dates differ but no daily file for leaderboard date in ``date_map``.
    """
    lb = leaderboard_doc if isinstance(leaderboard_doc, dict) else {}
    lb_date = str(lb.get("slate_date") or "").strip()
    sel = str(selected_date).strip()
    if not lb_date or lb_date == sel:
        return games_selected, "aligned"
    if lb_date in date_map:
        path = date_map[lb_date]
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            gl = doc.get("games")
            if isinstance(gl, list) and gl:
                return gl, "leaderboard_slate"
        except Exception:
            pass
    return games_selected, "mismatch_no_file"


if not date_map and league == "NHL":
    _render_bridge_slate_page()
    st.stop()

if not date_map and league not in ("NBA", "NCAAM"):
    _render_new_league_model_status_page()
    st.stop()

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
        latest = _latest_nba_backtest_with_files(
            "nba_model_pockets.json",
            "nba_model_combo_pockets.json",
            "nba_current_game_pocket_view.json",
        )
        if latest is None:
            return None, None, None, None, None
        p1 = latest / "nba_model_pockets.json"
        p2 = latest / "nba_model_combo_pockets.json"
        p3 = latest / "nba_current_game_pocket_view.json"
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


def _latest_nba_backtest_with_files(*filenames: str) -> Path | None:
    root = get_backtest_output_root("nba")
    if not root.exists():
        return None
    subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
    candidates = [
        d for d in subdirs
        if all((d / name).exists() for name in filenames)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.stat().st_mtime)


_nba_pockets_doc, _nba_combo_doc, _nba_current_pockets_doc, _nba_live_pockets_doc, _nba_pockets_date = (
    _load_nba_pocket_artifacts() if league == "NBA" else (None, None, None, None, None)
)


def _load_nba_live_pocket_leaderboard() -> dict | None:
    """Optional nba_live_pocket_leaderboard.json from latest NBA backtest dir."""
    try:
        latest = _latest_nba_backtest_with_files("nba_live_pocket_leaderboard.json")
        if latest is None:
            return None
        p = latest / "nba_live_pocket_leaderboard.json"
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


_nba_live_pocket_leaderboard_doc = _load_nba_live_pocket_leaderboard() if league == "NBA" else None


def _load_nba_best_pocket_per_game() -> dict | None:
    """Optional nba_best_pocket_per_game.json from latest NBA backtest dir."""
    try:
        latest = _latest_nba_backtest_with_files("nba_best_pocket_per_game.json")
        if latest is None:
            return None
        p = latest / "nba_best_pocket_per_game.json"
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


_nba_best_pocket_doc = _load_nba_best_pocket_per_game() if league == "NBA" else None


def _load_nba_ranked_pocket_opportunities() -> dict | None:
    """Optional nba_ranked_pocket_opportunities.json from latest NBA backtest dir."""
    try:
        latest = _latest_nba_backtest_with_files("nba_ranked_pocket_opportunities.json")
        if latest is None:
            return None
        p = latest / "nba_ranked_pocket_opportunities.json"
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


_nba_ranked_pocket_doc = _load_nba_ranked_pocket_opportunities() if league == "NBA" else None


def _load_nba_pocket_leaderboard_validation() -> dict | None:
    """Optional nba_pocket_leaderboard_validation.json from latest NBA backtest dir."""
    try:
        latest = _latest_nba_backtest_with_files("nba_pocket_leaderboard_validation.json")
        if latest is None:
            return None
        p = latest / "nba_pocket_leaderboard_validation.json"
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


_nba_pocket_validation_doc = _load_nba_pocket_leaderboard_validation() if league == "NBA" else None


_ROBUSTNESS_RECOMMENDATION = {
    "KEEP": "Trust — held up out-of-sample and in the postseason.",
    "WATCH": "Monitor — mixed signal; not confirmed out-of-sample.",
    "FADE": "Fade — decayed recently or failed the postseason.",
    "KILL": "Remove — negative full-season or failed the hold-out.",
}


def _normalize_robustness_ctx(ctx: dict, analysis_dir_name: str) -> dict | None:
    """Flatten the timestamped tables.json (full ctx schema) into the stable join shape."""
    if not isinstance(ctx, dict):
        return None

    def _roi(row: dict, scope: str):
        sc = (row.get("scopes") or {}).get(scope)
        return sc.get("roi") if isinstance(sc, dict) else None

    def _project(row: dict, keys: list[str]) -> dict:
        out = {k: row.get(k) for k in keys}
        out.update({
            "rating": row.get("rating"),
            "trust_score": row.get("trust_score"),
            "full_roi": _roi(row, "full"),
            "second_half_roi": _roi(row, "second_half"),
            "recent_roi": _roi(row, "recent"),
            "postseason_roi": _roi(row, "postseason"),
            "flags": row.get("flags") or [],
            "recommendation": _ROBUSTNESS_RECOMMENDATION.get(row.get("rating"), ""),
        })
        return out

    singles = [_project(r, ["model", "market_type", "edge_bucket"]) for r in (ctx.get("single_rows") or [])]
    combos = [_project(r, ["market_type", "combo_kind", "models_key", "state_signature"])
              for r in (ctx.get("combo_rows") or [])]
    if not singles and not combos:
        return None
    return {
        "source": "analysis_fallback",
        "source_backtest_dir": ctx.get("backtest_dir"),
        "generated_at_utc": ctx.get("generated_at_utc"),
        "analysis_dir_name": analysis_dir_name,
        "singles": singles,
        "combos": combos,
    }


def _load_nba_pocket_robustness() -> dict | None:
    """Read-only NBA pocket robustness trust artifact.

    Prefers the stable file data/nba/view/nba_pocket_robustness_latest.json (emitted by
    tools/analysis/analyze_nba_pocket_robustness.py --emit-latest); falls back to the newest
    data/nba/analysis/pocket_robustness_*/pocket_robustness_tables.json. Returns a normalized
    dict {source, source_backtest_dir, generated_at_utc, singles, combos} or None if unavailable.
    """
    try:
        stable = PROJECT_ROOT / "data" / "nba" / "view" / "nba_pocket_robustness_latest.json"
        if stable.exists():
            with open(stable, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if isinstance(doc, dict) and (doc.get("singles") or doc.get("combos")):
                return {
                    "source": "stable",
                    "source_backtest_dir": doc.get("source_backtest_dir"),
                    "generated_at_utc": doc.get("generated_at_utc"),
                    "singles": doc.get("singles") or [],
                    "combos": doc.get("combos") or [],
                }
        analysis_root = PROJECT_ROOT / "data" / "nba" / "analysis"
        if analysis_root.exists():
            cands = [
                d for d in analysis_root.iterdir()
                if d.is_dir() and d.name.startswith("pocket_robustness_")
                and (d / "pocket_robustness_tables.json").exists()
            ]
            if cands:
                latest = max(cands, key=lambda d: d.stat().st_mtime)
                with open(latest / "pocket_robustness_tables.json", "r", encoding="utf-8") as f:
                    ctx = json.load(f)
                return _normalize_robustness_ctx(ctx, latest.name)
        return None
    except Exception:
        return None


def _robustness_lookups(doc: dict | None) -> dict:
    """Build join dicts: exact singles (model, market, bucket), combos (market, kind, models_key, sig),
    plus a conservative (model, market) fallback that keeps the lowest-trust row for that pair."""
    out: dict[str, dict] = {"singles": {}, "combos": {}, "singles_by_model_market": {}}
    if not isinstance(doc, dict):
        return out
    for r in doc.get("singles") or []:
        m = str(r.get("model") or "").strip()
        mt = str(r.get("market_type") or "").strip().lower()
        b = str(r.get("edge_bucket") or "").strip()
        if not (m and mt and b):
            continue
        out["singles"][(m, mt, b)] = r
        mm = (m, mt)
        prev = out["singles_by_model_market"].get(mm)
        if prev is None or (r.get("trust_score") or 0) < (prev.get("trust_score") or 0):
            out["singles_by_model_market"][mm] = r
    for r in doc.get("combos") or []:
        mt = str(r.get("market_type") or "").strip().lower()
        ck = str(r.get("combo_kind") or "").strip().lower()
        mk = str(r.get("models_key") or "").strip()
        sig = str(r.get("state_signature") or "").strip()
        if mt and ck and mk:
            out["combos"][(mt, ck, mk, sig)] = r
    return out


_nba_robustness_doc = _load_nba_pocket_robustness() if league == "NBA" else None
_nba_robustness_lk = _robustness_lookups(_nba_robustness_doc)


def _rpo_combo_kind(pocket_type) -> str | None:
    pt = str(pocket_type or "").strip().lower()
    if pt.startswith("pair_"):
        return "pair"
    if pt.startswith("triple_"):
        return "triple"
    return None


def _robustness_for_row(r: dict, lk: dict) -> tuple[dict | None, bool]:
    """Match a ranked-opportunity row to a robustness row.

    Returns (robustness_row_or_None, is_approx). Single-model rows join exactly on
    (model, market_type, edge_bucket); if edge_bucket is absent (older artifacts) they fall
    back to the conservative (model, market_type) row (is_approx=True). Combos join on
    (market_type, combo_kind, models_key, state_signature).
    """
    pt = str(r.get("pocket_type") or "").strip().lower()
    mt = str(r.get("market_type") or "").strip().lower()
    if pt == "single_model":
        m = str(r.get("model_name") or r.get("model") or "").strip()
        b = str(r.get("edge_bucket") or "").strip()
        if m and mt and b:
            hit = lk["singles"].get((m, mt, b))
            if hit is not None:
                return hit, False
        if m and mt:
            hit = lk["singles_by_model_market"].get((m, mt))
            if hit is not None:
                return hit, True
        return None, False
    ck = _rpo_combo_kind(pt)
    if ck:
        mk = str(r.get("models_key") or "").strip()
        sig = str(r.get("state_signature") or "").strip()
        hit = lk["combos"].get((mt, ck, mk, sig))
        if hit is not None:
            return hit, False
    return None, False


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
    *,
    join_mode: str = "aligned",
) -> str:
    """
    Plain-English wager for Pocket ROI tables (UI-only; no authority change).
    Spread: '{matchup}: Take {team} ({line})' via format_spread_text.
    Total: '{matchup}: OVER|UNDER ({total})' from market_state.total_last.

    ``join_mode`` — when ``mismatch_no_file``, missing daily join omits the repetitive
    "(no matching slate row)" suffix; a table-level warning explains the fix.
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
        if join_mode == "mismatch_no_file":
            return f"{matchup}: {pick_s or '—'}"
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


_date_options = sorted(date_map.keys(), reverse=True)
_today_central = datetime.now(ZoneInfo("America/Chicago")).date().isoformat()
_default_date_index = 0
if _today_central in date_map:
    _default_date_index = _date_options.index(_today_central)

selected_date = st.selectbox(
    "Select Date",
    _date_options,
    index=_default_date_index,
    help="Defaults to **today (US Central)** when a daily file exists for that date; otherwise the latest available slate.",
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

    try:
        from eng.execution.build_nba_model_pockets import resolve_nba_pocket_board_for_selected_slate

        _lb_sf, _rpo_resolved, _bpp_resolved, _pocket_board_mode = (
            resolve_nba_pocket_board_for_selected_slate(
                selected_date=str(selected_date),
                daily_games=list(games or []),
                model_pockets_doc=_nba_pockets_doc,
                current_game_pocket_doc=_nba_current_pockets_doc,
                leaderboard_disk=_nba_live_pocket_leaderboard_doc,
                ranked_disk=_nba_ranked_pocket_doc,
                bpp_disk=_nba_best_pocket_doc,
            )
        )
    except Exception:
        _lb_sf = _nba_live_pocket_leaderboard_doc
        _rpo_resolved = _nba_ranked_pocket_doc
        _bpp_resolved = _nba_best_pocket_doc
        _pocket_board_mode = "fallback_disk"
        if _lb_sf:
            try:
                from eng.execution.build_nba_model_pockets import (
                    build_nba_best_pocket_per_game_from_leaderboard,
                    build_nba_ranked_pocket_opportunities,
                )

                _pockets_list_fb = list(((_nba_pockets_doc or {}).get("pockets") or []))
                if _rpo_resolved is None and _pockets_list_fb:
                    _rpo_resolved = build_nba_ranked_pocket_opportunities(_lb_sf, _pockets_list_fb)
                if _bpp_resolved is None:
                    _bpp_resolved = build_nba_best_pocket_per_game_from_leaderboard(_lb_sf)
            except Exception:
                pass
    _opp_rows = [r for r in ((_rpo_resolved or {}).get("opportunities") or []) if isinstance(r, dict)]
    _games_bpp = list((_bpp_resolved or {}).get("games") or [])
    _parlay_eligible_n = sum(1 for r in _opp_rows if r.get("eligible_for_parlay"))
    _pocket_join_games, _pocket_join_mode = _resolve_pocket_recommended_bet_daily_games(
        games, selected_date, _lb_sf
    )
    _pocket_daily_by_id = _pocket_index_daily_games(_pocket_join_games)
    _lb_slate = str((_lb_sf or {}).get("slate_date") or "").strip()
    _sel_date = str(selected_date).strip()
    if _pocket_board_mode == "fallback_disk" and _lb_sf:
        st.warning(
            f"**Select Date** `{_sel_date}` — **Pocket ROI fallback**: showing the latest **on-disk** pocket board "
            f"(leaderboard slate **`{_lb_slate or '?'}**`), not a slate rebuilt for this date. "
            f"Typical cause: no games on this daily slate overlap **`nba_current_game_pocket_view`**, or pocket inputs are missing. "
            f"**Recommended Bet** still joins daily lines to that on-disk slate when possible."
        )
    elif _pocket_board_mode == "session_rebuild":
        st.caption(
            f"Pocket ROI **aligned to Select Date** `{_sel_date}` (leaderboard, ranked opportunities, and best-pocket-per-game "
            f"rebuilt in-session from current pocket view + this daily slate)."
        )
    elif _lb_sf and _lb_slate and _lb_slate != _sel_date and _pocket_join_mode == "leaderboard_slate":
        st.warning(
            f"**Recommended Bet** uses the daily file for leaderboard slate **`{_lb_slate}`** (≠ **Select Date** `{_sel_date}`)."
        )
    elif _lb_sf and _lb_slate and _lb_slate != _sel_date and _pocket_join_mode == "mismatch_no_file":
        st.warning(
            f"Leaderboard slate **`{_lb_slate}`** ≠ **Select Date** `{_sel_date}`**, and no daily JSON for **`{_lb_slate}`** "
            f"is in the date list — **Recommended Bet** line detail may be incomplete."
        )

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

    with st.expander("How to read Pocket ROI View", expanded=False):
        st.markdown(
            "**Two layers, one decision.** The historical layer (**Pocket State / State Signature**) is the "
            "season-long hot / warm / cold context for a pocket. The decision layer (**Trust Rating**) comes from "
            "the robustness analysis, which stress-tests each pocket against a recent window, an out-of-sample "
            "second-half hold-out, and the postseason.\n\n"
            "**When they disagree, trust the Trust Rating, not the season-long state** — a pocket can look hot "
            "all season yet still be a backtest artifact that fails out-of-sample.\n\n"
            "- **KEEP** — serious candidate; held up out-of-sample and in the postseason.\n"
            "- **WATCH** — monitor; mixed evidence, not confirmed out-of-sample.\n"
            "- **FADE** — looked good historically but weakened recently or failed the hold-out / postseason checks.\n"
            "- **KILL** — ignore / remove from decision-making (negative full-season or failed the hold-out).\n\n"
            "FADE and KILL rows are hidden by default — use **Show FADE / KILL pockets** to reveal them. "
            "Single-model rows join the robustness table exactly on (model, market, edge bucket); a rating tagged "
            "**(approx)** fell back to a conservative (model, market) match."
        )
        st.markdown(
            "| Column | Meaning |\n"
            "|---|---|\n"
            "| Recommended Bet | The actual side/line to consider for this game (joined to the daily slate). |\n"
            "| Pocket Type | Pocket shape: `single_model`, or a combo (`pair_spread`, `triple_total`, …). |\n"
            "| Pocket Models | Model (single) or the models in the combo (`models_key`). |\n"
            "| State Signature | Historical per-model hot/warm/cold context for the combo (season-long). |\n"
            "| ROI | Historical season-long return per 1u at -110 (WIN +0.909u, LOSS -1u, PUSH 0u). |\n"
            "| Win Rate | Historical wins ÷ graded (pushes in the denominator). |\n"
            "| Graded Games | Historical sample size behind ROI / Win Rate. |\n"
            "| Trust Rating | **Decision layer**: KEEP / WATCH / FADE / KILL from robustness analysis. |\n"
            "| Trust Score | 0–100 composite of out-of-sample, postseason, recent, and sample strength. |\n"
            "| 2nd-Half ROI | ROI on the out-of-sample second half of the season (hold-out test). |\n"
            "| Recent ROI | ROI over the most recent window of graded legs (decay check; singles only). |\n"
            "| Postseason ROI | ROI in play-in + playoffs games. |\n"
            "| Robustness Warning | Decay / instability flags (e.g. first-half-hot then second-half-negative). |\n"
            "| Recommendation | Plain-language action implied by the Trust Rating. |\n"
            "| Parlay Eligible | Whether the row qualifies for the spread-only 2-leg parlay builder. |\n"
        )
        st.caption("Explanatory only — does not change ROI, ranking, filters, or any artifact.")

    st.markdown("## Ranked Pocket Opportunities")
    st.caption(
        "One row per pocket candidate; table is aligned to **Select Date** when pocket data allows "
        "(in-session rebuild from **`nba_current_game_pocket_view`** + this daily slate), else on-disk JSON when it already matches, "
        "else **fallback** to the latest leaderboard (see warning). "
        "Global sort: ROI → graded games → win rate. **Rank** is the global rank in the resolved board. Read-only."
    )

    _has_robustness = bool(_nba_robustness_lk["singles"] or _nba_robustness_lk["combos"])
    if _nba_robustness_doc is not None and _has_robustness:
        _rb_bt = str((_nba_robustness_doc or {}).get("source_backtest_dir") or "").strip()
        _cur_bt = str(
            (_rpo_resolved or {}).get("source_backtest_dir")
            or (_nba_pockets_doc or {}).get("source_backtest_dir")
            or ""
        ).strip()
        _rb_src = (_nba_robustness_doc or {}).get("source")
        if _rb_bt and _cur_bt and _rb_bt != _cur_bt:
            st.warning(
                f"**Pocket trust ratings may be stale:** robustness was computed on backtest "
                f"`{_rb_bt}`, but the displayed pockets are from `{_cur_bt}`. "
                f"Re-run `python tools/analysis/analyze_nba_pocket_robustness.py --emit-latest` to refresh."
            )
        else:
            st.caption(
                f"Trust layer joined from robustness artifact "
                f"({'stable latest' if _rb_src == 'stable' else 'analysis fallback'}; backtest `{_rb_bt or '?'}`). "
                f"**Trust Rating** is the decision layer; season-long state remains as historical context."
            )
    else:
        st.caption(
            "Robustness trust layer not loaded — run "
            "`python tools/analysis/analyze_nba_pocket_robustness.py --emit-latest` to add "
            "KEEP/WATCH/FADE/KILL trust columns. Showing season-long pocket view only."
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

        _RATING_ORDER = {"KEEP": 0, "WATCH": 1, "FADE": 2, "KILL": 3, None: 4}
        _trust_by_rowid: dict[int, dict] = {}
        if _has_robustness:
            for _r in _opp_display:
                _hit, _approx = _robustness_for_row(_r, _nba_robustness_lk)
                _trust_by_rowid[id(_r)] = {"hit": _hit, "approx": _approx}

            def _rating_of(row: dict):
                return (_trust_by_rowid.get(id(row), {}).get("hit") or {}).get("rating")

            _show_fade_kill = st.checkbox(
                "Show FADE / KILL pockets", value=False, key="nba_show_fade_kill",
                help="By default only KEEP/WATCH (and unrated) pockets are shown.",
            )
            _hidden_count = 0
            if not _show_fade_kill:
                _before = len(_opp_display)
                _opp_display = [r for r in _opp_display if _rating_of(r) not in ("FADE", "KILL")]
                _hidden_count = _before - len(_opp_display)

            def _trust_sort_key(row: dict):
                _h = _trust_by_rowid.get(id(row), {}).get("hit") or {}
                _ts = _h.get("trust_score")
                _roi = _pocket_float(row.get("roi"))
                _gr = int(row.get("graded_games") or 0)
                return (
                    _RATING_ORDER.get(_h.get("rating"), 4),
                    -(_ts if _ts is not None else -1e18),
                    -(_roi if _roi is not None else -1e18),
                    -_gr,
                )

            _opp_display = sorted(_opp_display, key=_trust_sort_key)
            if _hidden_count:
                st.caption(
                    f"**{_hidden_count}** FADE/KILL pocket row(s) hidden by default — "
                    f"toggle **Show FADE / KILL pockets** to view."
                )

        def _trust_cells(row: dict) -> dict:
            info = _trust_by_rowid.get(id(row)) or {}
            h = info.get("hit")
            if not h:
                return {
                    "Trust Rating": "—", "Trust Score": "—", "2nd-Half ROI": "—",
                    "Recent ROI": "—", "Postseason ROI": "—", "Robustness Warning": "—",
                    "Recommendation": "—",
                }
            ts = h.get("trust_score")
            approx = " (approx)" if info.get("approx") else ""
            return {
                "Trust Rating": f"{h.get('rating') or '—'}{approx}",
                "Trust Score": (f"{float(ts):.0f}" if ts is not None else "—"),
                "2nd-Half ROI": _rpo_num(h.get("second_half_roi")),
                "Recent ROI": _rpo_num(h.get("recent_roi")),
                "Postseason ROI": _rpo_num(h.get("postseason_roi")),
                "Robustness Warning": (", ".join(h.get("flags") or []) or "—"),
                "Recommendation": (h.get("recommendation") or "—"),
            }

        if not _opp_display:
            st.info(f"No rows match **{_pocket_filter_label}** for this slate.")
        else:
            _st_pocket_main_roi_table(
                [
                    {
                        "Rank": r.get("rank"),
                        "Recommended Bet": format_pocket_recommended_bet(
                            r, _pocket_daily_by_id, join_mode=_pocket_join_mode
                        ),
                        "Pocket Type": _rpo_cell(r.get("pocket_type")),
                        "Pocket Models": _rpo_models_col(r),
                        "State Signature": _rpo_sig_cell(r),
                        "ROI": _rpo_num(r.get("roi")),
                        "Win Rate": _rpo_num(r.get("win_rate")),
                        "Graded Games": r.get("graded_games") if r.get("graded_games") is not None else "—",
                        **(_trust_cells(r) if _has_robustness else {}),
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
                        "Recommended Bet": format_pocket_recommended_bet(
                            g, _pocket_daily_by_id, join_mode=_pocket_join_mode
                        ),
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
            _bet1 = format_pocket_recommended_bet(_r1, _pocket_daily_by_id, join_mode=_pocket_join_mode)
            _bet2 = format_pocket_recommended_bet(_r2, _pocket_daily_by_id, join_mode=_pocket_join_mode)
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
            + ("yes" if _lb_mismatch else "no")
            + "\npocket_board_mode: "
            + str(_pocket_board_mode),
            language=None,
        )
        st.markdown("**Slate resolution (live artifact vs fallback)**")
        st.markdown(_adm_cap)
        if (
            _pocket_board_mode == "fallback_disk"
            and _lb_sf
            and str(_lb_sf.get("slate_date") or "").strip() != str(selected_date).strip()
        ):
            st.warning(
                "On-disk leaderboard `slate_date` ≠ **Select Date** — diagnostic tables reflect that **fallback** board."
            )

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
            if (
                _pocket_board_mode == "fallback_disk"
                and _sf_slate
                and _sf_slate != str(selected_date).strip()
            ):
                st.warning(
                    f"Diagnostic tables use **fallback** leaderboard slate **`{_sf_slate}`** (≠ selected **`{selected_date}`**)."
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

    try:
        from eng.execution.build_ncaam_model_pockets import resolve_ncaam_pocket_board_for_selected_slate

        _lb_sf, _rpo_resolved, _bpp_resolved, _pocket_board_mode = (
            resolve_ncaam_pocket_board_for_selected_slate(
                selected_date=str(selected_date),
                daily_games=list(games or []),
                model_pockets_doc=_ncaam_pockets_doc,
                current_game_pocket_doc=_ncaam_current_pockets_doc,
                leaderboard_disk=_ncaam_live_pocket_leaderboard_doc,
                ranked_disk=_ncaam_ranked_pocket_doc,
                bpp_disk=_ncaam_best_pocket_doc,
            )
        )
    except Exception:
        _lb_sf = _ncaam_live_pocket_leaderboard_doc
        _rpo_resolved = _ncaam_ranked_pocket_doc
        _bpp_resolved = _ncaam_best_pocket_doc
        _pocket_board_mode = "fallback_disk"
        if _lb_sf:
            try:
                from eng.execution.build_ncaam_model_pockets import (
                    build_ncaam_best_pocket_per_game_from_leaderboard,
                    build_ncaam_ranked_pocket_opportunities,
                )

                _pockets_list_fb = list(((_ncaam_pockets_doc or {}).get("pockets") or []))
                if _rpo_resolved is None and _pockets_list_fb:
                    _rpo_resolved = build_ncaam_ranked_pocket_opportunities(_lb_sf, _pockets_list_fb)
                if _bpp_resolved is None:
                    _bpp_resolved = build_ncaam_best_pocket_per_game_from_leaderboard(_lb_sf)
            except Exception:
                pass
    _opp_rows = [r for r in ((_rpo_resolved or {}).get("opportunities") or []) if isinstance(r, dict)]
    _games_bpp = list((_bpp_resolved or {}).get("games") or [])
    _parlay_eligible_n = sum(1 for r in _opp_rows if r.get("eligible_for_parlay"))
    _pocket_join_games, _pocket_join_mode = _resolve_pocket_recommended_bet_daily_games(
        games, selected_date, _lb_sf
    )
    _pocket_daily_by_id = _pocket_index_daily_games(_pocket_join_games)
    _lb_slate = str((_lb_sf or {}).get("slate_date") or "").strip()
    _sel_date = str(selected_date).strip()
    if _pocket_board_mode == "fallback_disk" and _lb_sf:
        st.warning(
            f"**Select Date** `{_sel_date}` — **Pocket ROI fallback**: showing the latest **on-disk** pocket board "
            f"(leaderboard slate **`{_lb_slate or '?'}**`), not a slate rebuilt for this date. "
            f"Typical cause: no games on this daily slate overlap **`ncaam_current_game_pocket_view`**, or pocket inputs are missing. "
            f"**Recommended Bet** still joins daily lines to that on-disk slate when possible."
        )
    elif _pocket_board_mode == "session_rebuild":
        st.caption(
            f"Pocket ROI **aligned to Select Date** `{_sel_date}` (leaderboard, ranked opportunities, and best-pocket-per-game "
            f"rebuilt in-session from current pocket view + this daily slate)."
        )
    elif _lb_sf and _lb_slate and _lb_slate != _sel_date and _pocket_join_mode == "leaderboard_slate":
        st.warning(
            f"**Recommended Bet** uses the daily file for leaderboard slate **`{_lb_slate}`** (≠ **Select Date** `{_sel_date}`)."
        )
    elif _lb_sf and _lb_slate and _lb_slate != _sel_date and _pocket_join_mode == "mismatch_no_file":
        st.warning(
            f"Leaderboard slate **`{_lb_slate}`** ≠ **Select Date** `{_sel_date}`**, and no daily JSON for **`{_lb_slate}`** "
            f"is in the date list — **Recommended Bet** line detail may be incomplete."
        )

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
        "One row per pocket candidate; table is aligned to **Select Date** when pocket data allows "
        "(in-session rebuild from **`ncaam_current_game_pocket_view`** + this daily slate), else on-disk JSON when it already matches, "
        "else **fallback** to the latest leaderboard (see warning). "
        "Global sort: ROI → graded games → win rate. **Rank** is the global rank in the resolved board. Read-only."
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

        if not _opp_display:
            st.info(f"No rows match **{_pocket_filter_label}** for this slate.")
        else:
            _st_pocket_main_roi_table(
                [
                    {
                        "Rank": r.get("rank"),
                        "Recommended Bet": format_pocket_recommended_bet(
                            r, _pocket_daily_by_id, join_mode=_pocket_join_mode
                        ),
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
                        "Recommended Bet": format_pocket_recommended_bet(
                            g, _pocket_daily_by_id, join_mode=_pocket_join_mode
                        ),
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
            _bet1 = format_pocket_recommended_bet(_r1, _pocket_daily_by_id, join_mode=_pocket_join_mode)
            _bet2 = format_pocket_recommended_bet(_r2, _pocket_daily_by_id, join_mode=_pocket_join_mode)
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
            + ("yes" if _lb_mismatch else "no")
            + "\npocket_board_mode: "
            + str(_pocket_board_mode),
            language=None,
        )
        st.markdown("**Slate resolution (live artifact vs fallback)**")
        st.markdown(_adm_cap)
        if (
            _pocket_board_mode == "fallback_disk"
            and _lb_sf
            and str(_lb_sf.get("slate_date") or "").strip() != str(selected_date).strip()
        ):
            st.warning(
                "On-disk leaderboard `slate_date` ≠ **Select Date** — diagnostic tables reflect that **fallback** board."
            )

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
            if (
                _pocket_board_mode == "fallback_disk"
                and _sf_slate
                and _sf_slate != str(selected_date).strip()
            ):
                st.warning(
                    f"Diagnostic tables use **fallback** leaderboard slate **`{_sf_slate}`** (≠ selected **`{selected_date}`**)."
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


def _render_seed_pocket_roi_view(games: list, selected_date: str, league_code: str, league_label: str) -> None:
    """
    Limited-sample Pocket ROI presentation shell.

    This mirrors the NBA/NCAAM Pocket ROI layout, but it intentionally does not
    create mature ROI, confidence, or backtest-derived values before larger
    settled-game pocket artifacts exist.
    """
    seed_root = PROJECT_ROOT / "data" / league_code / "backtests"
    ranked_path = seed_root / f"{league_code}_ranked_pocket_opportunities.json"
    best_path = seed_root / f"{league_code}_best_pocket_per_game.json"
    live_path = seed_root / f"{league_code}_live_pocket_leaderboard.json"
    model_pockets_path = seed_root / f"{league_code}_model_pockets.json"

    def _load_seed(path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    ranked_doc = _load_seed(ranked_path)
    best_doc = _load_seed(best_path)
    live_doc = _load_seed(live_path)
    pockets_doc = _load_seed(model_pockets_path)

    st.markdown(f"Per-game pocket summary from the **{league_label} seed prediction ledger**.")
    if not ranked_doc:
        st.info(
            f"No {league_label} seed Pocket ROI artifacts found yet. Run "
            f"`tools/oneoff/build_{league_code}_pocket_roi_seed.py` after the prediction ledger validates."
        )
    else:
        warning = ranked_doc.get("sample_warning") or f"{league_label} seed artifact; limited sample."
        st.warning(warning)
        overall = (pockets_doc or ranked_doc).get("overall") or {}
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Graded Picks", overall.get("graded_games", 0))
        c2.metric("Seed ROI", overall.get("roi", "n/a"))
        c3.metric("Seed Win Rate", overall.get("win_rate", "n/a"))
        c4.metric("Units", overall.get("units", "n/a"))

    st.markdown("## Ranked Pocket Opportunities")
    all_ranked_rows = (ranked_doc or {}).get("opportunities") or []
    selected_game_ids = {
        str((g.get("identity") or {}).get("game_id") or g.get("game_id") or "").strip()
        for g in games
    }
    selected_game_ids = {gid for gid in selected_game_ids if gid}
    selected_matchups = {
        f"{(g.get('identity') or {}).get('away_team', g.get('away_team', ''))} @ {(g.get('identity') or {}).get('home_team', g.get('home_team', ''))}".strip()
        for g in games
    }
    selected_matchups = {m for m in selected_matchups if m and m != "@"}

    def _matches_selected_slate(row: dict) -> bool:
        row_date = str(row.get("slate_date") or "").strip()
        row_gid = str(row.get("game_id") or "").strip()
        return row_date == selected_date or (row_gid and row_gid in selected_game_ids)

    if league_code in ("wnba", "mlb"):
        ranked_rows = [r for r in all_ranked_rows if _matches_selected_slate(r)]
        if all_ranked_rows and not ranked_rows:
            st.info(
                f"No {league_label} seed Pocket ROI rows match selected date {selected_date}. "
                "The global seed board is available below as a reference, but is not being shown as the selected slate."
            )
    else:
        ranked_rows = all_ranked_rows
    ranked_columns = [
        "Rank",
        "Recommended Bet",
        "Pocket Type",
        "Pocket Models",
        "State Signature",
        "ROI",
        "Win Rate",
        "Graded Games",
        "Trust Rating",
        "Trust Score",
        "Why",
        "Parlay Eligible",
    ]
    if ranked_rows:
        st.dataframe(pd.DataFrame(ranked_rows)[ranked_columns], width="stretch", hide_index=True)
    else:
        st.dataframe(pd.DataFrame(columns=ranked_columns), width="stretch", hide_index=True)
        st.caption(f"No {league_label} seed opportunities available yet.")

    if league_code in ("wnba", "mlb") and all_ranked_rows and ranked_rows != all_ranked_rows:
        with st.expander(f"Global {league_label} seed board (reference only)", expanded=False):
            st.caption(
                "These rows are from the full seed ledger and may not belong to the selected slate date."
            )
            st.dataframe(pd.DataFrame(all_ranked_rows)[ranked_columns], width="stretch", hide_index=True)

    with st.expander("Best pocket per game (secondary summary)", expanded=False):
        all_best_rows = (best_doc or {}).get("games") or []
        if league_code in ("wnba", "mlb"):
            best_rows = [
                r for r in all_best_rows
                if str(r.get("Game") or "").strip() in selected_matchups
                or any(str(r.get("Recommended Bet") or "").startswith(matchup) for matchup in selected_matchups)
            ]
        else:
            best_rows = all_best_rows
        best_columns = [
            "Rank",
            "Game",
            "Recommended Bet",
            "Best Pocket Type",
            "Pocket Models",
            "Pocket ROI",
            "Pocket Win Rate",
            "Pocket Games",
            "Why",
            "Parlay Eligible",
        ]
        if best_rows:
            st.dataframe(pd.DataFrame(best_rows)[best_columns], width="stretch", hide_index=True)
        else:
            st.dataframe(pd.DataFrame(columns=best_columns), width="stretch", hide_index=True)
            st.caption(f"Pending {league_label} best-pocket-per-game seed artifact.")

    st.markdown("## Best 2-leg parlay (positive ROI only)")
    positive_rows = [
        r for r in ranked_rows
        if (r.get("ROI") is not None and r.get("ROI") > 0 and r.get("Parlay Eligible"))
    ]
    if len(positive_rows) >= 2:
        st.dataframe(pd.DataFrame(positive_rows[:2])[ranked_columns], width="stretch", hide_index=True)
        st.caption("Seed-only parlay candidate; sample is too small for production authority.")
    else:
        st.info(f"No {league_label} seed rows currently qualify for a positive-ROI 2-leg parlay.")

    with st.expander(f"{league_label} Pocket ROI readiness", expanded=False):
        st.write(
            {
                "selected_date": selected_date,
                "daily_games_loaded": len(games),
                "expected_backtest_root": str(seed_root.resolve()),
                f"{league_code}_model_pockets.json": "loaded" if pockets_doc else "missing",
                f"{league_code}_ranked_pocket_opportunities.json": "loaded" if ranked_doc else "missing",
                f"{league_code}_best_pocket_per_game.json": "loaded" if best_doc else "missing",
                f"{league_code}_live_pocket_leaderboard.json": "loaded" if live_doc else "missing",
                "live_seed_slate_date": (live_doc or {}).get("slate_date"),
                "sample_warning": (ranked_doc or {}).get("sample_warning"),
            }
        )


def _render_wnba_pocket_roi_view(games: list, selected_date: str) -> None:
    _render_seed_pocket_roi_view(games, selected_date, "wnba", "WNBA")


def _render_mlb_pocket_roi_view(games: list, selected_date: str) -> None:
    _render_seed_pocket_roi_view(games, selected_date, "mlb", "MLB")


# --------------------------------------------------
# AGENT OVERLAY (read-only): load by league, join by game_id
# --------------------------------------------------
def _agent_overlay_path_for_league(league_label: str) -> Path:
    key = (league_label or "").strip().lower()
    name = f"{key}_agent_overlay.json"
    return PROJECT_ROOT / "data" / key / "view" / name


_overlay_path = _agent_overlay_path_for_league(league)
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

if league in ("NBA", "NCAAM", "WNBA", "MLB"):
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
        "**Pocket ROI lens** — ranked board prefers **Select Date** (in-session rebuild from current pocket view + this daily slate "
        "when possible); otherwise on-disk JSON when it already matches; otherwise **fallback** to latest leaderboard (with warning). "
        "**Recommended Bet** uses the same resolved board’s slate. Read-only; **MonkeyDarts_v2** excluded upstream."
    )
    _render_nba_pocket_roi_view(games, selected_date)
    st.stop()

if league == "NCAAM" and slate_dashboard_view == "Pocket ROI View":
    st.caption(
        "**Pocket ROI lens** — NCAAM; ranked board prefers **Select Date** (in-session rebuild when possible), else matching on-disk JSON, "
        "else **fallback** (with warning). **Recommended Bet** follows the same resolved slate. "
        "Read-only. Models: avg score, momentum, market pressure (no injury layer)."
    )
    _render_ncaam_pocket_roi_view(games, selected_date)
    st.stop()

if league == "WNBA" and slate_dashboard_view == "Pocket ROI View":
    st.caption(
        "**Pocket ROI lens** - WNBA; display contract mirrors NBA, using limited-sample seed artifacts "
        "until larger settled-game backtests exist."
    )
    _render_wnba_pocket_roi_view(games, selected_date)
    st.stop()

if league == "MLB" and slate_dashboard_view == "Pocket ROI View":
    st.caption(
        "**Pocket ROI lens** - MLB; display contract mirrors WNBA/NBA, using limited-sample seed artifacts "
        "until larger settled-game backtests exist."
    )
    _render_mlb_pocket_roi_view(games, selected_date)
    st.stop()

if league == "NBA" and slate_dashboard_view == "Standard Slate View":
    st.caption(
        "**NBA pockets:** use **Pocket ROI View** for ranked best-pocket per game and positive-ROI parlay diagnostics."
    )

if league == "NCAAM" and slate_dashboard_view == "Standard Slate View":
    st.caption(
        "**NCAAM pockets:** use **Pocket ROI View** for ranked best-pocket per game and positive-ROI parlay diagnostics."
    )

if league == "WNBA" and slate_dashboard_view == "Standard Slate View":
    st.caption(
        "**WNBA Daily View:** market-value picks compare available lines against cross-book consensus. "
        "Use **Live Odds Slate** for the live bookmaker table; Pocket ROI requires WNBA settled "
        "backtests before any ROI-ranked picks can appear."
    )

if league == "MLB" and slate_dashboard_view == "Standard Slate View":
    st.caption(
        "**MLB Daily View:** market-value picks compare available moneyline, run-line, and total lines "
        "against cross-book consensus. Use **Live Odds Slate** for the live bookmaker table."
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
