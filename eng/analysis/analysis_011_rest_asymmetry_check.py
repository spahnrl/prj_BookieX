import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_PATH = BASE_DIR / "data" / "derived" / "nba_games_with_b2b.json"

def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    asymmetric = 0

    for g in data:
        if g.get("home_rest_days") != g.get("away_rest_days"):
            asymmetric += 1

    print("=== REST ASYMMETRY CHECK ===")
    print("Total Games:", len(data))
    print("Games with asymmetric rest:", asymmetric)
    print("=== END REPORT ===")

if __name__ == "__main__":
    main()