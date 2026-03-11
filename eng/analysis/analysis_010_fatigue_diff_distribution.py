import json
import statistics

from configs.leagues.league_nba import FINAL_VIEW_JSON_PATH

DATA_PATH = FINAL_VIEW_JSON_PATH

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