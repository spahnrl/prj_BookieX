import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = PROJECT_ROOT / "data/view/final_game_view.json"

def main():
    with INPUT_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    total_games = len(data)
    fatigue_games = 0
    both_fatigue = 0

    for g in data:
        home_flag = g.get("home_fatigue_flag", False)
        away_flag = g.get("away_fatigue_flag", False)

        if home_flag or away_flag:
            fatigue_games += 1

        if home_flag and away_flag:
            both_fatigue += 1

    print("=== FATIGUE ACTIVATION REPORT ===")
    print(f"Total Games: {total_games}")
    print(f"Games with ANY fatigue: {fatigue_games}")
    print(f"Games with BOTH teams fatigued: {both_fatigue}")
    print("=== END REPORT ===")


if __name__ == "__main__":
    main()