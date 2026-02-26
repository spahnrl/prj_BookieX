"""
analysis_015_confidence_backtest.py

Evaluate historical win rate by confidence tier.

Reads:
    data/view/final_game_view.json

Outputs:
    Console summary of:
        - Tier distribution
        - Win rate per tier
"""

import json
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = PROJECT_ROOT / "data/view/final_game_view.json"


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Handle wrapped vs flat structure
    if isinstance(data, dict) and "games" in data:
        return data["games"]
    return data


def determine_total_result(game):
    """
    Compute WIN/LOSS for total bet directly from game fields.
    """

    total_pick = game.get("Total Bet")
    market_total = game.get("total")

    if total_pick not in ("OVER", "UNDER"):
        return None

    if market_total is None:
        return None

    actual_total = (
        game.get("home_points", 0)
        + game.get("away_points", 0)
    )

    actual_result = "OVER" if actual_total > market_total else "UNDER"

    return "WIN" if total_pick == actual_result else "LOSS"


def main():

    games = load_json(INPUT_PATH)

    tier_counts = defaultdict(int)
    tier_wins = defaultdict(int)

    for game in games:

        tier = game.get("confidence_tier", "UNKNOWN")
        tier_counts[tier] += 1

        result = determine_total_result(game)

        if result == "WIN":
            tier_wins[tier] += 1

    print("\n=== CONFIDENCE BACKTEST ===\n")

    for tier in sorted(tier_counts.keys()):

        count = tier_counts[tier]
        wins = tier_wins[tier]

        win_rate = (wins / count) if count > 0 else 0

        print(f"{tier}")
        print(f"  Games: {count}")
        print(f"  Win Rate: {win_rate:.4f}")
        print()

    print("=== END REPORT ===\n")


if __name__ == "__main__":
    main()