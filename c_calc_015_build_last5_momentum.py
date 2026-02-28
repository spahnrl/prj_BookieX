import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = PROJECT_ROOT / "data/derived/nba_boxscores_team.json"
OUTPUT_PATH = PROJECT_ROOT / "data/derived/nba_boxscores_team_last5.json"


def main():

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        games = json.load(f)

    # Only finalized games
    games = [g for g in games if g.get("_boxscore_status") == "FINAL"]

    # Sort chronologically
    games.sort(
        key=lambda g: datetime.fromisoformat(
            g["game_date"].replace("Z", "+00:00")
        )
    )

    team_history = defaultdict(list)

    for g in games:

        home_id = g["home_team_id"]
        away_id = g["away_team_id"]

        # -----------------------------
        # HOME TEAM LAST 5
        # -----------------------------
        home_hist = team_history[home_id][-5:]

        if home_hist:
            g["home_last5_points_for"] = sum(x["pf"] for x in home_hist) / len(home_hist)
            g["home_last5_points_against"] = sum(x["pa"] for x in home_hist) / len(home_hist)
        else:
            g["home_last5_points_for"] = None
            g["home_last5_points_against"] = None

        # -----------------------------
        # AWAY TEAM LAST 5
        # -----------------------------
        away_hist = team_history[away_id][-5:]

        if away_hist:
            g["away_last5_points_for"] = sum(x["pf"] for x in away_hist) / len(away_hist)
            g["away_last5_points_against"] = sum(x["pa"] for x in away_hist) / len(away_hist)
        else:
            g["away_last5_points_for"] = None
            g["away_last5_points_against"] = None

        # -----------------------------
        # Append current game AFTER computing
        # -----------------------------
        team_history[home_id].append({
            "pf": g["home_score"],
            "pa": g["away_score"]
        })

        team_history[away_id].append({
            "pf": g["away_score"],
            "pa": g["home_score"]
        })

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(games, f, indent=2)

    print("✅ Last 5 (location agnostic) momentum fields added")
    print(f"📄 Output → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()