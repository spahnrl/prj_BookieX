"""
analysis_016_confidence_on_backtest.py

Apply current Hybrid confidence logic
to historical backtest games and measure win rate by tier.
"""

import json
from pathlib import Path
from collections import defaultdict

# ============================================================
# PROJECT PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_DIR = PROJECT_ROOT / "eng/outputs/backtests"

# ============================================================
# HYBRID CLASSIFIER (Embedded for Stability)
# ============================================================

def classify_game(models):
    """
    Hybrid magnitude classifier.

    Uses max absolute spread_edge across:
    - Joel_Baseline_v1
    - FatiguePlus_v3
    - InjuryModel_v2
    """

    joel = models.get("Joel_Baseline_v1", {})
    fatigue = models.get("FatiguePlus_v3", {})
    injury = models.get("InjuryModel_v2", {})

    edges = [
        joel.get("spread_edge"),
        fatigue.get("spread_edge"),
        injury.get("spread_edge"),
    ]

    edges = [e for e in edges if e is not None]

    if not edges:
        return "IGNORE"

    magnitude = max(abs(e) for e in edges)

    signs = set()
    for e in edges:
        if e > 0:
            signs.add(1)
        elif e < 0:
            signs.add(-1)

    cluster_aligned = len(signs) == 1

    # ---------------------------------------------------------
    # Tier logic (TIGHTENED)
    # ---------------------------------------------------------

    if magnitude < 2:
        return "IGNORE"
    elif cluster_aligned and magnitude >= 6:
        return "HIGH"
    elif cluster_aligned and magnitude >= 3:
        return "MODERATE"
    else:
        return "LOW"

# ============================================================
# UTILITIES
# ============================================================

def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_backtest_folder():
    """
    Return most recent backtest folder
    that actually contains backtest_games.json
    """

    valid_folders = []

    for folder in BACKTEST_DIR.iterdir():
        if not folder.is_dir():
            continue

        test_file = folder / "backtest_games.json"
        if test_file.exists():
            valid_folders.append(folder)

    if not valid_folders:
        raise FileNotFoundError("No valid backtest folders found.")

    valid_folders.sort()
    return valid_folders[-1]


# ============================================================
# MAIN ANALYSIS
# ============================================================

def main():

    latest = get_latest_backtest_folder()
    print(f"Using backtest folder: {latest.name}")

    games_path = latest / "backtest_games.json"
    games = load_json(games_path)

    tier_counts = defaultdict(int)
    tier_wins = defaultdict(int)

    for game in games:

        models = game.get("models", {})
        tier = classify_game(models)

        tier_counts[tier] += 1

        if game.get("parlay_result") == "WIN":
            tier_wins[tier] += 1

    print("\n=== CONFIDENCE BACKTEST (HISTORICAL) ===\n")

    total_games = sum(tier_counts.values())

    for tier in sorted(tier_counts.keys()):

        count = tier_counts[tier]
        wins = tier_wins[tier]
        win_rate = wins / count if count > 0 else 0
        exposure = count / total_games if total_games else 0

        print(f"{tier}")
        print(f"  Games: {count}")
        print(f"  Exposure: {exposure:.2%}")
        print(f"  Wins: {wins}")
        print(f"  Win Rate: {win_rate:.4f}")
        print()

    print("=== END REPORT ===\n")


if __name__ == "__main__":
    main()