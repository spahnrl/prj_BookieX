"""
utils/io_helpers.py

Shared loading/saving for game-state JSON used by both NBA and NCAAM.

Design:
- Forward-only: only reads/writes files; no pipeline order logic.
- No circular dependency: configs do not import utils; utils may import configs.
- Standardized interface: load_game_state(league) returns a list of game dicts
  (JSON-aligned structure). save_game_state(league, games) writes the same.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_LEAGUES = ("nba", "ncaam", "wnba", "nhl")


def _normalize_league(league: str) -> str:
    league = (league or "").strip().lower()
    if league not in SUPPORTED_LEAGUES:
        raise ValueError(f"Unknown league: {league!r}. Use one of: {', '.join(SUPPORTED_LEAGUES)}.")
    return league


def _league_paths(league: str) -> dict[str, Path | None]:
    league = _normalize_league(league)
    if league == "nba":
        from configs.leagues import league_nba as cfg
        return {
            "game_state": cfg.GAME_STATE_PATH,
            "boxscore": cfg.BOXSCORES_TEAM_JSON_PATH,
            "schedule_raw": cfg.RAW_DIR / "nba_schedule.json",
            "schedule_joined": cfg.SCHEDULE_JOINED_PATH,
            "team_map": cfg.RAW_DIR / "nba_team_map.json",
            "canonical_csv": cfg.CANONICAL_CSV_PATH,
            "canonical_json": cfg.CANONICAL_JSON_PATH,
            "game_level_json": cfg.GAME_LEVEL_JSON_PATH,
            "game_level_csv": cfg.GAME_LEVEL_CSV_PATH,
            "model_json": cfg.MULTI_MODEL_JSON_PATH,
            "model_csv": cfg.MULTI_MODEL_CSV_PATH,
            "final_json": cfg.FINAL_VIEW_JSON_PATH,
            "final_csv": cfg.FINAL_VIEW_CSV_PATH,
            "active_final_json": None,
            "daily_dir": cfg.DAILY_DIR,
            "backtest_dir": PROJECT_ROOT / "data" / league / "backtests",
            "odds_master": cfg.ODDS_MASTER_PATH,
            "odds_raw_latest": None,
            "odds_raw_accum": PROJECT_ROOT / "data" / "external" / "odds_api_raw.json",
        }
    if league == "ncaam":
        from configs.leagues import league_ncaam as cfg
        data_root = getattr(cfg, "DATA_ROOT", PROJECT_ROOT / "data" / "ncaam")
        raw_dir = getattr(cfg, "RAW_DIR", data_root / "raw")
        interim_dir = getattr(cfg, "INTERIM_DIR", data_root / "interim")
        canonical_dir = getattr(cfg, "CANONICAL_DIR", data_root / "canonical")
        model_dir = getattr(cfg, "MODEL_DIR", data_root / "model")
        view_dir = getattr(cfg, "VIEW_DIR", data_root / "view")
        daily_dir = getattr(cfg, "DAILY_DIR", data_root / "daily")
        backtest_dir = getattr(cfg, "BACKTEST_DIR", data_root / "backtests")
        odds_raw_latest = getattr(
            cfg,
            "ODDS_RAW_LATEST_PATH",
            raw_dir / "ncaam_odds_latest.json",
        )
        odds_raw_accum = getattr(
            cfg,
            "ODDS_RAW_ACCUM_PATH",
            raw_dir / "ncaam_odds_api_raw.json",
        )
        return {
            "game_state": model_dir / "ncaam_canonical_games_with_lines.json",
            "boxscore": interim_dir / "ncaam_boxscores_raw.json",
            "schedule_raw": raw_dir / "ncaam_schedule_raw.json",
            "schedule_joined": interim_dir / "ncaam_schedule_mapped.json",
            "team_map": raw_dir / "ncaam_team_map.csv",
            "canonical_csv": getattr(cfg, "CANONICAL_GAMES_PATH", canonical_dir / "ncaam_canonical_games.csv"),
            "canonical_json": None,
            "game_level_json": None,
            "game_level_csv": getattr(cfg, "GAME_LEVEL_PATH", canonical_dir / "ncaam_game_level.csv"),
            "model_json": model_dir / "ncaam_games_multi_model_v1.json",
            "model_csv": model_dir / "ncaam_games_multi_model_v1.csv",
            "final_json": view_dir / "final_game_view_ncaam.json",
            "final_csv": view_dir / "final_game_view_ncaam.csv",
            "active_final_json": view_dir / "final_game_view_ncaam_active.json",
            "daily_dir": daily_dir,
            "backtest_dir": backtest_dir,
            "odds_master": raw_dir / "odds_master_ncaam.json",
            "odds_raw_latest": odds_raw_latest,
            "odds_raw_accum": odds_raw_accum,
        }
    if league == "wnba":
        from configs.leagues import league_wnba as cfg
    else:
        from configs.leagues import league_nhl as cfg
    return {
        "game_state": cfg.GAME_STATE_PATH,
        "boxscore": cfg.BOXSCORES_RAW_PATH,
        "schedule_raw": cfg.SCHEDULE_RAW_PATH,
        "schedule_joined": cfg.SCHEDULE_MAPPED_PATH,
        "team_map": cfg.TEAM_MAP_PATH,
        "canonical_csv": cfg.CANONICAL_GAMES_PATH,
        "canonical_json": cfg.CANONICAL_JSON_PATH,
        "game_level_json": cfg.GAME_LEVEL_JSON_PATH,
        "game_level_csv": cfg.GAME_LEVEL_PATH,
        "model_json": cfg.MULTI_MODEL_JSON_PATH,
        "model_csv": cfg.MULTI_MODEL_CSV_PATH,
        "final_json": cfg.FINAL_VIEW_JSON_PATH,
        "final_csv": cfg.FINAL_VIEW_CSV_PATH,
        "active_final_json": cfg.FINAL_VIEW_ACTIVE_JSON_PATH,
        "daily_dir": cfg.DAILY_DIR,
        "backtest_dir": cfg.BACKTEST_DIR,
        "odds_master": cfg.ODDS_MASTER_PATH,
        "odds_raw_latest": cfg.ODDS_RAW_LATEST_PATH,
        "odds_raw_accum": cfg.ODDS_RAW_ACCUM_PATH,
    }


def get_game_state_path(league: str) -> Path:
    """
    Path to the canonical game-state-with-odds JSON for the given league.
    NBA: data/nba/view/; NCAAM: data/ncaam/model/.
    """
    return _league_paths(league)["game_state"]


def load_game_state(league: str) -> list[dict]:
    """
    Load the game-state JSON for the given league. Returns a list of game dicts
    (JSON-aligned). Raises FileNotFoundError if the file does not exist.
    """
    path = get_game_state_path(league)
    if not path.exists():
        raise FileNotFoundError(f"Game state file not found: {path}")

    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Game state JSON must be a list of game objects: {path}")
    return data


def save_game_state(league: str, games: list[dict]) -> Path:
    """
    Save the game-state JSON for the given league. Creates parent dirs if needed.
    Returns the path written.
    """
    import json
    path = get_game_state_path(league)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(games, f, indent=2)
    return path


def load_previous_game_state_by_id(league: str, game_id_key: str = "game_id") -> dict[str, dict]:
    """
    Load previous run's game-state JSON (if it exists) and return a dict keyed by game id.
    Used for odds drift tracking and finalized protection. Returns {} if file missing.
    game_id_key: key to use as unique game id ('game_id' for NBA; for NCAAM use
    ``canonical_game_id`` unless the caller has standardized on ``game_id``).
    """
    path = get_game_state_path(league)
    if not path.exists():
        return {}

    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return {}

    by_id = {}
    for row in data:
        gid = (row.get(game_id_key) or "").strip() if isinstance(row, dict) else ""
        if gid:
            by_id[gid] = row
    return by_id


# -----------------------------------------------------------------------------
# Boxscore raw (b_data_004 / b_gen_004 output) — league-agnostic, JSON-first
# -----------------------------------------------------------------------------

def get_boxscore_path(league: str) -> Path:
    """Path to boxscore JSON (primary artifact). NBA: data/nba/processed; NCAAM: data/ncaam/interim."""
    return _league_paths(league)["boxscore"]


def save_boxscores(league: str, boxscore_rows: list[dict]) -> Path:
    """Save boxscore list as JSON. Creates parent dirs. Returns path written."""
    import json
    path = get_boxscore_path(league)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(boxscore_rows, f, indent=2)
    return path


def load_previous_boxscores_by_id(league: str, id_key: str) -> dict[str, dict]:
    """
    Load previous boxscores JSON (if exists). Return dict keyed by id_key.
    Used for finalized protection: do not re-fetch or overwrite final boxscores.
    id_key: 'game_id' for NBA, 'espn_game_id' for NCAAM.
    Returns {} if file missing.
    """
    path = get_boxscore_path(league)
    if not path.exists():
        return {}

    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return {}

    by_id = {}
    for row in data:
        gid = (row.get(id_key) or "").strip() if isinstance(row, dict) else ""
        if isinstance(gid, (int, float)):
            gid = str(gid).strip()
        if gid:
            by_id[gid] = row
    return by_id


# NCAAM aliases (backward compat for d_ncaam_021, etc.)
def get_ncaam_boxscore_raw_path() -> Path:
    """Path to NCAAM raw boxscores JSON (primary artifact from b_data_004)."""
    return get_boxscore_path("ncaam")


def save_ncaam_boxscores(boxscore_rows: list[dict]) -> Path:
    """Save NCAAM boxscore list as JSON. Creates parent dirs. Returns path written."""
    return save_boxscores("ncaam", boxscore_rows)


def load_previous_ncaam_boxscores_by_id(id_key: str = "espn_game_id") -> dict[str, dict]:
    """Load previous NCAAM boxscores by id_key. Returns {} if file missing."""
    return load_previous_boxscores_by_id("ncaam", id_key)


# -----------------------------------------------------------------------------
# Schedule (b_data_001 / b_gen_001 output, b_data_003 / b_gen_003 input)
# -----------------------------------------------------------------------------

def get_schedule_raw_path(league: str) -> Path:
    """Path to raw/normalized schedule JSON (output of 001)."""
    return _league_paths(league)["schedule_raw"]


def get_schedule_joined_path(league: str) -> Path:
    """Path to joined/mapped schedule JSON (output of 003)."""
    return _league_paths(league)["schedule_joined"]


def save_schedule_raw(league: str, rows: list[dict]) -> Path:
    """Save normalized schedule (001 output) as JSON. Creates parent dirs."""
    import json
    path = get_schedule_raw_path(league)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    return path


def load_schedule_raw(league: str) -> list[dict]:
    """Load normalized schedule JSON (001 output). Raises if missing."""
    import json
    path = get_schedule_raw_path(league)
    if not path.exists():
        raise FileNotFoundError(f"Schedule raw file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Schedule JSON must be a list: {path}")
    return data


def save_schedule_joined(league: str, rows: list[dict]) -> Path:
    """Save joined/mapped schedule (003 output) as JSON. Creates parent dirs."""
    import json
    path = get_schedule_joined_path(league)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    return path


def get_team_map_path(league: str) -> Path:
    """Path to team map. NBA: data/nba/raw (fallback data/raw, data/static); NCAAM: data/ncaam/raw."""
    league = _normalize_league(league)
    if league == "nba":
        from configs.leagues.league_nba import RAW_DIR
        primary = RAW_DIR / "nba_team_map.json"
        if primary.exists():
            return primary
        for fallback in (PROJECT_ROOT / "data" / "raw" / "nba_team_map.json", PROJECT_ROOT / "data" / "static" / "nba_team_map.json"):
            if fallback.exists():
                return fallback
        return primary
    return _league_paths(league)["team_map"]


def load_schedule_joined(league: str) -> list[dict]:
    """Load joined/mapped schedule (003 output) from JSON. Raises if missing."""
    import json
    path = get_schedule_joined_path(league)
    if not path.exists():
        raise FileNotFoundError(f"Schedule joined file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Schedule joined JSON must be a list: {path}")
    return data


def load_boxscores(league: str) -> list[dict]:
    """Load boxscore list (004 output) from JSON. Raises if missing."""
    import json
    path = get_boxscore_path(league)
    if not path.exists():
        raise FileNotFoundError(f"Boxscore file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Boxscore JSON must be a list: {path}")
    return data


# -----------------------------------------------------------------------------
# Canonical games (d_021 output) — paths only; output must match for model runners
# -----------------------------------------------------------------------------

def get_canonical_games_csv_path(league: str) -> Path:
    """Path to canonical games CSV. NBA: data/nba/view; NCAAM: data/ncaam/canonical."""
    return _league_paths(league)["canonical_csv"]


def get_canonical_games_json_path(league: str) -> Path | None:
    """Path to canonical games JSON. NBA only; NCAAM returns None (CSV-only)."""
    return _league_paths(league)["canonical_json"]


def get_game_level_json_path(league: str) -> Path | None:
    """Path to game-level JSON (022 output). NBA only; NCAAM returns None (CSV-only)."""
    return _league_paths(league)["game_level_json"]


def get_game_level_csv_path(league: str) -> Path:
    """Path to game-level CSV (022 output). NBA: data/nba/view; NCAAM: data/ncaam/canonical."""
    return _league_paths(league)["game_level_csv"]


# -----------------------------------------------------------------------------
# Model runner 0051 output (multi-model projections) — JSON + CSV for UI/backtest
# -----------------------------------------------------------------------------

def get_model_runner_output_json_path(league: str) -> Path:
    """Path to multi-model runner JSON (0051 output). NBA: data/nba/view; NCAAM: data/ncaam/model."""
    return _league_paths(league)["model_json"]


def get_model_runner_output_csv_path(league: str) -> Path:
    """Path to multi-model runner CSV (0051 output)."""
    return _league_paths(league)["model_csv"]


# -----------------------------------------------------------------------------
# Final view (0052 output) — JSON/CSV for UI
# -----------------------------------------------------------------------------

def get_final_view_json_path(league: str) -> Path:
    """Path to final game view JSON (0052 output). NBA: data/nba/view; NCAAM: data/ncaam/view."""
    league = _normalize_league(league)
    if league == "ncaam":
        from configs.leagues.league_ncaam import VIEW_DIR
        primary = VIEW_DIR / "final_game_view_ncaam.json"
        fallback = PROJECT_ROOT / "data" / "ncaam" / "processed" / "final_game_view_ncaam.json"
        return primary if primary.exists() else fallback
    return _league_paths(league)["final_json"]


def get_final_view_csv_path(league: str) -> Path:
    """Path to final game view CSV (0052 output). Writes to league view dir; reads with fallback."""
    return _league_paths(league)["final_csv"]


def get_final_view_active_json_path(league: str) -> Path | None:
    """Path to final active games JSON (0052). NCAAM only; NBA returns None."""
    return _league_paths(league)["active_final_json"]


def get_daily_view_output_dir(league: str) -> Path:
    """Directory for daily view JSON/CSV output (build_daily_view).

    Canonical daily roots: data/nba/daily (NBA), data/ncaam/daily (NCAAM).
    data/daily is legacy and must not be used by active code.
    """
    return _league_paths(league)["daily_dir"]


def get_backtest_output_root(league: str) -> Path:
    """Root directory for backtest runs (backtest_gen_runner). data/{league}/backtests/."""
    return _league_paths(league)["backtest_dir"]


def get_odds_master_path(league: str) -> Path:
    """Path to odds master JSON. NBA: data/nba/raw/odds_master_nba.json; NCAAM: data/ncaam/raw/odds_master_ncaam.json."""
    return _league_paths(league)["odds_master"]


def get_odds_raw_latest_path(league: str) -> Path | None:
    """Path to the latest raw Odds API snapshot where the league has one."""
    return _league_paths(league)["odds_raw_latest"]


def get_odds_raw_accum_path(league: str) -> Path:
    """Path to the append-only raw Odds API snapshot list."""
    return _league_paths(league)["odds_raw_accum"]


def get_timestamped_odds_raw_path(league: str, ts_label: str) -> Path | None:
    """Path to a timestamped raw Odds API snapshot where the league has that artifact."""
    league = _normalize_league(league)
    if league == "nba":
        return None
    if league == "ncaam":
        from configs.leagues.league_ncaam import timestamped_odds_raw_path
        return timestamped_odds_raw_path(ts_label)
    if league == "wnba":
        from configs.leagues.league_wnba import timestamped_odds_raw_path
        return timestamped_odds_raw_path(ts_label)
    from configs.leagues.league_nhl import timestamped_odds_raw_path
    return timestamped_odds_raw_path(ts_label)
