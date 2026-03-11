from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

LEAGUE_CODE = "ncaam"
SEASON = "2025-2026"

DATA_ROOT = PROJECT_ROOT / "data" / LEAGUE_CODE
RAW_DIR = DATA_ROOT / "raw"
INTERIM_DIR = DATA_ROOT / "interim"
CANONICAL_DIR = DATA_ROOT / "canonical"
PROCESSED_DIR = DATA_ROOT / "processed"
VIEW_DIR = DATA_ROOT / "view"
MARKET_DIR = DATA_ROOT / "market"
MODEL_DIR = DATA_ROOT / "model"
BACKTEST_DIR = DATA_ROOT / "backtests"
# NCAAM daily output is canonical under data/ncaam/daily.
DAILY_DIR = DATA_ROOT / "daily"
CALIBRATION_DIR = DATA_ROOT / "calibration"
CALIBRATION_SNAPSHOT_PATH = CALIBRATION_DIR / "calibration_snapshot_ncaam_v1.json"

# Processed artifacts (051-style boxscores, 052 final view)
BOXSCORES_PROCESSED_PATH = PROCESSED_DIR / "boxscores_ncaam.csv"

MARKET_RAW_DIR = MARKET_DIR / "raw"
MARKET_FLAT_DIR = MARKET_DIR / "flat"
MARKET_AUDIT_DIR = MARKET_DIR / "audit"

TEAM_MAP_PATH = RAW_DIR / "ncaam_team_map.csv"
SCHEDULE_RAW_PATH = RAW_DIR / "ncaam_schedule_raw.csv"
SCHEDULE_RAW_JSON_PATH = RAW_DIR / "ncaam_schedule_raw.json"
SCHEDULE_MAPPED_PATH = INTERIM_DIR / "ncaam_schedule_mapped.csv"
BOXSCORES_RAW_PATH = RAW_DIR / "ncaam_boxscores_raw.csv"
BOXSCORES_CLEAN_PATH = INTERIM_DIR / "ncaam_boxscores_clean.csv"
CANONICAL_GAMES_PATH = CANONICAL_DIR / "ncaam_canonical_games.csv"
GAME_LEVEL_PATH = CANONICAL_DIR / "ncaam_game_level.csv"

ODDS_RAW_LATEST_PATH = MARKET_RAW_DIR / "ncaam_odds_latest.json"
ODDS_FLAT_LATEST_PATH = MARKET_FLAT_DIR / "ncaam_odds_flat_latest.csv"
ODDS_UNMATCHED_TEAMS_PATH = MARKET_AUDIT_DIR / "ncaam_odds_unmatched_teams.csv"


def ensure_ncaam_dirs() -> None:
    for path in [
        DATA_ROOT,
        RAW_DIR,
        INTERIM_DIR,
        CANONICAL_DIR,
        PROCESSED_DIR,
        VIEW_DIR,
        MARKET_DIR,
        MODEL_DIR,
        BACKTEST_DIR,
        DAILY_DIR,
        CALIBRATION_DIR,
        MARKET_RAW_DIR,
        MARKET_FLAT_DIR,
        MARKET_AUDIT_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def timestamped_odds_raw_path(ts_label: str):
    return MARKET_RAW_DIR / f"ncaam_odds_raw_{ts_label}.json"


def timestamped_odds_flat_path(ts_label: str):
    return MARKET_FLAT_DIR / f"ncaam_odds_flat_{ts_label}.csv"


def get_ncaam_config() -> dict:
    ensure_ncaam_dirs()
    return {
        "league_code": LEAGUE_CODE,
        "season": SEASON,
        "data_root": str(DATA_ROOT),
        "market_raw_dir": str(MARKET_RAW_DIR),
        "market_flat_dir": str(MARKET_FLAT_DIR),
        "market_audit_dir": str(MARKET_AUDIT_DIR),
        "odds_raw_latest_path": str(ODDS_RAW_LATEST_PATH),
        "odds_flat_latest_path": str(ODDS_FLAT_LATEST_PATH),
    }


if __name__ == "__main__":
    cfg = get_ncaam_config()
    for k, v in cfg.items():
        print(f"{k}: {v}")
