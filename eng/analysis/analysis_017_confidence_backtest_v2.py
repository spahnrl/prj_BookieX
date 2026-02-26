# prj_BookieX/eng/analysis/analysis_017_confidence_backtest_v2.py

import json
from pathlib import Path
from collections import defaultdict
import statistics

# -------------------------------------------------------
# CONFIG
# -------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MULTI_MODEL_PATH = PROJECT_ROOT / "data/view/nba_games_multi_model_v1.json"
BACKTEST_ROOT = PROJECT_ROOT / "eng/outputs/backtests"


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_backtest_file() -> Path:
    if not BACKTEST_ROOT.exists():
        raise FileNotFoundError("No backtests directory found.")

    subdirs = [
        d for d in BACKTEST_ROOT.iterdir()
        if d.is_dir() and not d.name.startswith("zzz")
    ]

    if not subdirs:
        raise RuntimeError("No valid backtest directories found.")

    # Use modification time (correct behavior)
    latest_dir = max(subdirs, key=lambda d: d.stat().st_mtime)

    file_path = latest_dir / "backtest_games.json"

    if not file_path.exists():
        raise RuntimeError(f"No backtest_games.json in {latest_dir}")

    return file_path


def classify_game(models_dict) -> str:
    """
    Directional disagreement-based confidence.

    HIGH: All non-null edges share same sign
    LOW: Both positive and negative edges present
    MEDIUM: All other cases
    """

    signs = []

    # NEW SHAPE: dict
    for model in models_dict.values():

        edge = model.get("total_edge")  # critical fix

        if edge is None:
            continue

        if edge > 0:
            signs.append(1)
        elif edge < 0:
            signs.append(-1)

    if len(signs) < 2:
        return "INSUFFICIENT"

    has_positive = any(s > 0 for s in signs)
    has_negative = any(s < 0 for s in signs)

    if has_positive and has_negative:
        return "LOW"
    elif has_positive or has_negative:
        return "HIGH"
    else:
        return "MEDIUM"


# -------------------------------------------------------
# Main
# -------------------------------------------------------

def main():

    raw_multi = load_json(MULTI_MODEL_PATH)

    if isinstance(raw_multi, dict) and "games" in raw_multi:
        multi_model_games = raw_multi["games"]
    elif isinstance(raw_multi, list):
        multi_model_games = raw_multi
    else:
        multi_model_games = list(raw_multi.values())

    backtest_path = get_latest_backtest_file()
    backtest_games = load_json(backtest_path)

    multi_lookup = {g["game_id"]: g for g in multi_model_games}
    backtest_lookup = {g["game_id"]: g for g in backtest_games}

    tier_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0})

    for game_id, bt_game in backtest_lookup.items():

        multi_game = multi_lookup.get(game_id)
        if not multi_game:
            continue

        models_dict = multi_game.get("models", {})
        tier = classify_game(models_dict)

        result = bt_game.get("total_result")

        if result not in ("WIN", "LOSS"):
            continue

        tier_stats[tier]["total"] += 1

        if result == "WIN":
            tier_stats[tier]["wins"] += 1
        else:
            tier_stats[tier]["losses"] += 1

    print("\n=== CONFIDENCE BACKTEST RESULTS ===\n")

    for tier in ["HIGH", "MEDIUM", "LOW", "INSUFFICIENT"]:
        stats = tier_stats.get(tier)
        if not stats or stats["total"] == 0:
            continue

        win_rate = stats["wins"] / stats["total"]

        print(f"{tier}")
        print(f"  Games: {stats['total']}")
        print(f"  Wins: {stats['wins']}")
        print(f"  Losses: {stats['losses']}")
        print(f"  Win Rate: {win_rate:.3f}")
        print()

    print("Latest Backtest File Used:")
    print(backtest_path.resolve())


if __name__ == "__main__":
    main()