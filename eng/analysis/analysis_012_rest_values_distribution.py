import json
from pathlib import Path
import collections

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_PATH = BASE_DIR / "data" / "derived" / "nba_games_with_b2b.json"

def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    home_rest_values = collections.Counter()
    away_rest_values = collections.Counter()

    for g in data:
        home_rest_values[g.get("home_rest_days")] += 1
        away_rest_values[g.get("away_rest_days")] += 1

    print("=== HOME REST DISTRIBUTION ===")
    print(home_rest_values)
    print()
    print("=== AWAY REST DISTRIBUTION ===")
    print(away_rest_values)
    print("=== END REPORT ===")

if __name__ == "__main__":
    main()