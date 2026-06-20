from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

LEAGUE_CODE = "ncaam"
SEASON = "2025-2026"

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
# NCAAM daily output is canonical under data/ncaam/daily.
DAILY_DIR = DATA_ROOT / "daily"
CALIBRATION_DIR = DATA_ROOT / "calibration"
CALIBRATION_SNAPSHOT_PATH = CALIBRATION_DIR / "calibration_snapshot_ncaam_v1.json"

# Processed artifacts (051-style boxscores, 052 final view)
BOXSCORES_PROCESSED_PATH = PROCESSED_DIR / "boxscores_ncaam.csv"

MARKET_FLAT_DIR = MARKET_DIR / "flat"
MARKET_AUDIT_DIR = MARKET_DIR / "audit"
# Pre-derived-layout flat CSV (032 output before data/ncaam/derived); 041 falls back if derived missing
NCAAM_LEGACY_ODDS_FLAT_CSV_PATH = MARKET_FLAT_DIR / "ncaam_odds_flat_latest.csv"

# Flattened Odds API lines (parallel to NBA: data/nba/derived/nba_betlines_flattened.*)
BETLINES_FLATTENED_CSV_PATH = DERIVED_DIR / "ncaam_betlines_flattened.csv"
BETLINES_FLATTENED_JSON_PATH = DERIVED_DIR / "ncaam_betlines_flattened.json"
# Legacy constant name used in 032/041; same path as BETLINES_FLATTENED_CSV_PATH
ODDS_FLAT_LATEST_PATH = BETLINES_FLATTENED_CSV_PATH

# Odds API JSON (latest, accum, ncaam_odds_raw_*): under league RAW_DIR (NBA-style: data/ncaam/raw).
ODDS_SNAPSHOT_DIR = RAW_DIR
# Older layout; still read for timestamped files and accum migration.
LEGACY_NCAAM_MARKET_RAW_DIR = MARKET_DIR / "raw"
# Backward-compatible alias (canonical odds snapshot directory).
MARKET_RAW_DIR = ODDS_SNAPSHOT_DIR

TEAM_MAP_PATH = RAW_DIR / "ncaam_team_map.csv"
SCHEDULE_RAW_PATH = RAW_DIR / "ncaam_schedule_raw.csv"
SCHEDULE_RAW_JSON_PATH = RAW_DIR / "ncaam_schedule_raw.json"
SCHEDULE_MAPPED_PATH = INTERIM_DIR / "ncaam_schedule_mapped.csv"
BOXSCORES_RAW_PATH = RAW_DIR / "ncaam_boxscores_raw.csv"
BOXSCORES_CLEAN_PATH = INTERIM_DIR / "ncaam_boxscores_clean.csv"
CANONICAL_GAMES_PATH = CANONICAL_DIR / "ncaam_canonical_games.csv"
GAME_LEVEL_PATH = CANONICAL_DIR / "ncaam_game_level.csv"

ODDS_RAW_LATEST_PATH = ODDS_SNAPSHOT_DIR / "ncaam_odds_latest.json"
# NBA-parity: append-only list of snapshots (same shape as each single-snapshot dict).
ODDS_RAW_ACCUM_PATH = ODDS_SNAPSHOT_DIR / "ncaam_odds_api_raw.json"
LEGACY_ODDS_RAW_LATEST_PATH = LEGACY_NCAAM_MARKET_RAW_DIR / "ncaam_odds_latest.json"
LEGACY_ODDS_RAW_ACCUM_PATH = LEGACY_NCAAM_MARKET_RAW_DIR / "ncaam_odds_api_raw.json"
ODDS_UNMATCHED_TEAMS_PATH = MARKET_AUDIT_DIR / "ncaam_odds_unmatched_teams.csv"


def ensure_ncaam_dirs() -> None:
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
        LEGACY_NCAAM_MARKET_RAW_DIR,
        MARKET_FLAT_DIR,
        MARKET_AUDIT_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def ncaam_odds_latest_read_path() -> Path | None:
    """Prefer canonical latest JSON; else legacy path if only pre-migration files exist."""
    if ODDS_RAW_LATEST_PATH.exists():
        return ODDS_RAW_LATEST_PATH
    if LEGACY_ODDS_RAW_LATEST_PATH.exists():
        return LEGACY_ODDS_RAW_LATEST_PATH
    return None


def glob_ncaam_odds_raw_json_files() -> list[Path]:
    """All ``ncaam_odds_raw_*.json`` under canonical ``data/ncaam/raw`` and legacy ``market/raw``."""
    seen: set[Path] = set()
    ordered: list[Path] = []
    for d in (ODDS_SNAPSHOT_DIR, LEGACY_NCAAM_MARKET_RAW_DIR):
        if not d.exists():
            continue
        for p in sorted(d.glob("ncaam_odds_raw_*.json")):
            key = p.resolve()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(p)
    return ordered


def timestamped_odds_raw_path(ts_label: str):
    return ODDS_SNAPSHOT_DIR / f"ncaam_odds_raw_{ts_label}.json"


def timestamped_odds_flat_path(ts_label: str):
    return DERIVED_DIR / f"ncaam_betlines_flattened_{ts_label}.csv"


def get_ncaam_config() -> dict:
    ensure_ncaam_dirs()
    return {
        "league_code": LEAGUE_CODE,
        "season": SEASON,
        "data_root": str(DATA_ROOT),
        "derived_dir": str(DERIVED_DIR),
        "odds_snapshot_dir": str(ODDS_SNAPSHOT_DIR),
        "legacy_market_raw_dir": str(LEGACY_NCAAM_MARKET_RAW_DIR),
        "market_raw_dir": str(ODDS_SNAPSHOT_DIR),
        "market_flat_dir": str(MARKET_FLAT_DIR),
        "market_audit_dir": str(MARKET_AUDIT_DIR),
        "betlines_flattened_csv": str(BETLINES_FLATTENED_CSV_PATH),
        "betlines_flattened_json": str(BETLINES_FLATTENED_JSON_PATH),
        "odds_raw_latest_path": str(ODDS_RAW_LATEST_PATH),
        "odds_raw_accum_path": str(ODDS_RAW_ACCUM_PATH),
        "odds_flat_latest_path": str(ODDS_FLAT_LATEST_PATH),
    }


if __name__ == "__main__":
    cfg = get_ncaam_config()
    for k, v in cfg.items():
        print(f"{k}: {v}")
