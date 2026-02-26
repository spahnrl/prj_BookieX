"""
c_calc_012_compute_fatigue_score.py

Compute a per-team fatigue score for each game using:
- Rest days
- Back-to-back
- Back-to-back-to-back
- Overtime minutes

Reads:
  data/external/nba_boxscores_team.json

Writes:
  data/derived/nba_games_with_fatigue.json
  data/derived/nba_games_with_fatigue.csv
"""

import json
import csv
from pathlib import Path


INPUT_PATH = Path("data/derived/nba_games_with_b2b.json")
OUTPUT_DIR = Path("data/derived")


# --- Tunable weights (MVP defaults) ---
BASELINE_FATIGUE = 0.0

REST_DAY_PENALTY = {
    0: 1.0,   # no rest
    1: 0.4,   # one day rest
    2: 0.15,  # two days rest
}
MAX_REST_PENALTY = 0.0  # 3+ days rest

B2B_PENALTY = 0.6
B2B2B_PENALTY = 1.0

OT_5_MIN_PENALTY = 0.35  # per 5-minute OT


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def rest_penalty(rest_days: int | None) -> float:
    if rest_days is None:
        return 0.0
    return REST_DAY_PENALTY.get(rest_days, MAX_REST_PENALTY)


def compute_team_fatigue(
    rest_days: int | None,
    is_b2b: bool,
    is_b2b2b: bool,
    ot_minutes: int,
) -> float:
    score = BASELINE_FATIGUE

    score += rest_penalty(rest_days)

    if is_b2b:
        score += B2B_PENALTY

    if is_b2b2b:
        score += B2B2B_PENALTY

    if ot_minutes and ot_minutes > 0:
        score += (ot_minutes / 5) * OT_5_MIN_PENALTY

    return round(score, 3)


def compute_fatigue(games: list[dict]) -> list[dict]:
    enriched = []

    for g in games:
        record = dict(g)

        home_fatigue = compute_team_fatigue(
            rest_days=g.get("home_rest_days"),
            is_b2b=g.get("home_back_to_back", False),
            is_b2b2b=g.get("home_back_to_back_to_back", False),
            ot_minutes=g.get("ot_minutes", 0),
        )

        away_fatigue = compute_team_fatigue(
            rest_days=g.get("away_rest_days"),
            is_b2b=g.get("away_back_to_back", False),
            is_b2b2b=g.get("away_back_to_back_to_back", False),
            ot_minutes=g.get("ot_minutes", 0),
        )

        record["home_fatigue_score"] = home_fatigue
        record["away_fatigue_score"] = away_fatigue
        record["fatigue_diff_home_minus_away"] = round(
            home_fatigue - away_fatigue, 3
        )

        enriched.append(record)

    return enriched


def write_outputs(records: list[dict]):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "nba_games_with_fatigue.json"
    csv_path = OUTPUT_DIR / "nba_games_with_fatigue.csv"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)

    print(f"Fatigue JSON saved to: {json_path}")
    print(f"Fatigue CSV  saved to: {csv_path}")


def run():
    games = load_json(INPUT_PATH)
    print(f"Loaded games: {len(games)}")

    enriched = compute_fatigue(games)
    write_outputs(enriched)


if __name__ == "__main__":
    run()
