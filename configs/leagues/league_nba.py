"""
configs/leagues/league_nba.py

NBA data paths: parallel to league_ncaam under data/nba/.
Domain isolation: all NBA artifacts under data/nba/{raw,processed,view,derived}.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

LEAGUE_CODE = "nba"

DATA_ROOT = PROJECT_ROOT / "data" / LEAGUE_CODE
RAW_DIR = DATA_ROOT / "raw"
PROCESSED_DIR = DATA_ROOT / "processed"
VIEW_DIR = DATA_ROOT / "view"
# NBA daily output is canonical under data/nba/daily. Legacy data/daily is not part of the active contract.
DAILY_DIR = DATA_ROOT / "daily"
CALIBRATION_DIR = DATA_ROOT / "calibration"
CALIBRATION_SNAPSHOT_PATH = CALIBRATION_DIR / "calibration_snapshot_v1.json"

# Derived: league-scoped root. All NBA derived artifacts live here.
DERIVED_DIR = PROJECT_ROOT / "data" / "nba" / "derived"
SCHEDULE_JOINED_PATH = DERIVED_DIR / "nba_games_joined.json"
BOXSCORES_TEAM_JSON_PATH = DERIVED_DIR / "nba_boxscores_team.json"
BOXSCORES_TEAM_CSV_PATH = DERIVED_DIR / "nba_boxscores_team.csv"

# Standardized artifact names ({type}_{league})
ODDS_MASTER_PATH = RAW_DIR / "odds_master_nba.json"
GAME_STATE_PATH = VIEW_DIR / "nba_games_game_level_with_odds.json"
CANONICAL_CSV_PATH = VIEW_DIR / "nba_games_canonical.csv"
CANONICAL_JSON_PATH = PROCESSED_DIR / "nba_games_canonical.json"
GAME_LEVEL_CSV_PATH = VIEW_DIR / "nba_games_game_level.csv"
GAME_LEVEL_JSON_PATH = VIEW_DIR / "nba_games_game_level.json"
FINAL_VIEW_JSON_PATH = VIEW_DIR / "final_game_view.json"
FINAL_VIEW_CSV_PATH = VIEW_DIR / "final_game_view.csv"
MULTI_MODEL_JSON_PATH = VIEW_DIR / "nba_games_multi_model_v1.json"
MULTI_MODEL_CSV_PATH = VIEW_DIR / "nba_games_multi_model_v1.csv"
BETLINES_FLATTENED_JSON_PATH = DERIVED_DIR / "nba_betlines_flattened.json"
BETLINES_FLATTENED_CSV_PATH = DERIVED_DIR / "nba_betlines_flattened.csv"


def ensure_nba_dirs() -> None:
    for path in [DATA_ROOT, RAW_DIR, PROCESSED_DIR, VIEW_DIR, DAILY_DIR, CALIBRATION_DIR, DERIVED_DIR]:
        path.mkdir(parents=True, exist_ok=True)
