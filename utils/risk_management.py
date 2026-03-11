"""
utils/risk_management.py

Kelly Criterion bet-sizing. Quarter-Kelly (0.25 * f*) default to manage volatility.

- calculate_kelly_bet(win_probability, market_odds, bankroll, kelly_fraction=0.25)
- market_odds: American style (e.g. -110). Converted to decimal for f*.
- Returns recommended fraction of bankroll and dollar amount.

Authority: eng/execution/live_monitor_agent.py, configs/runtime/bankroll.json.
"""

from __future__ import annotations


def american_to_decimal(american_odds: float) -> float:
    """Convert American odds to decimal. -110 -> ~1.909; +150 -> 2.50."""
    if american_odds is None:
        return 1.909  # default -110
    try:
        a = float(american_odds)
    except (TypeError, ValueError):
        return 1.909
    if a >= 100:
        return 1.0 + a / 100.0
    if a <= -100:
        return 1.0 + 100.0 / abs(a)
    return 1.909


def kelly_fraction_full(win_probability: float, decimal_odds: float) -> float:
    """
    Full Kelly: f* = p - (1-p)/b where b = decimal_odds - 1 (profit per unit).
    Returns fraction of bankroll to bet; negative means no bet.
    """
    if win_probability <= 0 or win_probability >= 1:
        return 0.0
    b = decimal_odds - 1.0
    if b <= 0:
        return 0.0
    q = 1.0 - win_probability
    f_star = win_probability - q / b
    return max(0.0, f_star)


def calculate_kelly_bet(
    win_probability: float,
    market_odds: float,
    bankroll: float,
    kelly_fraction: float = 0.25,
) -> tuple[float, float]:
    """
    Quarter-Kelly (default) bet size from win probability and market odds.

    Args:
        win_probability: p in Kelly formula (e.g. from bias_report Sweet Spot win_rate).
        market_odds: American odds (e.g. -110 for standard spread/total).
        bankroll: Total bankroll in dollars (e.g. from configs/runtime/bankroll.json).
        kelly_fraction: Fraction of full Kelly to use (0.25 = Quarter-Kelly).

    Returns:
        (fraction, amount): fraction of bankroll (e.g. 0.025 for 2.5%), dollar amount.
    """
    if bankroll is None or bankroll <= 0:
        return 0.0, 0.0
    if win_probability is None or win_probability <= 0 or win_probability >= 1:
        return 0.0, 0.0
    kelly_fraction = kelly_fraction if kelly_fraction is not None else 0.25
    decimal = american_to_decimal(market_odds)
    f_full = kelly_fraction_full(win_probability, decimal)
    f_actual = kelly_fraction * f_full
    amount = bankroll * f_actual
    return f_actual, amount
