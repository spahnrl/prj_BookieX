import json
from pathlib import Path

from configs.leagues.league_nba import DERIVED_DIR, FINAL_VIEW_JSON_PATH

FATIGUE_PATH = DERIVED_DIR / "nba_games_with_fatigue.json"
FINAL_PATH = FINAL_VIEW_JSON_PATH


def load(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main():
    fatigue_games = load(FATIGUE_PATH)
    final_games = load(FINAL_PATH)

    fatigue_sample = fatigue_games[0]
    final_sample = final_games[0]

    print("=== FATIGUE FILE KEYS ===")
    print(sorted(fatigue_sample.keys()))

    print("\n=== FINAL FILE KEYS ===")
    print(sorted(final_sample.keys()))

    print("\n=== CHECKING FATIGUE FIELDS IN FINAL ===")

    fatigue_fields = [
        "home_fatigue_score",
        "away_fatigue_score",
        "fatigue_diff_home_minus_away"
    ]

    for field in fatigue_fields:
        present = field in final_sample
        print(f"{field}: {'PRESENT' if present else 'MISSING'}")


if __name__ == "__main__":
    main()