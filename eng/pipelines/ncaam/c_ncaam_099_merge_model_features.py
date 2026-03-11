"""
c_ncaam_099_merge_model_features.py

Purpose
-------
Merge NCAA feature tables into one model-ready input table.

Inputs
------
- data/ncaam/model/ncaam_game_level_with_avg_features.csv
- data/ncaam/model/ncaam_game_level_with_last5_momentum.csv

Output
------
- data/ncaam/model/ncaam_model_input_v1.csv

Design goals
------------
- Keep feature builders separate
- Provide one unified input table for all NCAA models
- Join on canonical_game_id
- Prefer avg-feature table as the base grain
"""

import csv
from pathlib import Path

from configs.leagues.league_ncaam import MODEL_DIR, ensure_ncaam_dirs

AVG_PATH = MODEL_DIR / "ncaam_game_level_with_avg_features.csv"
LAST5_PATH = MODEL_DIR / "ncaam_game_level_with_last5_momentum.csv"
OUTPUT_PATH = MODEL_DIR / "ncaam_model_input_v1.csv"


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Missing input file: {path}")
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def index_by_canonical_game_id(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for row in rows:
        cid = (row.get("canonical_game_id") or "").strip()
        if cid:
            out[cid] = row
    return out


def merge_rows(avg_rows: list[dict], last5_rows: list[dict]) -> list[dict]:
    last5_idx = index_by_canonical_game_id(last5_rows)

    merged = []

    for avg_row in avg_rows:
        cid = (avg_row.get("canonical_game_id") or "").strip()
        last5_row = last5_idx.get(cid, {})

        row = dict(avg_row)

        # add only momentum fields from last5 file
        for key in [
            "home_last5_points_for",
            "home_last5_points_against",
            "home_last5_avg_margin",
            "home_last5_win_pct",
            "home_last5_games_in_history",
            "away_last5_points_for",
            "away_last5_points_against",
            "away_last5_avg_margin",
            "away_last5_win_pct",
            "away_last5_games_in_history",
        ]:
            row[key] = last5_row.get(key, "")

        merged.append(row)

    merged.sort(key=lambda r: (r.get("game_date", ""), r.get("canonical_game_id", "")))
    return merged


def write_rows(rows: list[dict], path: Path) -> None:
    if not rows:
        raise ValueError("No merged rows to write")

    fieldnames = list(rows[0].keys())

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run() -> None:
    ensure_ncaam_dirs()

    avg_rows = load_rows(AVG_PATH)
    last5_rows = load_rows(LAST5_PATH)

    merged_rows = merge_rows(avg_rows, last5_rows)
    write_rows(merged_rows, OUTPUT_PATH)

    with_home_avg = sum(1 for r in merged_rows if str(r.get("home_avg_points_for", "")).strip() != "")
    with_home_last5 = sum(1 for r in merged_rows if str(r.get("home_last5_points_for", "")).strip() != "")

    print(f"Loaded avg rows:             {len(avg_rows)}")
    print(f"Loaded last5 rows:           {len(last5_rows)}")
    print(f"Merged output written to:    {OUTPUT_PATH}")
    print(f"Merged rows:                 {len(merged_rows)}")
    print(f"Rows with avg features:      {with_home_avg}")
    print(f"Rows with last5 features:    {with_home_last5}")


if __name__ == "__main__":
    run()
