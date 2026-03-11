"""
eng/execution/live_monitor_agent.py

Watch for actionable Timing Agent transitions. Runs on a loop (e.g. every 30 minutes)
or can be triggered via cron.

- Loads data/ncaam/view/final_game_view_ncaam_active.json.
- Filter: max(|Spread Edge|, |Total Edge|) > 10.0 and game is in a Sweet Spot with 60%+ Win Rate.
- Uses eng/execution/timing_agent.timing_recommendation() on odds_history.
- Generates alert ONLY when status is EXECUTE.
- Writes logs/active_alerts.log: [TIMESTAMP] [LEAGUE] [MATCHUP] - [PICK] - EDGE: [X] - REASON: [SWEET SPOT TEXT] - STATUS: EXECUTE.
- Optional: "VALUE PEAK REACHED" when a pick moves from HOLD/WAIT to EXECUTE.

Authority: eng/execution/timing_agent.py, data/ncaam/view/final_game_view_ncaam_active.json,
           eng/outputs/analysis/bias_report_ncaam.json.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Paths
BIAS_REPORT_PATH = PROJECT_ROOT / "data" / "ncaam" / "reports" / "bias_report_ncaam.json"
BANKROLL_CONFIG_PATH = PROJECT_ROOT / "configs" / "runtime" / "bankroll.json"
ACTIVE_VIEW_PATH = PROJECT_ROOT / "data" / "ncaam" / "view" / "final_game_view_ncaam_active.json"
ALERTS_LOG_PATH = PROJECT_ROOT / "logs" / "active_alerts.log"
MONITOR_STATE_PATH = PROJECT_ROOT / "logs" / "monitor_state.json"

EDGE_MIN = 10.0
SWEET_SPOT_WIN_RATE_MIN = 0.60  # 60%+ for "in Sweet Spots"
DEFAULT_INTERVAL_MINUTES = 30
DEFAULT_MARKET_ODDS_AMERICAN = -110  # standard spread/total
KELLY_FRACTION = 0.25  # Quarter-Kelly


def _safe_float(x) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_bias_report() -> dict | None:
    if not BIAS_REPORT_PATH.exists():
        return None
    try:
        with open(BIAS_REPORT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def sweet_spots_60_plus(report: dict) -> list[str]:
    """Scenario names (e.g. spread_edge_25.0_inf) with win_rate >= 60%."""
    if not report:
        return []
    spots = report.get("sweet_spots") or []
    return [
        (s.get("scenario") or "").strip()
        for s in spots
        if s and (s.get("win_rate") or 0) >= SWEET_SPOT_WIN_RATE_MIN
    ]


def sweet_spot_scenario_to_win_rate(report: dict) -> dict[str, float]:
    """Map scenario name -> win_rate for all sweet spots (for Kelly p)."""
    if not report:
        return {}
    spots = report.get("sweet_spots") or []
    return {
        (s.get("scenario") or "").strip(): float(s.get("win_rate") or 0)
        for s in spots
        if s and (s.get("scenario") or "").strip()
    }


def game_sweet_spot_win_rate(game: dict, scenario_to_wr: dict[str, float], scenario_names_60: list[str]) -> float | None:
    """Win rate p from bias_report for this game's Sweet Spot (60%+). Returns None if no match."""
    reason = (game.get("agent_reasoning") or "").strip()
    if not reason or not scenario_to_wr:
        return None
    for scenario in scenario_names_60:
        if scenario in reason:
            return scenario_to_wr.get(scenario)
    return None


def load_bankroll() -> float:
    """Load Total Bankroll from configs/runtime/bankroll.json. Returns 0.0 if missing/invalid."""
    if not BANKROLL_CONFIG_PATH.exists():
        return 0.0
    try:
        with open(BANKROLL_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return 0.0
        total = data.get("total_bankroll")
        if total is None:
            return 0.0
        return max(0.0, float(total))
    except Exception:
        return 0.0


def game_in_60_plus_sweet_spot(game: dict, scenario_names: list[str]) -> bool:
    """True if agent_reasoning references one of the 60%+ scenario names."""
    if not scenario_names:
        return False
    reason = (game.get("agent_reasoning") or "").strip()
    if not reason:
        return False
    return any(scenario in reason for scenario in scenario_names)


def load_active_view() -> list[dict]:
    if not ACTIVE_VIEW_PATH.exists():
        return []
    try:
        with open(ACTIVE_VIEW_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def load_game_state_ncaam() -> dict[str, dict]:
    """Load NCAAM game state by game_id / canonical_game_id for odds_history."""
    try:
        from utils.io_helpers import get_game_state_path
        path = get_game_state_path("ncaam")
    except Exception:
        return {}
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, list):
        return {}
    by_id = {}
    for g in data:
        if not isinstance(g, dict):
            continue
        gid = (g.get("canonical_game_id") or g.get("game_id") or "").strip()
        if gid:
            by_id[gid] = g
    return by_id


def merge_odds_history_into_games(active_games: list[dict], state_by_id: dict[str, dict]) -> list[dict]:
    """Attach odds_history from game state to each active game (by game_id)."""
    out = []
    for g in active_games:
        row = dict(g)
        gid = (g.get("game_id") or g.get("canonical_game_id") or "").strip()
        state = state_by_id.get(gid) if gid else None
        if state and (state.get("odds_history") or []):
            row["odds_history"] = list(state.get("odds_history") or [])
        else:
            row["odds_history"] = row.get("odds_history") or []
        out.append(row)
    return out


def pick_summary(game: dict) -> str:
    """Single-line pick: Line Bet and/or Total Bet with edges."""
    line = (game.get("Line Bet") or "").strip()
    total = (game.get("Total Bet") or "").strip()
    se = _safe_float(game.get("Spread Edge"))
    te = _safe_float(game.get("Total Edge"))
    parts = []
    if line and se is not None:
        parts.append(f"{line} (spread edge {se})")
    if total and te is not None:
        parts.append(f"{total} (total edge {te})")
    return " | ".join(parts) if parts else (line or total or "—")


def matchup_string(game: dict) -> str:
    away = (game.get("away_team") or game.get("away_team_display") or "").strip()
    home = (game.get("home_team") or game.get("home_team_display") or "").strip()
    return f"{away} @ {home}"


def load_monitor_state() -> dict[str, str]:
    """Previous run status per game_id: EXECUTE | HOLD/WAIT | UNKNOWN."""
    if not MONITOR_STATE_PATH.exists():
        return {}
    try:
        with open(MONITOR_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_monitor_state(state: dict[str, str]) -> None:
    MONITOR_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MONITOR_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def run_one_cycle() -> int:
    """
    Load active view, filter by edge > 10 and 60%+ Sweet Spot, run timing_agent;
    write alerts only for EXECUTE. Returns number of alerts written.
    """
    from eng.execution.timing_agent import timing_recommendation

    report = load_bias_report()
    scenario_names_60 = sweet_spots_60_plus(report) if report else []
    scenario_to_wr = sweet_spot_scenario_to_win_rate(report) if report else {}
    bankroll = load_bankroll()
    active = load_active_view()
    if not active:
        return 0

    state_by_id = load_game_state_ncaam()
    games = merge_odds_history_into_games(active, state_by_id)

    candidates = []
    for g in games:
        se = _safe_float(g.get("Spread Edge"))
        te = _safe_float(g.get("Total Edge"))
        best = max((abs(x) for x in (se, te) if x is not None), default=0)
        if best <= EDGE_MIN:
            continue
        if not game_in_60_plus_sweet_spot(g, scenario_names_60):
            continue
        candidates.append(g)

    previous_state = load_monitor_state()
    new_state = dict(previous_state)
    alerts = []
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    for game in candidates:
        rec = timing_recommendation(game)
        status = (rec.get("status") or "").strip()
        gid = (game.get("game_id") or game.get("canonical_game_id") or "").strip()
        new_state[gid] = status

        if status != "EXECUTE":
            continue

        reason = (game.get("agent_reasoning") or "").strip()
        if not reason:
            reason = "(Sweet Spot)"
        reason_flat = reason.replace("\n", " ").strip()
        if len(reason_flat) > 200:
            reason_flat = reason_flat[:197] + "..."

        matchup = matchup_string(game)
        pick = pick_summary(game)
        se = _safe_float(game.get("Spread Edge"))
        te = _safe_float(game.get("Total Edge"))
        edge_str = f"spread={se}|total={te}" if se is not None and te is not None else str(se or te or "")

        prev = previous_state.get(gid, "")
        value_peak = " VALUE PEAK REACHED" if prev in ("HOLD/WAIT", "HOLD") else ""

        # Kelly: p from bias_report Sweet Spot win_rate; default -110
        win_rate_p = game_sweet_spot_win_rate(game, scenario_to_wr, scenario_names_60)
        market_odds = _safe_float(
            game.get("market_odds_american") or game.get("odds_american")
        ) or DEFAULT_MARKET_ODDS_AMERICAN
        from utils.risk_management import calculate_kelly_bet
        kelly_frac, kelly_amount = calculate_kelly_bet(
            win_probability=win_rate_p if win_rate_p is not None else 0.55,
            market_odds=market_odds,
            bankroll=bankroll,
            kelly_fraction=KELLY_FRACTION,
        )
        kelly_pct = f"{kelly_frac * 100:.1f}" if kelly_frac is not None else "0"
        kelly_dollars = f"${kelly_amount:.2f}" if kelly_amount is not None else "$0.00"

        line = f"[{ts}] [{matchup}] - STATUS: EXECUTE - KELLY SIZE: [{kelly_pct}]% ({kelly_dollars}). [{pick}] EDGE: [{edge_str}] REASON: [{reason_flat}].{value_peak}"
        alerts.append(line)

    save_monitor_state(new_state)

    if not alerts:
        return 0

    ALERTS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERTS_LOG_PATH, "a", encoding="utf-8") as f:
        for line in alerts:
            f.write(line + "\n")
    return len(alerts)


def run_loop(interval_minutes: int = DEFAULT_INTERVAL_MINUTES) -> None:
    """Run monitor every interval_minutes until KeyboardInterrupt."""
    import time
    print(f"Live monitor started (interval={interval_minutes} min). Ctrl+C to stop.")
    while True:
        try:
            n = run_one_cycle()
            if n > 0:
                print(f"[{datetime.now(timezone.utc).isoformat()}] Alerts written: {n}")
        except Exception as e:
            print(f"Monitor cycle error: {e}")
        time.sleep(interval_minutes * 60)


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Live monitor: Timing Agent EXECUTE alerts for NCAAM Sweet Spots")
    p.add_argument("--once", action="store_true", help="Run one cycle and exit (for cron)")
    p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_MINUTES, help="Loop interval in minutes")
    args = p.parse_args()
    if args.once:
        n = run_one_cycle()
        print(f"Alerts written: {n}")
        return
    run_loop(interval_minutes=args.interval)


if __name__ == "__main__":
    main()
