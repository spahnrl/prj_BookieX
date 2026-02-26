"""
bookiex_cli.py

Phase 3 — Minimal Interaction Layer

Rules:
- Read DAILY_VIEW_V1 only
- No recomputation
- No ingestion
- No writes
- Deterministic formatting
"""

import json
import sys
from pathlib import Path
from datetime import datetime

DAILY_DIR = Path("data/daily")


# ------------------------------------------------------------
# Loader
# ------------------------------------------------------------

def load_daily_view(date_str=None):
    if date_str:
        file_path = DAILY_DIR / f"daily_view_{date_str}_v1.json"
    else:
        files = sorted(DAILY_DIR.glob("daily_view_*_v1.json"))
        if not files:
            sys.exit("No DAILY_VIEW files found.")
        file_path = files[-1]

    if not file_path.exists():
        sys.exit(f"File not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # DAILY_VIEW_V1 is a wrapped object → extract games list
    if isinstance(data, dict) and "games" in data:
        return data["games"]

    # Fallback (if ever needed)
    if isinstance(data, list):
        return data

    sys.exit("Invalid DAILY_VIEW format.")

# ------------------------------------------------------------
# Formatting Helpers
# ------------------------------------------------------------

def header(title):
    print(f"\n=== {title} ===\n")


def format_game_label(g):
    return f"{g['away_team']} @ {g['home_team']}"


def round1(x):
    return round(x, 1) if isinstance(x, (int, float)) else None


# ------------------------------------------------------------
# Commands
# ------------------------------------------------------------

def show_action(games):
    header("BOOKIEX DAILY ACTION")

    action_games = sorted(
        [g for g in games if g["actionability"] == "ACTION"],
        key=lambda x: (- (x.get("parlay_edge_score") or 0), x["game_id"])
    )

    if not action_games:
        print("No ACTION games.")
        return

    for i, g in enumerate(action_games, 1):
        print(f"{i}) {format_game_label(g)}")

        if g.get("spread_pick"):
            print(f"   Pick: {g.get('spread_pick')}")
            print(f"   Spread Edge: +{round1(g.get('spread_edge'))}")

        if g.get("total_pick"):
            print(f"   Pick: {g.get('total_pick')}")
            print(f"   Total Edge: +{round1(g.get('total_edge'))}")

        print(f"   Confidence: {g.get('confidence_reason')}")
        print()


def show_ignore(games):
    header("IGNORED GAMES")

    ignored = sorted(
        [g for g in games if g["actionability"] == "IGNORE"],
        key=lambda x: x["game_id"]
    )

    if not ignored:
        print("No ignored games.")
        return

    for g in ignored:
        print(f"• {format_game_label(g)}")
        print(f"  Reason: {g.get('confidence_reason')}")
        print()


def show_why(games):
    header("ACTION EXPLANATIONS")

    action_games = sorted(
        [g for g in games if g["actionability"] == "ACTION"],
        key=lambda x: (-(x.get("parlay_edge_score") or 0), x["game_id"])
    )

    if not action_games:
        print("No ACTION games.")
        return

    for g in action_games:
        print(format_game_label(g))

        if g.get("spread_pick"):
            print(f"  Pick: {g.get('spread_pick')}")
            if g.get("spread_edge") is not None:
                print(f"  Spread Edge: +{round1(g.get('spread_edge'))}")

        if g.get("total_pick"):
            print(f"  Pick: {g.get('total_pick')}")
            if g.get("total_edge") is not None:
                print(f"  Total Edge: +{round1(g.get('total_edge'))}")

        if g.get("parlay_edge_score") is not None:
            print(f"  Parlay Score: +{round1(g.get('parlay_edge_score'))}")

        print(f"  Confidence: {g.get('confidence_reason')}")
        print()


def show_disagreement(games):
    header("MODEL / MARKET DISAGREEMENT")

    disagreements = []

    for g in games:
        proj = g.get("model_projection_spread")
        market = g.get("market_spread")

        if proj is not None and market is not None:
            diff = abs(proj - market)
            if diff >= 5:  # purely display threshold, not model logic
                disagreements.append((diff, g))

    disagreements.sort(key=lambda x: (-x[0], x[1]["game_id"]))

    if not disagreements:
        print("No major disagreements.")
        return

    for diff, g in disagreements:
        print(f"{format_game_label(g)}")
        print(f"  Projection: {round1(g.get('model_projection_spread'))}")
        print(f"  Market: {round1(g.get('market_spread'))}")
        print(f"  Delta: {round1(diff)}")
        print()


def show_changes(games):
    header("WHAT CHANGED")

    print("Change tracking requires prior snapshot comparison.")
    print("Phase 3 minimal implementation: not yet enabled.")
    print()


# ------------------------------------------------------------
# Main Router
# ------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python bookiex_cli.py [action|ignore|why|disagreement|changes]")

    command = sys.argv[1].lower()
    date_str = None

    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        date_str = sys.argv[idx + 1]

    games = load_daily_view(date_str)

    if command == "action":
        show_action(games)
    elif command == "ignore":
        show_ignore(games)
    elif command == "why":
        show_why(games)
    elif command == "disagreement":
        show_disagreement(games)
    elif command == "changes":
        show_changes(games)
    else:
        sys.exit("Invalid command.")


if __name__ == "__main__":
    main()