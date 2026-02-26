import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

FATIGUE_PATH = PROJECT_ROOT / "data/derived/nba_games_with_fatigue.json"
FINAL_PATH = PROJECT_ROOT / "data/view/final_game_view.json"


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