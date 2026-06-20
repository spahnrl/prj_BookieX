"""
configs/leagues/league_mlb.py

MLB data paths. This file is path/config support only; it does not fetch,
model, backtest, or generate daily artifacts.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

LEAGUE_CODE = "mlb"
SEASON = "2026"

DATA_ROOT = PROJECT_ROOT / "data" / LEAGUE_CODE
RAW_DIR = DATA_ROOT / "raw"
DERIVED_DIR = DATA_ROOT / "derived"
INTERIM_DIR = DATA_ROOT / "interim"
CANONICAL_DIR = DATA_ROOT / "canonical"
PROCESSED_DIR = DATA_ROOT / "processed"
VIEW_DIR = DATA_ROOT / "view"
MARKET_DIR = DATA_ROOT / "market"
MODEL_DIR = DATA_ROOT / "model"
BACKTEST_DIR = DATA_ROOT / "backtests"
DAILY_DIR = DATA_ROOT / "daily"
CALIBRATION_DIR = DATA_ROOT / "calibration"

CALIBRATION_SNAPSHOT_PATH = CALIBRATION_DIR / "calibration_snapshot_mlb_v1.json"

MARKET_FLAT_DIR = MARKET_DIR / "flat"
MARKET_AUDIT_DIR = MARKET_DIR / "audit"
ODDS_SNAPSHOT_DIR = RAW_DIR
MARKET_RAW_DIR = ODDS_SNAPSHOT_DIR

TEAM_MAP_PATH = RAW_DIR / "mlb_team_map.csv"
SCHEDULE_RAW_PATH = RAW_DIR / "mlb_schedule_raw.json"
SCHEDULE_RAW_CSV_PATH = RAW_DIR / "mlb_schedule_raw.csv"
SCHEDULE_MAPPED_PATH = INTERIM_DIR / "mlb_schedule_mapped.json"
BOXSCORES_RAW_PATH = INTERIM_DIR / "mlb_boxscores_raw.json"
BOXSCORES_CLEAN_PATH = INTERIM_DIR / "mlb_boxscores_clean.csv"

CANONICAL_GAMES_PATH = CANONICAL_DIR / "mlb_canonical_games.csv"
CANONICAL_JSON_PATH = CANONICAL_DIR / "mlb_canonical_games.json"
GAME_LEVEL_PATH = CANONICAL_DIR / "mlb_game_level.csv"
GAME_LEVEL_JSON_PATH = CANONICAL_DIR / "mlb_game_level.json"
GAME_STATE_PATH = MODEL_DIR / "mlb_canonical_games_with_lines.json"

ODDS_MASTER_PATH = RAW_DIR / "odds_master_mlb.json"
ODDS_RAW_LATEST_PATH = ODDS_SNAPSHOT_DIR / "mlb_odds_latest.json"
ODDS_RAW_ACCUM_PATH = ODDS_SNAPSHOT_DIR / "mlb_odds_api_raw.json"
BETLINES_FLATTENED_CSV_PATH = DERIVED_DIR / "mlb_betlines_flattened.csv"
BETLINES_FLATTENED_JSON_PATH = DERIVED_DIR / "mlb_betlines_flattened.json"
ODDS_FLAT_LATEST_PATH = BETLINES_FLATTENED_CSV_PATH
ODDS_UNMATCHED_TEAMS_PATH = MARKET_AUDIT_DIR / "mlb_odds_unmatched_teams.csv"

MULTI_MODEL_JSON_PATH = MODEL_DIR / "mlb_games_multi_model_v1.json"
MULTI_MODEL_CSV_PATH = MODEL_DIR / "mlb_games_multi_model_v1.csv"
FINAL_VIEW_JSON_PATH = VIEW_DIR / "final_game_view_mlb.json"
FINAL_VIEW_CSV_PATH = VIEW_DIR / "final_game_view_mlb.csv"
FINAL_VIEW_ACTIVE_JSON_PATH = VIEW_DIR / "final_game_view_mlb_active.json"


def ensure_mlb_dirs() -> None:
    for path in [
        DATA_ROOT,
        RAW_DIR,
        DERIVED_DIR,
        INTERIM_DIR,
        CANONICAL_DIR,
        PROCESSED_DIR,
        VIEW_DIR,
        MARKET_DIR,
        MODEL_DIR,
        BACKTEST_DIR,
        DAILY_DIR,
        CALIBRATION_DIR,
        ODDS_SNAPSHOT_DIR,
        MARKET_FLAT_DIR,
        MARKET_AUDIT_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def timestamped_odds_raw_path(ts_label: str) -> Path:
    return ODDS_SNAPSHOT_DIR / f"mlb_odds_raw_{ts_label}.json"


def timestamped_odds_flat_path(ts_label: str) -> Path:
    return DERIVED_DIR / f"mlb_betlines_flattened_{ts_label}.csv"


def get_mlb_config() -> dict:
    ensure_mlb_dirs()
    return {
        "league_code": LEAGUE_CODE,
        "season": SEASON,
        "data_root": str(DATA_ROOT),
        "derived_dir": str(DERIVED_DIR),
        "odds_snapshot_dir": str(ODDS_SNAPSHOT_DIR),
        "market_raw_dir": str(MARKET_RAW_DIR),
        "market_flat_dir": str(MARKET_FLAT_DIR),
        "market_audit_dir": str(MARKET_AUDIT_DIR),
        "betlines_flattened_csv": str(BETLINES_FLATTENED_CSV_PATH),
        "betlines_flattened_json": str(BETLINES_FLATTENED_JSON_PATH),
        "odds_raw_latest_path": str(ODDS_RAW_LATEST_PATH),
        "odds_raw_accum_path": str(ODDS_RAW_ACCUM_PATH),
        "odds_flat_latest_path": str(ODDS_FLAT_LATEST_PATH),
    }
