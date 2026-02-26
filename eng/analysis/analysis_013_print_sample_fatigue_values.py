import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_PATH = BASE_DIR / "data" / "derived" / "nba_games_with_fatigue.json"


def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("=== SAMPLE FATIGUE RECORDS ===")

    count = 0
    for g in data:
        if (
            g.get("home_fatigue_score", 0) > 0
            or g.get("away_fatigue_score", 0) > 0
        ):
            print(
                g["game_id"],
                "HOME:",
                g.get("home_rest_days"),
                g.get("home_back_to_back"),
                g.get("home_back_to_back_to_back"),
                g.get("home_fatigue_score"),
                "| AWAY:",
                g.get("away_rest_days"),
                g.get("away_back_to_back"),
                g.get("away_back_to_back_to_back"),
                g.get("away_fatigue_score"),
                "| DIFF:",
                g.get("fatigue_diff_home_minus_away"),
            )
            count += 1

        if count >= 15:
            break

if __name__ == "__main__":
    main()