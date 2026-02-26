# prj_BookieX/eng/backtest_runner.py

import json
import csv
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict

from eng.backtest_grader import (grade_game, grade_spread_bet,grade_total_bet, grade_parlay,)
from eng.backtest_summary import build_summary

# ---------- CONFIG ----------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_JSON = PROJECT_ROOT / "data/view/final_game_view.json"
OUTPUT_ROOT = PROJECT_ROOT / "eng/outputs/backtests"

REQUIRED_FIELDS = [
    "game_id",
    "home_points",
    "away_points",
]

GRADE_REQUIRED_FIELDS = [
    "spread_home",
    "spread_away",
    "total",
    "Line Bet",
    "Total Bet",
]
# ---------------------------


def _fail_fast_missing_fields(g: Dict):
    missing = [k for k in REQUIRED_FIELDS if k not in g]
    if missing:
        raise ValueError(f"Missing required fields {missing} for game_id={g.get('game_id')}")


def load_games() -> List[Dict]:
    if not INPUT_JSON.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_JSON}")

    with INPUT_JSON.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("final_game_view.json must be a flat list of games")

    return data


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def write_csv(path: Path, rows: List[Dict]):
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        print("No rows to write to CSV.")
        return

    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    out_dir = OUTPUT_ROOT / f"backtest_{run_ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    games = load_games()

    backtest_rows = []
    skipped = []

    for g in games:
        try:
            _fail_fast_missing_fields(g)

            missing_grade = [k for k in GRADE_REQUIRED_FIELDS if g.get(k) is None]
            if missing_grade:
                skipped.append({
                    "game_id": g.get("game_id"),
                    "reason": f"Missing market fields: {missing_grade}"
                })
                continue

            g["home_score_final"] = g.get("home_points")
            g["away_score_final"] = g.get("away_points")

            if g["home_score_final"] is None or g["away_score_final"] is None:
                skipped.append({
                    "game_id": g.get("game_id"),
                    "reason": "Final scores missing"
                })
                continue

            grading = grade_game(g)

            row = dict(g)
            # row["model_results"] = g.get("model_results", [])

            model_outcomes = {}

            for name, m in g.get("models", {}).items():
                spread_pick = m.get("spread_pick")
                total_pick = m.get("total_pick")

                spread_result = grade_spread_bet(
                    line_bet=spread_pick,
                    spread_home=g.get("spread_home"),
                    home_score_final=g.get("home_score_final"),
                    away_score_final=g.get("away_score_final"),
                )

                total_result = grade_total_bet(
                    total_bet=total_pick,
                    market_total=g.get("total"),
                    home_score_final=g.get("home_score_final"),
                    away_score_final=g.get("away_score_final"),
                )

                parlay_result = grade_parlay(spread_result, total_result)

                model_outcomes[name] = {
                    "spread_pick": spread_pick,
                    "spread_result": spread_result,
                    "total_pick": total_pick,
                    "total_result": total_result,
                    "parlay_result": parlay_result,
                }

            row["model_results"] = model_outcomes

            row.update(grading)

            backtest_rows.append(row)

        except Exception as e:
            raise RuntimeError(
                f"Backtest failed for game_id={g.get('game_id')}: {e}"
            ) from e

    if not backtest_rows:
        print("Backtest complete: no games eligible for grading.")

    write_json(out_dir / "backtest_games.json", backtest_rows)
    write_csv(out_dir / "backtest_games.csv", backtest_rows)

    summary = build_summary(backtest_rows, skipped)
    write_json(out_dir / "backtest_summary.json", summary)

    print("Backtest complete.")
    print(f"Graded games: {len(backtest_rows)}")
    print(f"Skipped games: {len(skipped)}")
    print(f"Output dir: {out_dir.resolve()}")


if __name__ == "__main__":
    main()