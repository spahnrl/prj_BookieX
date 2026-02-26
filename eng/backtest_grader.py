# prj_BookieX/eng/backtest_grader.py

from typing import Dict, Optional


# def grade_spread_bet(
#     line_bet: Optional[str],
#     spread_home: Optional[float],
#     home_score_final: Optional[int],
#     away_score_final: Optional[int],
# ) -> Optional[str]:
#     """
#     Returns WIN / LOSS / PUSH / None
#     """
#     if not line_bet or spread_home is None:
#         return None
#     if home_score_final is None or away_score_final is None:
#         raise ValueError("Final scores missing for spread grading")
#
#     actual_margin = home_score_final - away_score_final
#
#     if actual_margin == spread_home:
#         return "PUSH"
#
#     if line_bet == "HOME":
#         return "WIN" if actual_margin > spread_home else "LOSS"
#
#     if line_bet == "AWAY":
#         return "WIN" if actual_margin < spread_home else "LOSS"
#
#     raise ValueError(f"Invalid Line Bet value: {line_bet}")

# def grade_spread_bet(
#     line_bet: Optional[str],
#     spread_home: Optional[float],
#     home_score_final: Optional[int],
#     away_score_final: Optional[int],
# ) -> Optional[str]:
#     """
#     Returns WIN / LOSS / PUSH / None
#     """
#
#     # No bet placed
#     if not line_bet or spread_home is None:
#         return None
#
#     # If model explicitly marked PUSH → no action
#     if line_bet == "PUSH":
#         return "PUSH"
#
#     if home_score_final is None or away_score_final is None:
#         raise ValueError("Final scores missing for spread grading")
#
#     actual_margin = home_score_final - away_score_final
#
#     if actual_margin == spread_home:
#         return "PUSH"
#
#     if line_bet == "HOME":
#         return "WIN" if actual_margin > spread_home else "LOSS"
#
#     if line_bet == "AWAY":
#         return "WIN" if actual_margin < spread_home else "LOSS"
#
#     raise ValueError(f"Invalid Line Bet value: {line_bet}")

def grade_spread_bet(
    line_bet: Optional[str],
    spread_home: Optional[float],
    home_score_final: Optional[int],
    away_score_final: Optional[int],
) -> Optional[str]:

    if not line_bet or spread_home is None:
        return None

    if line_bet == "PUSH":
        return "PUSH"

    if home_score_final is None or away_score_final is None:
        raise ValueError("Final scores missing for spread grading")

    actual_margin = home_score_final - away_score_final

    adjusted = actual_margin + spread_home

    if adjusted == 0:
        return "PUSH"

    if line_bet == "HOME":
        return "WIN" if adjusted > 0 else "LOSS"

    if line_bet == "AWAY":
        return "WIN" if adjusted < 0 else "LOSS"

    raise ValueError(f"Invalid Line Bet value: {line_bet}")

def grade_total_bet(
    total_bet: Optional[str],
    market_total: Optional[float],
    home_score_final: Optional[int],
    away_score_final: Optional[int],
) -> Optional[str]:
    """
    Returns WIN / LOSS / PUSH / None
    """
    if not total_bet or market_total is None:
        return None
    if home_score_final is None or away_score_final is None:
        raise ValueError("Final scores missing for total grading")

    actual_total = home_score_final + away_score_final

    if actual_total == market_total:
        return "PUSH"

    if total_bet == "OVER":
        return "WIN" if actual_total > market_total else "LOSS"

    if total_bet == "UNDER":
        return "WIN" if actual_total < market_total else "LOSS"

    raise ValueError(f"Invalid Total Bet value: {total_bet}")


def grade_parlay(
    spread_result: Optional[str],
    total_result: Optional[str],
) -> Optional[str]:
    """
    Returns WIN / LOSS / PUSH / None
    """
    if not spread_result or not total_result:
        return None

    if "LOSS" in (spread_result, total_result):
        return "LOSS"

    if spread_result == "PUSH" or total_result == "PUSH":
        return "PUSH"

    return "WIN"


def grade_game(game: Dict) -> Dict:
    """
    Returns additive grading fields only.
    """
    spread_result = grade_spread_bet(
        line_bet=game.get("Line Bet"),
        spread_home=game.get("spread_home"),
        home_score_final=game.get("home_score_final"),
        away_score_final=game.get("away_score_final"),
    )

    total_result = grade_total_bet(
        total_bet=game.get("Total Bet"),
        market_total=game.get("total"),
        home_score_final=game.get("home_score_final"),
        away_score_final=game.get("away_score_final"),
    )

    parlay_result = grade_parlay(spread_result, total_result)

    return {
        "spread_result": spread_result,
        "total_result": total_result,
        "parlay_result": parlay_result,
        "actual_margin": (
            None
            if game.get("home_score_final") is None
            else game["home_score_final"] - game["away_score_final"]
        ),
        "actual_total": (
            None
            if game.get("home_score_final") is None
            else game["home_score_final"] + game["away_score_final"]
        ),
    }