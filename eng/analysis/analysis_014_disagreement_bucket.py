# eng/analysis/analysis_014_disagreement_bucket.py

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MULTI_PATH = PROJECT_ROOT / "data/view/nba_games_multi_model_v1.json"
BASELINE_PATH = PROJECT_ROOT / "data/view/final_game_view.json"

BASELINE_MODEL = "Joel_Baseline_v1"
FATIGUE_MODEL = "FatiguePlus_v3"


def load_multi():
    with MULTI_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["games"]


def load_baseline():
    with BASELINE_PATH.open("r", encoding="utf-8") as f:
        return {g["game_id"]: g for g in json.load(f)}


def get_pick(edge):
    if edge is None:
        return None
    return "OVER" if edge > 0 else "UNDER"


def main():

    multi_games = load_multi()
    baseline_games = load_baseline()

    agree = []
    disagree = []

    for game in multi_games:

        game_id = game["game_id"]

        if game_id not in baseline_games:
            continue

        base_record = baseline_games[game_id]

        actual_total = (
            base_record.get("home_points", 0)
            + base_record.get("away_points", 0)
        )

        market_total = base_record.get("total")

        if market_total is None:
            continue

        actual_result = "OVER" if actual_total > market_total else "UNDER"

        models = game.get("models", {})

        if BASELINE_MODEL not in models or FATIGUE_MODEL not in models:
            continue

        baseline = models[BASELINE_MODEL]
        fatigue = models[FATIGUE_MODEL]

        # Updated field name
        b_pick = get_pick(baseline.get("total_edge"))
        f_pick = get_pick(fatigue.get("total_edge"))

        if b_pick is None or f_pick is None:
            continue

        correct_baseline = (b_pick == actual_result)
        correct_fatigue = (f_pick == actual_result)

        if b_pick == f_pick:
            agree.append((correct_baseline, correct_fatigue))
        else:
            disagree.append((correct_baseline, correct_fatigue))

    print("\n=== DISAGREEMENT ANALYSIS ===\n")
    print("Total Games Evaluated:", len(agree) + len(disagree))
    print("Agreement Count:", len(agree))
    print("Disagreement Count:", len(disagree))

    if disagree:
        b_win = sum(1 for x in disagree if x[0])
        f_win = sum(1 for x in disagree if x[1])

        print("\n--- Disagreement Bucket ---")
        print("Baseline Win %:", round(b_win / len(disagree), 4))
        print("FatiguePlus_v3 Win %:", round(f_win / len(disagree), 4))

    if agree:
        both_win = sum(1 for x in agree if x[0])
        print("\n--- Agreement Bucket ---")
        print("Shared Win %:", round(both_win / len(agree), 4))


if __name__ == "__main__":
    main()