import json
from pathlib import Path
import statistics

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_PATH = BASE_DIR / "data" / "view" / "final_game_view.json"

def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        games = json.load(f)

    diffs = []

    for g in games:
        diff = g.get("fatigue_diff_home_minus_away")

        if diff is not None and diff != 0:
            diffs.append(diff)

    print("=== FATIGUE DIFF DISTRIBUTION ===")
    print("Games with non-zero diff:", len(diffs))

    if diffs:
        print("Mean:", round(statistics.mean(diffs), 4))
        print("Std Dev:", round(statistics.stdev(diffs), 4))
        print("Min:", min(diffs))
        print("Max:", max(diffs))

    print("=== END REPORT ===")

if __name__ == "__main__":
    main()