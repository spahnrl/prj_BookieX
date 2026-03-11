import json
from pathlib import Path
import datetime
import sys
# Unified Paths from your refactor


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests

NBA_VIEW = PROJECT_ROOT / "data" / "nba" / "view" / "final_game_view.json"

def backfill_test_alert():
    if not NBA_VIEW.exists():
        print(f"❌ Error: NBA final view not found at {NBA_VIEW}")
        return

    with open(NBA_VIEW, 'r') as f:
        games = json.load(f)

    # Filter for games that are finished (have scores)
    graded = [g for g in games if g.get('home_score') is not None and g.get('away_score') is not None]

    if not graded:
        print("❌ No completed games found in the NBA database to test with.")
        return

    # Pick the most recent graded game
    sample = sorted(graded, key=lambda x: x.get('game_date', ''), reverse=True)[0]
    matchup = f"{sample['away_team']} @ {sample['home_team']}"

    # Extract edges for the alert string
    s_edge = sample.get('spread_edge', 0.0)
    t_edge = sample.get('total_edge', 0.0)

    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Construct the Agent Alert line
    alert_line = (
        f"[{timestamp}] [NBA] [{matchup}] - STATUS: EXECUTE - KELLY SIZE: [5.0]% ($500.00). "
        f"[{sample['away_team']} (spread edge {s_edge}) | OVER (total edge {t_edge})] "
        f"EDGE: [spread={s_edge}|total={t_edge}] "
        f"REASON: [VALUE PEAK REACHED: Automated test alert for yesterday's matches]."
    )

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"\n{alert_line}")

    print(f"✅ Successfully added retro-alert for: {matchup}")
    print(f"   Reason: {sample.get('away_team')} {sample.get('away_score')} - "
          f"{sample.get('home_team')} {sample.get('home_score')}")


if __name__ == "__main__":
    backfill_test_alert()