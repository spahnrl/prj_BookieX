# Project Structure & Domain Isolation

## Goal

Strict isolation of NBA and NCAAM data into parallel directories so no "domain drift" occurs. All NBA artifacts live under `data/nba/`; all NCAAM artifacts under `data/ncaam/`.

## Target Layout

```
data/
  nba/
    raw/          # odds_master_nba.json, nba_schedule.json, nba_team_map.json
    processed/    # boxscores_nba.csv, nba_betlines_flattened.json
    view/         # final_game_view.json, nba_games_game_level*.json, nba_games_canonical*.csv
    daily/        # daily_view_*.json
  ncaam/
    raw/          # ncaam_schedule_raw*, ncaam_team_map.csv, odds_master_ncaam.json
    interim/      # ncaam_boxscores_raw.json, ncaam_schedule_mapped.csv
    canonical/    # ncaam_canonical_games.csv, ncaam_game_level.csv
    processed/    # boxscores_ncaam.csv
    view/         # final_game_view_ncaam.json, final_game_view_ncaam_active.json
    market/       # raw/, flat/, audit/ (odds)
    model/        # ncaam_canonical_games_with_lines.json, ncaam_games_multi_model_v1.json
    daily/
```

## Authority Paths

| League | Final view JSON | Final view CSV |
|--------|-----------------|----------------|
| NBA    | `data/nba/view/final_game_view.json` | `data/nba/view/final_game_view.csv` |
| NCAAM  | `data/ncaam/view/final_game_view_ncaam.json` | `data/ncaam/view/final_game_view_ncaam.csv` |

## Naming Standardization

- **Boxscores:** `boxscores_nba.csv` (in `data/nba/processed/`), `boxscores_ncaam.csv` (in `data/ncaam/processed/`).
- **Odds master:** `odds_master_nba.json` (in `data/nba/raw/`), `odds_master_ncaam.json` (in `data/ncaam/raw/`).
- **Final view:** `final_game_view.json` (NBA), `final_game_view_ncaam.json` (NCAAM) in each league’s `view/` folder.

## Scripts Updated

1. **configs/league_nba.py** (new) – NBA paths: `data/nba/{raw,processed,view,daily}` and artifact names.
2. **configs/league_ncaam.py** – Added `VIEW_DIR`; `ensure_ncaam_dirs()` creates `view/`.
3. **utils/io_helpers.py** – All league paths go through configs; NBA uses `league_nba`, NCAAM uses `league_ncaam`. Added `get_odds_master_path(league)`. NBA read fallbacks: `data/view/` and `data/derived/` when `data/nba/` files are missing.
4. **f_gen_041_add_betting_lines.py** – NBA uses `_nba_paths()` from `league_nba` (games_in, odds_master, odds_in, csv_out); calls `ensure_nba_dirs()`.
5. **eng/daily/build_daily_view.py** – Uses `get_final_view_json_path("nba")` and `get_daily_view_output_dir("nba")` instead of hardcoded `data/view` and `data/daily`.
6. **eng/backtest_runner.py** – Uses `get_final_view_json_path("nba")` for input (NBA backtest).
7. **eng/models/model_gen_0052_add_model.py** – Already uses `io_helpers.get_final_view_*` and `get_model_runner_output_*`; no change. Writes NCAAM final view to `data/ncaam/view/` via io_helpers.

## One-Time Migration (Optional)

To fully move existing files into the new layout:

1. Create directories: `data/nba/raw`, `data/nba/processed`, `data/nba/view`, `data/nba/daily`, `data/ncaam/view`.
2. **NBA:** Copy (or move) from `data/view/` into `data/nba/view/`: `final_game_view.json`, `final_game_view.csv`, `nba_games_game_level*.json`, `nba_games_canonical*.json`, `nba_games_multi_model_v1.*`, `nba_games_game_level_with_odds.*`. Copy from `data/derived/`: `nba_betlines_flattened.*` → `data/nba/processed/`; optionally `nba_games_joined.json` etc. Copy from `data/external/`: `odds_api_raw.json` → `data/nba/raw/odds_master_nba.json`.
3. **NCAAM:** Copy (or move) from `data/ncaam/processed/`: `final_game_view_ncaam.json`, `final_game_view_ncaam.csv`, `final_game_view_ncaam_active.json` → `data/ncaam/view/`.

Until migration is done, NBA continues to read from `data/view/` and `data/derived/` when `data/nba/` files are missing (see io_helpers fallbacks). NCAAM reads from `data/ncaam/view/` if present, else `data/ncaam/processed/` for the final view.

## Validation

- **No NBA script reads from `data/ncaam/`.** Grep of the codebase shows no NBA-only script references `data/ncaam/`; only NCAAM scripts, shared utils, or dual-league tools do.
- All NBA final-view and game-state reads go through `utils.io_helpers.get_final_view_json_path("nba")` and `get_game_state_path("nba")`, which resolve to `data/nba/view/` with fallback to `data/view/`.
- All NCAAM final-view reads use `get_final_view_json_path("ncaam")` → `data/ncaam/view/` (with fallback to `data/ncaam/processed/`).
