"""
eng/analysis/analysis_041_agent_attribution.py

Audit success of Live Monitor EXECUTE alerts: parse logs/active_alerts.log,
cross-reference with final_game_view_ncaam.json for actual_margin/actual_total,
simulate Flat ($100) vs Kelly bet sizing, compute Yield/ROI%, Success Rate,
Max Drawdown; compare VALUE PEAK REACHED vs standard EXECUTE win rates.
Output: console summary table + logs/attribution_report.json.

Authority: logs/active_alerts.log, data/ncaam/view/final_game_view_ncaam.json,
           utils/risk_management.py, eng/backtest_gen_runner.py (grading).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ALERTS_LOG_PATH = PROJECT_ROOT / "logs" / "active_alerts.log"
FINAL_VIEW_PATH = PROJECT_ROOT / "data" / "ncaam" / "view" / "final_game_view_ncaam.json"
ATTRIBUTION_REPORT_PATH = PROJECT_ROOT / "logs" / "attribution_report.json"

FLAT_BET_AMOUNT = 100.0
PAYOUT_RATIO = 100 / 110  # -110 standard


def _safe_float(x):
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_alert_line(line: str) -> dict | None:
    """
    Parse a line from active_alerts.log. Returns dict with timestamp, matchup, pick_str,
    kelly_pct, kelly_dollars, value_peak_reached, or None if not EXECUTE.
    """
    line = (line or "").strip()
    if "STATUS: EXECUTE" not in line:
        return None
    # [TIMESTAMP] [MATCHUP] - STATUS: EXECUTE - KELLY SIZE: [4.6]% ($458.27). ...
    # or older: [TIMESTAMP] [NCAAM] [MATCHUP] - [...] - STATUS: EXECUTE.
    ts_match = re.match(r"\[([^\]]+)\]\s+", line)
    timestamp = ts_match.group(1) if ts_match else ""
    value_peak = "VALUE PEAK REACHED" in line
    matchup = ""
    for bracket in re.finditer(r"\[([^\]]+)\]", line):
        content = bracket.group(1).strip()
        if " @ " in content and content != "NCAAM":
            matchup = content
            break
    # KELLY SIZE: [4.6]% ($458.27)
    kelly_pct = None
    kelly_dollars = None
    kelly_match = re.search(r"KELLY SIZE:\s*\[([^\]]+)\]%\s*\(\$([^)]+)\)", line)
    if kelly_match:
        kelly_pct = _safe_float(kelly_match.group(1))
        kelly_dollars = _safe_float(kelly_match.group(2).replace(",", ""))
    if kelly_dollars is None:
        kelly_dollars = FLAT_BET_AMOUNT  # legacy alerts without Kelly
    # Pick: [PICK] EDGE: or [PICK] - EDGE:
    pick_match = re.search(r"\]\.\s*\[([^\]]+)\]\s+EDGE:", line) or re.search(r"\]\s+\[([^\]]+)\]\s+EDGE:", line)
    pick_str = pick_match.group(1).strip() if pick_match else ""
    return {
        "timestamp": timestamp,
        "matchup": matchup,
        "pick_str": pick_str,
        "kelly_pct": kelly_pct,
        "kelly_dollars": kelly_dollars,
        "value_peak_reached": value_peak,
    }


def load_alerts() -> list[dict]:
    if not ALERTS_LOG_PATH.exists():
        return []
    out = []
    with open(ALERTS_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            rec = parse_alert_line(line)
            if rec and rec.get("matchup"):
                out.append(rec)
    return out


def load_final_view() -> list[dict]:
    if not FINAL_VIEW_PATH.exists():
        return []
    with open(FINAL_VIEW_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def normalize_team(t: str) -> str:
    return (t or "").strip().upper()


def matchup_key(away: str, home: str) -> str:
    return f"{normalize_team(away)} @ {normalize_team(home)}"


def build_game_index(games: list[dict]) -> dict[str, dict]:
    """Key: matchup "AWAY @ HOME". Value: game dict. If duplicate matchup, keep latest by game_date."""
    index = {}
    for g in games:
        away = g.get("away_team") or g.get("away_team_display") or ""
        home = g.get("home_team") or g.get("home_team_display") or ""
        if not away or not home:
            continue
        key = matchup_key(away, home)
        existing = index.get(key)
        gdate = (g.get("game_date") or "")[:10]
        if existing is None or (gdate and gdate > (existing.get("game_date") or "")[:10]):
            index[key] = g
    return index


def parse_pick_string(pick_str: str, away_team: str, home_team: str) -> tuple[str, str]:
    """Extract Line Bet (spread) and Total Bet from pick string like 'Oregon (spread edge 4.47) | OVER (total edge 20.91)'."""
    line_bet = ""
    total_bet = ""
    away = normalize_team(away_team)
    home = normalize_team(home_team)
    if "|" in pick_str:
        parts = [p.strip() for p in pick_str.split("|")]
        for p in parts:
            if "spread edge" in p.lower():
                # "Oregon (spread edge 4.47)" or "Hofstra (spread edge -1.82)"
                m = re.match(r"([^(]+)\s*\(.*spread", p, re.I)
                if m:
                    line_bet = (m.group(1) or "").strip()
                    if line_bet.upper() == home:
                        line_bet = "HOME"
                    elif line_bet.upper() == away:
                        line_bet = "AWAY"
            elif "total edge" in p.lower():
                m = re.search(r"\b(OVER|UNDER)\b", p, re.I)
                if m:
                    total_bet = m.group(1).upper()
    else:
        if re.search(r"\bOVER\b", pick_str, re.I):
            total_bet = "OVER"
        elif re.search(r"\bUNDER\b", pick_str, re.I):
            total_bet = "UNDER"
        for name in [away_team, home_team]:
            if name and normalize_team(name) in normalize_team(pick_str):
                line_bet = "HOME" if normalize_team(name) == home else "AWAY"
                break
    return line_bet, total_bet


def grade_spread_pick(spread_pick: str, home_team: str, away_team: str, market_spread_home: float | None, home_score: float, away_score: float) -> str:
    if not spread_pick or market_spread_home is None or home_score is None or away_score is None:
        return ""
    adjusted_home = home_score + market_spread_home
    if adjusted_home > away_score:
        ats_winner = "HOME"
        ats_winner_name = home_team
    elif adjusted_home < away_score:
        ats_winner = "AWAY"
        ats_winner_name = away_team
    else:
        return "PUSH"
    pick_upper = (spread_pick or "").strip().upper()
    if pick_upper in ("HOME", "AWAY"):
        return "WIN" if pick_upper == ats_winner else "LOSS"
    return "WIN" if (ats_winner_name and pick_upper == normalize_team(ats_winner_name)) else "LOSS"


def grade_total_pick(total_pick: str, market_total: float | None, home_score: float, away_score: float) -> str:
    if not total_pick or market_total is None or home_score is None or away_score is None:
        return ""
    actual_total = home_score + away_score
    if actual_total > market_total:
        side = "OVER"
    elif actual_total < market_total:
        side = "UNDER"
    else:
        return "PUSH"
    return "WIN" if (total_pick or "").strip().upper() == side else "LOSS"


def grade_alert_result(alert: dict, game: dict) -> tuple[str, str, str]:
    """
    Grade spread and total from alert pick string vs game actuals.
    Returns (spread_result, total_result, combined).
    combined = WIN if both WIN (parlay), LOSS if either LOSS, PUSH if either PUSH.
    """
    home_score = _safe_float(game.get("home_score"))
    away_score = _safe_float(game.get("away_score"))
    market_spread = _safe_float(game.get("spread_home") or game.get("market_spread_home"))
    market_total = _safe_float(game.get("total") or game.get("market_total"))
    home_team = (game.get("home_team") or game.get("home_team_display") or "").strip()
    away_team = (game.get("away_team") or game.get("away_team_display") or "").strip()

    line_bet, total_bet = parse_pick_string(alert.get("pick_str") or "", away_team, home_team)
    spread_result = grade_spread_pick(line_bet, home_team, away_team, market_spread, home_score or 0, away_score or 0) if line_bet else ""
    total_result = grade_total_pick(total_bet, market_total, home_score or 0, away_score or 0) if total_bet else ""

    if not spread_result and not total_result:
        return "", "", "UNKNOWN"
    if spread_result and total_result:
        if spread_result == "PUSH" or total_result == "PUSH":
            combined = "PUSH"
        else:
            combined = "WIN" if (spread_result == "WIN" and total_result == "WIN") else "LOSS"
    else:
        combined = spread_result or total_result
    return spread_result, total_result, combined


def profit_loss(result: str, stake: float, payout_ratio: float = PAYOUT_RATIO) -> float:
    if result == "WIN":
        return stake * payout_ratio
    if result == "LOSS":
        return -stake
    return 0.0  # PUSH


def run_attribution() -> dict:
    alerts = load_alerts()
    games = load_final_view()
    game_index = build_game_index(games)

    flat_pl = []
    kelly_pl = []
    flat_stakes = []
    kelly_stakes = []
    results = []  # list of { alert, game, combined_result, value_peak, flat_pnl, kelly_pnl }
    value_peak_results = []
    standard_results = []

    for alert in alerts:
        matchup = (alert.get("matchup") or "").strip()
        if not matchup:
            continue
        # Normalize matchup to key (e.g. "OREGON @ GONZAGA")
        parts = [p.strip() for p in matchup.split("@")]
        if len(parts) != 2:
            continue
        key = matchup_key(parts[0], parts[1])
        game = game_index.get(key)
        if not game:
            continue
        spread_res, total_res, combined = grade_alert_result(alert, game)
        if combined == "UNKNOWN":
            continue

        stake_flat = FLAT_BET_AMOUNT
        stake_kelly = alert.get("kelly_dollars") or FLAT_BET_AMOUNT
        pnl_flat = profit_loss(combined, stake_flat)
        pnl_kelly = profit_loss(combined, stake_kelly)

        flat_pl.append(pnl_flat)
        kelly_pl.append(pnl_kelly)
        flat_stakes.append(stake_flat)
        kelly_stakes.append(stake_kelly)
        results.append({
            "matchup": matchup,
            "timestamp": alert.get("timestamp"),
            "combined_result": combined,
            "value_peak_reached": alert.get("value_peak_reached", False),
            "flat_stake": stake_flat,
            "kelly_stake": stake_kelly,
            "flat_pnl": pnl_flat,
            "kelly_pnl": pnl_kelly,
        })
        if alert.get("value_peak_reached"):
            value_peak_results.append(combined)
        else:
            standard_results.append(combined)

    # Metrics
    n = len(flat_pl)
    total_flat_wagered = sum(flat_stakes)
    total_kelly_wagered = sum(kelly_stakes)
    total_flat_pnl = sum(flat_pl)
    total_kelly_pnl = sum(kelly_pl)

    roi_flat = (total_flat_pnl / total_flat_wagered * 100) if total_flat_wagered else 0
    roi_kelly = (total_kelly_pnl / total_kelly_wagered * 100) if total_kelly_wagered else 0

    wins = sum(1 for r in results if r["combined_result"] == "WIN")
    losses = sum(1 for r in results if r["combined_result"] == "LOSS")
    pushes = sum(1 for r in results if r["combined_result"] == "PUSH")
    settled = wins + losses
    success_rate = (wins / settled * 100) if settled else 0

    # Max drawdown (running P&L)
    def max_drawdown(pnl_list: list[float]) -> float:
        peak = 0.0
        dd = 0.0
        run = 0.0
        for x in pnl_list:
            run += x
            peak = max(peak, run)
            dd = max(dd, peak - run)
        return dd

    dd_flat = max_drawdown(flat_pl)
    dd_kelly = max_drawdown(kelly_pl)

    # VALUE PEAK vs standard win rate
    vp_wins = sum(1 for r in value_peak_results if r == "WIN")
    vp_settled = sum(1 for r in value_peak_results if r in ("WIN", "LOSS"))
    std_wins = sum(1 for r in standard_results if r == "WIN")
    std_settled = sum(1 for r in standard_results if r in ("WIN", "LOSS"))
    vp_win_rate = (vp_wins / vp_settled * 100) if vp_settled else None
    std_win_rate = (std_wins / std_settled * 100) if std_settled else None

    report = {
        "summary": {
            "total_execute_alerts": len(alerts),
            "matched_to_final_view": n,
            "unmatched": len(alerts) - n,
        },
        "strategy_a_flat": {
            "stake_per_bet": FLAT_BET_AMOUNT,
            "total_wagered": total_flat_wagered,
            "total_pnl": round(total_flat_pnl, 2),
            "yield_roi_pct": round(roi_flat, 2),
            "success_rate_pct": round(success_rate, 2),
            "max_drawdown": round(dd_flat, 2),
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
        },
        "strategy_b_kelly": {
            "total_wagered": round(total_kelly_wagered, 2),
            "total_pnl": round(total_kelly_pnl, 2),
            "yield_roi_pct": round(roi_kelly, 2),
            "success_rate_pct": round(success_rate, 2),
            "max_drawdown": round(dd_kelly, 2),
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
        },
        "value_peak_vs_standard": {
            "value_peak_win_rate_pct": round(vp_win_rate, 2) if vp_win_rate is not None else None,
            "value_peak_n": vp_settled,
            "standard_win_rate_pct": round(std_win_rate, 2) if std_win_rate is not None else None,
            "standard_n": std_settled,
        },
        "detail": results,
    }
    return report


def print_summary_table(report: dict) -> None:
    s = report.get("summary", {})
    a = report.get("strategy_a_flat", {})
    b = report.get("strategy_b_kelly", {})
    v = report.get("value_peak_vs_standard", {})

    print("\n" + "=" * 70)
    print("AGENT ATTRIBUTION REPORT (Live Monitor EXECUTE Alerts)")
    print("=" * 70)
    print(f"  Total EXECUTE alerts parsed: {s.get('total_execute_alerts', 0)}")
    print(f"  Matched to final_game_view:  {s.get('matched_to_final_view', 0)}")
    print(f"  Unmatched:                   {s.get('unmatched', 0)}")
    print()
    print("  Strategy A (Flat $100)  |  Strategy B (Kelly)")
    print("  ------------------------+------------------------")
    print(f"  Total wagered: ${a.get('total_wagered', 0):,.2f}  |  ${b.get('total_wagered', 0):,.2f}")
    print(f"  Total P&L:     ${a.get('total_pnl', 0):+,.2f}  |  ${b.get('total_pnl', 0):+,.2f}")
    print(f"  Yield (ROI%):  {a.get('yield_roi_pct', 0):+.2f}%  |  {b.get('yield_roi_pct', 0):+.2f}%")
    print(f"  Success rate:  {a.get('success_rate_pct', 0):.2f}%  |  {b.get('success_rate_pct', 0):.2f}%")
    print(f"  Max drawdown:  ${a.get('max_drawdown', 0):,.2f}  |  ${b.get('max_drawdown', 0):,.2f}")
    print()
    print("  VALUE PEAK REACHED vs standard EXECUTE:")
    vp_wr = v.get("value_peak_win_rate_pct")
    std_wr = v.get("standard_win_rate_pct")
    print(f"    Value Peak win rate: {vp_wr if vp_wr is not None else 'n/a'}% (n={v.get('value_peak_n', 0)})")
    print(f"    Standard win rate:   {std_wr if std_wr is not None else 'n/a'}% (n={v.get('standard_n', 0)})")
    print("=" * 70 + "\n")


def main() -> None:
    report = run_attribution()
    print_summary_table(report)
    ATTRIBUTION_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ATTRIBUTION_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"Report saved: {ATTRIBUTION_REPORT_PATH}")


if __name__ == "__main__":
    main()
