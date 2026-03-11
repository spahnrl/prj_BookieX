# BookieX Repo Map

## 1. Purpose

This map is a single reference for finding pipeline entrypoints, league-specific vs shared scripts, and where key artifacts are read or written. It describes the current layout only; it does not propose renames or moves. Use it to navigate the repo and trace data flow without guessing.

---

## 2. Primary entrypoints

| Entrypoint | Role |
|------------|------|
| **000_RUN_ALL_NBA.py** | Full NBA pipeline: ingestion → features → canonical → market → models → backtest → calibration → execution overlay → daily view → analysis. |
| **000_RUN_ALL_NCAAM.py** | Full NCAAM pipeline: team map → schedule/boxscores → canonical → features → market → models → daily view → backtest. |
| **000_launch_bookiex_dashboard.py** | Launcher that runs the Streamlit dashboard (subprocess). |
| **000_bookiex_launcher_ui.py** | Operational launcher for the BookieX dashboard (alternative UI entrypoint). |
| **eng/ui/bookiex_dashboard.py** | Streamlit app: reads daily view JSON from `data/nba/daily/` and `data/ncaam/daily/`, shows games and Kelly guidance. |

---

## 3. Shared pipeline scripts

These scripts take `--league nba` or `--league ncaam` and are used by both runners.

| Script | Purpose |
|--------|---------|
| **eng/pipelines/shared/b_gen_001_ingest_schedule.py** | Ingest schedule from external source; output is league-scoped under `data/{league}/`. |
| **eng/pipelines/shared/b_gen_003_join_schedule_teams.py** | Join schedule with team identities; produces derived/joined artifact. |
| **eng/pipelines/shared/b_gen_004_ingest_boxscores.py** | Ingest boxscores; output is league-scoped. |
| **eng/pipelines/shared/d_gen_021_build_canonical_games.py** | Build canonical game rows (team-game or one per game) from schedule + boxscores + features. |
| **eng/pipelines/shared/d_gen_022_collapse_to_game_level.py** | Collapse canonical rows to one game-level row per game; writes view/processed artifacts. |
| **eng/pipelines/shared/e_gen_031_get_betline.py** | Fetch current odds from The Odds API; NBA writes to `data/external/`, NCAAM to league market/raw. |
| **eng/pipelines/shared/e_gen_032_get_betline_flatten.py** | Flatten raw odds to one row per game (NBA) or outcome-level (NCAAM); NBA reads `data/external/odds_api_raw.json`. |
| **eng/pipelines/shared/f_gen_041_add_betting_lines.py** | Join flattened odds onto game-level rows; writes game state JSON/CSV (with drift + finalized protection). |
| **eng/models/shared/model_gen_0051_runner.py** | Run league model registry over game state; writes multi-model JSON/CSV. |
| **eng/models/shared/model_gen_0052_add_model.py** | Add selection authority, confidence, execution overlay; writes final game view JSON/CSV. |
| **eng/daily/build_gen_daily_view.py** | Build daily view for dashboard; delegates to NBA or NCAAM builder; writes to `data/{league}/daily/`. |
| **eng/backtest/backtest_gen_runner.py** | Run backtest over final view; writes to `data/{league}/backtests/backtest_{timestamp}/`. |
| **eng/calibration/build_calibration_snapshot.py** | Build calibration snapshot from latest backtest; takes `--league`; writes to `eng/calibration/`. |

---

## 4. NBA-only scripts

Includes files that do not have "nba" in the filename but are used only for NBA.

| Script | Purpose |
|--------|---------|
| **eng/pipelines/nba/a_data_static_000_nba_team_map.py** | Build/refresh NBA team map. |
| **eng/pipelines/nba/b_data_005_ingest_player_boxscores.py** | Ingest player-level boxscores (NBA). |
| **eng/pipelines/nba/b_data_006_aggregate_team_3pt.py** | Aggregate team 3pt stats (NBA). |
| **eng/pipelines/nba/b_data_007_ingest_injuries.py** | Ingest injury data (NBA). |
| **eng/pipelines/nba/c_calc_010_add_team_rest_days.py** | Add rest days to games (NBA). |
| **eng/pipelines/nba/c_calc_011_flag_back_to_backs.py** | Flag back-to-backs (NBA). |
| **eng/pipelines/nba/c_calc_012_compute_fatigue_score.py** | Compute fatigue score (NBA). |
| **eng/pipelines/nba/c_calc_013_calc_rest_home_away_averages.py** | Rest/home/away averages (NBA). |
| **eng/pipelines/nba/c_calc_014_rolling_team_averages.py** | Rolling team averages (NBA). |
| **eng/pipelines/nba/c_calc_015_build_last5_momentum.py** | Last-5 momentum (NBA). |
| **eng/pipelines/nba/c_calc_020_build_team_injury_impact.py** | Team injury impact (NBA). |
| **eng/daily/build_daily_view.py** | NBA daily view builder (no "nba" in name). Invoked by `build_gen_daily_view.py --league nba`. Reads `data/nba/view/final_game_view.json` and `eng/calibration/calibration_snapshot_v1.json`; writes to `data/nba/daily/`. |
| **eng/execution/build_execution_overlay.py** | Annotate NBA final_game_view with execution overlay flags (no "nba" in name). Reads/writes `data/nba/view/final_game_view.json`. |
| **r_101_report_backtest_vegas.py** | NBA backtest report (no "nba" in name). Reads `data/nba/backtests/`; writes `data/nba/view/report_backtest_vegas.csv`. |
| **eng/analysis/analysis_001_edge_distribution.py** through **analysis_040_*** (most) | NBA-only analysis: use `configs.leagues.league_nba` and NBA paths. Only `analysis_gen_003_bias_detection.py` supports `--league`. |

---

## 5. NCAAM-only scripts

| Script | Purpose |
|--------|---------|
| **eng/pipelines/ncaam/a_data_static_000a_build_ncaam_team_map_from_ncaa.py** | Build NCAAM team map from NCAA source. |
| **eng/pipelines/ncaam/a_data_static_000b_ncaam_team_map.py** | NCAAM team map output/validation. |
| **eng/pipelines/ncaam/c_ncaam_001_build_avg_score_features.py** | Build avg-score features (NCAAM). |
| **eng/pipelines/ncaam/c_ncaam_015_build_last5_momentum.py** | Last-5 momentum (NCAAM). |
| **eng/pipelines/ncaam/c_ncaam_099_merge_model_features.py** | Merge model features into NCAAM model input. |
| **eng/daily/build_daily_view_ncaam.py** | NCAAM daily view builder. Invoked by `build_gen_daily_view.py --league ncaam`. |
| **eng/models/model_0052_add_model_ncaam.py** | NCAAM-specific adapter/wiring for 0052 (if used; otherwise 0052 shared handles both). |

---

## 6. Key artifact paths

### NBA

- **Raw/input:** `data/nba/raw/` (team map, schedule, odds_master_nba.json), `data/external/odds_api_raw.json` (031/032 for NBA).
- **Derived:** `data/nba/derived/` (nba_games_joined.json, nba_betlines_flattened.json, nba_games_with_rest.json, nba_games_with_fatigue.json, nba_team_rolling_averages.json, etc.).
- **Processed:** `data/nba/processed/nba_games_canonical.json`.
- **View:** `data/nba/view/nba_games_game_level.json`, `data/nba/view/nba_games_game_level_with_odds.json`, `data/nba/view/nba_games_multi_model_v1.json`, `data/nba/view/final_game_view.json`, `data/nba/view/final_game_view.csv`, `data/nba/view/report_backtest_vegas.csv`.
- **Daily:** `data/nba/daily/daily_view_{date}_v1.json` (and optional CSV).
- **Backtests:** `data/nba/backtests/backtest_{timestamp}/` (backtest_games.json, backtest_summary.json, etc.).

### NCAAM

- **Raw:** `data/ncaam/raw/` (ncaam_team_map.csv, ncaam_schedule_raw.*, ncaam_boxscores_raw.csv).
- **Interim:** `data/ncaam/interim/` (schedule_mapped, boxscores_clean, etc.).
- **Canonical:** `data/ncaam/canonical/` (ncaam_canonical_games.csv, ncaam_game_level.csv).
- **Processed:** `data/ncaam/processed/` (boxscores_ncaam.csv, etc.).
- **Market:** `data/ncaam/market/raw/`, `data/ncaam/market/flat/` (odds raw/flat files).
- **Model:** `data/ncaam/model/` (ncaam_model_input_v1.csv, ncaam_games_multi_model_v1.json, ncaam_canonical_games_with_lines.json).
- **View:** `data/ncaam/view/` (final_game_view_ncaam.json, final_game_view_ncaam.csv, final_game_view_ncaam_active.json).
- **Daily:** `data/ncaam/daily/daily_view_ncaam_{date}_v1.json` (and optional CSV).
- **Backtests:** `data/ncaam/backtests/backtest_{timestamp}/`.

### Shared / external

- **data/external/** — Used by NBA odds: `odds_api_raw.json` (031 write, 032 read), `odds_api_current.csv` (031). Not under a league folder.
- **configs/leagues/league_nba.py**, **configs/leagues/league_ncaam.py** — League path and artifact definitions; no artifact output in configs.

### Artifacts still under eng/

- **eng/calibration/** — `calibration_snapshot_v1.json` (NBA), `calibration_snapshot_ncaam_v1.json` (NCAAM). Written by `eng/calibration/build_calibration_snapshot.py`. Read by `eng/daily/build_daily_view.py` (NBA) for calibration percentiles.
- **eng/outputs/analysis/** — Used by some analysis/gen scripts (e.g. bias_report_{league}.json). Analysis scripts also reference `eng/outputs/backtests` in many places (see Section 8).

---

## 7. Current naming inconsistencies

- **Final view filename:** NBA uses `final_game_view.json` / `final_game_view.csv` (no league in name). NCAAM uses `final_game_view_ncaam.json` / `final_game_view_ncaam.csv`.
- **Daily view filename:** NBA uses `daily_view_{date}_v1.json`. NCAAM uses `daily_view_ncaam_{date}_v1.json` (league in prefix for NCAAM only).
- **Multi-model location:** NBA multi-model is under `data/nba/view/` (nba_games_multi_model_v1.json). NCAAM multi-model is under `data/ncaam/model/` (ncaam_games_multi_model_v1.json). Different directory names for the same conceptual artifact.
- **Game state location:** NBA game state is `data/nba/view/nba_games_game_level_with_odds.json`. NCAAM game state is `data/ncaam/model/ncaam_canonical_games_with_lines.json` (view vs model dir).

---

## 8. Known path / history cautions

- **Backtest output location:** The unified backtest runner writes to **data/{league}/backtests/** (see `utils.io_helpers.get_backtest_output_root`). Many scripts under **eng/analysis/** still reference **eng/outputs/backtests** (e.g. BACKTEST_ROOT = `eng/outputs/backtests`). Those analysis scripts may be intended for NBA-only and may be looking at an old or different location; confirm before relying on them.
- **Calibration path:** NBA daily view builder hardcodes `eng/calibration/calibration_snapshot_v1.json`. Calibration is league-scoped by filename but stored under `eng/calibration/`, not under `data/nba/` or `data/ncaam/`.
- **Legacy data/daily:** The codebase comments state that `data/daily` is legacy and must not be used by active code; canonical daily roots are `data/nba/daily` and `data/ncaam/daily`.

---

## 9. Safe future cleanup candidates

- Add a one-line “NBA-only” (or “NCAAM-only”) note in docstrings for scripts whose names do not include the league (e.g. `build_daily_view.py`, `build_execution_overlay.py`, `r_101_report_backtest_vegas.py`) to improve discoverability without renames.
- Align analysis scripts that use `eng/outputs/backtests` with the current backtest output location `data/{league}/backtests/` (or document them as legacy) to avoid path confusion.
- Consider documenting or standardizing final-view and daily-view naming (e.g. league prefix or directory) in a future pass; no change to code required in this map.
- If calibration artifacts are ever moved under `data/{league}/`, update this map and all readers (e.g. `build_daily_view.py` CALIBRATION_PATH, `build_calibration_snapshot.py` OUTPUT_DIR) in one change.
