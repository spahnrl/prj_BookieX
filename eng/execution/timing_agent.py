"""
eng/execution/timing_agent.py

Betting strategy: Timing Agent compares current_line in final_game_view against
odds_history. If the line is moving away from the model's projection (value
increasing), returns STATUS: EXECUTE. If the line is moving toward the
projection (value evaporating), returns STATUS: HOLD/WAIT.

- current_line: spread_home, total (or market_spread_home, market_total).
- odds_history: list of {market_spread_home, market_total, captured_at_utc} or
  {spread_home_last, total_last, ...} from f_gen_041 / game state.
- Model projection: Home Line Projection, Total Projection; Line Bet (HOME/AWAY or team), Total Bet (OVER/UNDER).

Authority: eng/backtest_gen_runner.py, final_game_view schema.
"""

from __future__ import annotations


def _safe_float(x) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _current_spread(game: dict) -> float | None:
    return _safe_float(
        game.get("spread_home")
        or game.get("market_spread_home")
        or game.get("spread_home_last")
    )


def _current_total(game: dict) -> float | None:
    return _safe_float(
        game.get("total")
        or game.get("market_total")
        or game.get("total_last")
    )


def _history_spread(snapshot: dict) -> float | None:
    return _safe_float(
        snapshot.get("market_spread_home")
        or snapshot.get("spread_home_last")
        or snapshot.get("spread_home")
    )


def _history_total(snapshot: dict) -> float | None:
    return _safe_float(
        snapshot.get("market_total")
        or snapshot.get("total_last")
        or snapshot.get("total")
    )


def _is_bet_on_home(game: dict) -> bool | None:
    """True if spread pick is home side, False if away, None if unknown."""
    line_bet = (game.get("Line Bet") or game.get("spread_pick") or "").strip().upper()
    if line_bet in ("HOME", "AWAY"):
        return line_bet == "HOME"
    home_team = (game.get("home_team") or game.get("home_team_display") or "").strip().upper()
    if not home_team:
        return None
    return line_bet == home_team


def timing_recommendation(game: dict) -> dict:
    """
    Compare current line vs odds_history. Return status and reason.

    Returns:
        {
            "status": "EXECUTE" | "HOLD/WAIT" | "UNKNOWN",
            "reason": str,
            "spread_value_direction": "better" | "worse" | None,
            "total_value_direction": "better" | "worse" | None,
        }
    - EXECUTE: line moved in our favor (value increasing).
    - HOLD/WAIT: line moved against us (value evaporating).
    - UNKNOWN: no odds_history or insufficient data.
    """
    history = game.get("odds_history") or []
    if len(history) < 2:
        return {
            "status": "UNKNOWN",
            "reason": "Insufficient odds history (need at least 2 snapshots)",
            "spread_value_direction": None,
            "total_value_direction": None,
        }

    current_s = _current_spread(game)
    current_t = _current_total(game)
    prev = history[-2]
    prev_s = _history_spread(prev)
    prev_t = _history_total(prev)

    status = "UNKNOWN"
    reasons = []
    spread_dir = None
    total_dir = None

    # Spread: we bet home -> we want home to get more points (less negative spread).
    # So "value" for home pick = -spread_home (higher = better). For away pick, value = +spread_home.
    bet_home = _is_bet_on_home(game)
    if bet_home is not None and current_s is not None and prev_s is not None:
        if bet_home:
            # Home pick: value = -spread_home. Current > previous (e.g. -3 vs -5) -> value up
            if -current_s > -prev_s:
                spread_dir = "better"
            elif -current_s < -prev_s:
                spread_dir = "worse"
        else:
            # Away pick: value = +spread_home. Current < previous (e.g. -5 vs -3) -> away gets more
            if current_s < prev_s:
                spread_dir = "better"
            elif current_s > prev_s:
                spread_dir = "worse"

    # Total: OVER wants lower total (easier to go over), UNDER wants higher total.
    total_bet = (game.get("Total Bet") or game.get("total_pick") or "").strip().upper()
    if total_bet and current_t is not None and prev_t is not None:
        if total_bet == "OVER":
            if current_t < prev_t:
                total_dir = "better"
            elif current_t > prev_t:
                total_dir = "worse"
        elif total_bet == "UNDER":
            if current_t > prev_t:
                total_dir = "better"
            elif current_t < prev_t:
                total_dir = "worse"

    if spread_dir == "better" or total_dir == "better":
        status = "EXECUTE"
        if spread_dir == "better" and total_dir == "better":
            reasons.append("Spread and total both moved in our favor (value increasing).")
        elif spread_dir == "better":
            reasons.append("Spread moved in our favor (value increasing).")
        else:
            reasons.append("Total moved in our favor (value increasing).")
    elif spread_dir == "worse" or total_dir == "worse":
        status = "HOLD/WAIT"
        if spread_dir == "worse" and total_dir == "worse":
            reasons.append("Spread and total moved against us (value evaporating).")
        elif spread_dir == "worse":
            reasons.append("Spread moved against us (value evaporating).")
        else:
            reasons.append("Total moved against us (value evaporating).")

    if status == "UNKNOWN" and (spread_dir is not None or total_dir is not None):
        # Mixed or only one market
        if spread_dir and total_dir:
            status = "EXECUTE" if (spread_dir == "better" or total_dir == "better") else "HOLD/WAIT"
        elif spread_dir:
            status = "EXECUTE" if spread_dir == "better" else "HOLD/WAIT"
        elif total_dir:
            status = "EXECUTE" if total_dir == "better" else "HOLD/WAIT"

    return {
        "status": status,
        "reason": " ".join(reasons) if reasons else "No clear spread/total movement.",
        "spread_value_direction": spread_dir,
        "total_value_direction": total_dir,
    }
