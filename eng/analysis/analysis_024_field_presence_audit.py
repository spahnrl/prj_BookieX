# eng/analysis/analysis_024_field_presence_audit.py

"""
FIELD PRESENCE AUDIT

Purpose:
Verify required keys exist in final_game_view.json.
"""

import json
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FINAL_PATH = PROJECT_ROOT / "data/view/final_game_view.json"


def main():

    with FINAL_PATH.open("r", encoding="utf-8") as f:
        games = json.load(f)

    required_fields = [
        "Projected Home Score",
        "Projected Away score",
        "home_points",
        "away_points",
        "Spread Edge",
        "Line Bet"
    ]

    presence_counter = Counter()
    total_games = len(games)

    for g in games:
        for field in required_fields:
            if field in g and g[field] is not None:
                presence_counter[field] += 1

    print("\n=== FIELD PRESENCE AUDIT ===\n")
    print(f"Total Games: {total_games}\n")

    for field in required_fields:
        count = presence_counter[field]
        pct = round(count / total_games, 3)
        print(f"{field}")
        print(f"  Present: {count}")
        print(f"  Coverage: {pct}")
        print()

    print("=== END REPORT ===\n")


if __name__ == "__main__":
    main()