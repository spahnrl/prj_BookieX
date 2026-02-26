"""
analysis_029_model_pipeline_trace.py

FULL MODEL PIPELINE TRACE AUDIT

This script inspects:

1. Raw model output (from nba_games_multi_model_v1.json)
2. Flattened output (from final_game_view.json)
3. Backtest artifact (backtest_games.json)

It verifies:
- Model contract fields exist
- spread_edge sign matches spread_pick
- Flattened fields match Joel_Baseline_v1 model
- No silent sign inversions occurred
"""

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

MULTI_MODEL_PATH = PROJECT_ROOT / "data/view/nba_games_multi_model_v1.json"
FINAL_VIEW_PATH = PROJECT_ROOT / "data/view/final_game_view.json"
BACKTEST_ROOT = PROJECT_ROOT / "eng/outputs/backtests"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_backtest():
    subdirs = [d for d in BACKTEST_ROOT.iterdir() if d.is_dir()]
    latest = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest / "backtest_games.json"


def sign(x):
    if x is None:
        return 0
    return 1 if x > 0 else -1 if x < 0 else 0


def main():

    multi_payload = load_json(MULTI_MODEL_PATH)
    multi_games = multi_payload["games"]

    final_games = load_json(FINAL_VIEW_PATH)
    backtest_games = load_json(get_latest_backtest())

    multi_map = {g["game_id"]: g for g in multi_games}
    final_map = {g["game_id"]: g for g in final_games}
    backtest_map = {g["game_id"]: g for g in backtest_games}

    checked = 0
    contract_failures = 0
    flatten_mismatch = 0
    sign_mismatch = 0

    for game_id, multi_game in multi_map.items():

        joel = multi_game.get("models", {}).get("Joel_Baseline_v1", {})
        if not joel:
            continue

        edge = joel.get("spread_edge")
        pick = joel.get("spread_pick")

        # ---------- CONTRACT CHECK ----------
        if edge is None or pick not in ("HOME", "AWAY"):
            contract_failures += 1
            continue

        # ---------- SIGN CONSISTENCY ----------
        if sign(edge) > 0 and pick != "HOME":
            sign_mismatch += 1
        if sign(edge) < 0 and pick != "AWAY":
            sign_mismatch += 1

        # ---------- FLATTEN CHECK ----------
        final_game = final_map.get(game_id)
        if not final_game:
            continue

        if (
            final_game.get("Spread Edge") != edge or
            final_game.get("Line Bet") != pick
        ):
            flatten_mismatch += 1

        checked += 1

    print("\n=== MODEL PIPELINE TRACE AUDIT ===\n")
    print("Games Checked:", checked)
    print("Contract Failures:", contract_failures)
    print("Edge ↔ Pick Sign Mismatch:", sign_mismatch)
    print("Flatten Mismatch:", flatten_mismatch)

    if contract_failures == 0 and sign_mismatch == 0 and flatten_mismatch == 0:
        print("\nSTATUS: PIPELINE STRUCTURALLY CONSISTENT")
    else:
        print("\nSTATUS: STRUCTURAL ISSUES DETECTED")


if __name__ == "__main__":
    main()