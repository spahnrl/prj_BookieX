# BookieX Active Project Inventory (Review Only)

**Project:** prj_BookieX  
**Purpose:** Complete end-to-end inventory for target-structure migration.  
**Rules:** NBA = mature reference; NCAAM aligned toward NBA; forward-only artifact flow; no circular deps.  
**Excluded from active:** zzz_/ZZZ_ prefix, archive/Archive/old/Old folders, legacy/ (listed separately). Deleted files not assumed active.

---

## 1. ACTIVE END-TO-END PIPELINE MAP

### 1.1 000_RUN_ALL_NBA.py

| Attribute | Value |
|-----------|--------|
| **File path** | `000_RUN_ALL_NBA.py` |
| **Purpose** | Official NBA order-of-operations runner. Supports --mode LIVE \| LAB, --analysis, --analysis-only, --quiet. |
| **Leagues** | NBA only (all steps run with --league nba where applicable). |
| **Execution order** | INGESTION → FEATURES → CANONICAL → MARKET → MODELS → (ARBITRATION commented) → EVALUATION → EXECUTION → DAILY_VIEW; optionally + ANALYSIS if --analysis. LAB mode skips INGESTION. |
| **Scripts called directly** | See table below. |
| **Key output folders** | data/nba/ (raw, processed, view, daily per config); data/derived/ (NBA intermediate); eng/calibration/; data/nba/backtests/ (via backtest_gen_runner). |

**Script list (order):**

| Step | Script | Args |
|------|--------|------|
| INGESTION | a_data_static_000_nba_team_map.py | (none) |
| | b_gen_001_ingest_schedule.py | --league nba |
| | b_gen_003_join_schedule_teams.py | --league nba |
| | b_gen_004_ingest_boxscores.py | --league nba |
| | b_data_005_ingest_player_boxscores.py | (none) |
| | b_data_006_aggregate_team_3pt.py | (none) |
| | b_data_007_ingest_injuries.py | (none) |
| FEATURES | c_calc_010_add_team_rest_days.py through c_calc_020_build_team_injury_impact.py | (none) |
| CANONICAL | d_gen_021_build_canonical_games.py | --league nba |
| | d_gen_022_collapse_to_game_level.py | --league nba |
| MARKET | e_gen_031_get_betline.py | --league nba |
| | e_gen_032_get_betline_flatten.py | --league nba |
| | f_gen_041_add_betting_lines.py | --league nba |
| MODELS | eng/models/model_gen_0051_runner.py | --league nba |
| | eng/models/model_gen_0052_add_model.py | --league nba |
| EVALUATION | eng/backtest_gen_runner.py | (default league nba) |
| | eng/calibration/build_calibration_snapshot.py | (default league nba) |
| | r_101_report_backtest_vegas.py | (none) |
| EXECUTION | eng/execution/build_execution_overlay.py | (none) |
| DAILY_VIEW | eng/daily/build_gen_daily_view.py | --league nba |
| ANALYSIS (if --analysis) | eng/analysis/analysis_001_*.py … analysis_040_*.py | (none) |

Inline audits after: b_gen_001, b_gen_004, d_gen_022 (NBA paths: data/raw, data/derived, data/view).

---

### 1.2 000_RUN_ALL_NCAAM.py

| Attribute | Value |
|-----------|--------|
| **File path** | `000_RUN_ALL_NCAAM.py` |
| **Purpose** | Run NCAAM MVP pipeline end-to-end; optional --start-date/--end-date for schedule window; --quiet. |
| **Leagues** | NCAAM only. |
| **Execution order** | STEPS in order (no separate mode; no calibration step in list). |
| **Scripts called directly** | configs/league_ncaam.py (import/config), then script list below. |
| **Key output folders** | data/ncaam/ (raw, interim, canonical, processed, view, model, daily, backtests per config). |

**Script list (order):**

| Step | Script | Args |
|------|--------|------|
| Config | configs/league_ncaam.py | (imported as module in audit; not run as script) |
| Team universe | a_data_static_000a_build_ncaam_team_map_from_ncaa.py | (none) |
| | a_data_static_000b_ncaam_team_map.py | (none) |
| Schedule + scores | b_gen_001_ingest_schedule.py | --league ncaam (+ date window if provided) |
| | b_gen_003_join_schedule_teams.py | --league ncaam |
| | b_gen_004_ingest_boxscores.py | --league ncaam |
| Canonical/history | d_gen_021_build_canonical_games.py | --league ncaam |
| | d_gen_022_collapse_to_game_level.py | --league ncaam |
| | c_ncaam_001_build_avg_score_features.py | (none) |
| | c_ncaam_015_build_last5_momentum.py | (none) |
| | c_ncaam_099_merge_model_features.py | (none) |
| Market | e_gen_031_get_betline.py | --league ncaam |
| | e_gen_032_get_betline_flatten.py | --league ncaam |
| | f_gen_041_add_betting_lines.py | (--league ncaam added in build_step_command) |
| Models + outputs | eng/models/model_gen_0051_runner.py | --league ncaam |
| | eng/models/model_gen_0052_add_model.py | --league ncaam |
| | eng/daily/build_gen_daily_view.py | --league ncaam |
| | eng/backtest_gen_runner.py | --league ncaam |

Note: build_calibration_snapshot is not in NCAAM STEPS; calibration is run only from NBA runner (default nba).

---

### 1.3 000_RUN_ALL_NBA_NCAA.py

| Attribute | Value |
|-----------|--------|
| **File path** | `000_RUN_ALL_NBA_NCAA.py` |
| **Purpose** | Run both NBA and NCAAM pipelines in sequence; single executive summary at end. Optional --watch (runs pipelines then live monitor). |
| **Leagues** | NBA then NCAAM. |
| **Scripts called directly** | Invokes 000_RUN_ALL_NBA.py (with --mode, --analysis, --analysis-only, --quiet), then 000_RUN_ALL_NCAAM.py (with --start-date/--end-date, --quiet). Does not call individual pipeline scripts. |
| **Execution order** | 1) NBA: full 000_RUN_ALL_NBA.py. 2) NCAAM: full 000_RUN_ALL_NCAAM.py. 3) Optional live monitor loop. |
| **Key output folders** | Same as 1.1 and 1.2 (data/nba/, data/ncaam/, data/view, data/derived, eng/calibration, etc.). |

---

### 1.4 000_AUTO_BOOKIEX.py

| Attribute | Value |
|-----------|--------|
| **File path** | `000_AUTO_BOOKIEX.py` |
| **Purpose** | One-shot automation: LIVE model run then push daily. |
| **Scripts called directly** | 000_RUN_ALL_NBA.py --mode LIVE; then tools/push_daily.py. |
| **Leagues** | NBA-only pipeline (000_RUN_ALL_NBA), then push (NBA + NCAAM daily dirs). |
| **Key output folders** | Same as 000_RUN_ALL_NBA; push_daily stages data/nba/daily/, data/ncaam/daily/. |

---

### 1.5 000_bookiex_launcher_ui.py

| Attribute | Value |
|-----------|--------|
| **File path** | `000_bookiex_launcher_ui.py` |
| **Purpose** | Tkinter control panel: run pipelines, launch dashboard, push daily. |
| **Scripts called directly** | 000_RUN_ALL_NBA_NCAA.py (with --mode LAB/LIVE); 000_launch_bookiex_dashboard.py; tools/push_daily.py. |
| **Leagues** | Both (via NBA_NCAA runner and push). |

---

### 1.6 000_launch_bookiex_dashboard.py

| Attribute | Value |
|-----------|--------|
| **File path** | `000_launch_bookiex_dashboard.py` |
| **Purpose** | Launch Streamlit dashboard (wrapper for streamlit run eng/ui/bookiex_dashboard.py). |
| **Scripts called directly** | None (subprocess: streamlit run eng/ui/bookiex_dashboard.py). |
| **Key output folders** | Reads: data/nba/daily/, data/ncaam/daily/ (via io_helpers in dashboard). |

---

## 2. ACTIVE SCRIPT INVENTORY (by stage)

*Only scripts referenced by the launchers above or by active code (excluding legacy/archive/zzz_).*

### 2.1 Static / reference prep

| Current path | Script name | League scope | Active | Direct inputs | Direct outputs | Replaces | Recommended target folder |
|--------------|-------------|--------------|--------|---------------|----------------|----------|---------------------------|
| a_data_static_000_nba_team_map.py | a_data_static_000_nba_team_map | nba | active | (API/CDN) | data/ raw team map | — | root or scripts/static |
| a_data_static_000a_build_ncaam_team_map_from_ncaa.py | 000a build ncaam team map | ncaam | active | NCAA source | ncaam team map artifacts | old 000/001–006 | root or scripts/static |
| a_data_static_000b_ncaam_team_map.py | 000b ncaam team map | ncaam | active | 000a output | ncaam team map / loader | — | root or scripts/static |

### 2.2 Ingestion

| Current path | Script name | League scope | Active | Direct inputs | Direct outputs | Replaces | Recommended target folder |
|--------------|-------------|--------------|--------|---------------|----------------|----------|---------------------------|
| b_gen_001_ingest_schedule.py | b_gen_001_ingest_schedule | shared | active | API/config | data/{league}/raw schedule | b_data_001_nba, b_data_001_ncaam | root or scripts/ingest |
| b_gen_003_join_schedule_teams.py | b_gen_003_join_schedule_teams | shared | active | 001 output, team map | data/derived (nba) / league interim (ncaam) | b_data_003* | root or scripts/ingest |
| b_gen_004_ingest_boxscores.py | b_gen_004_ingest_boxscores | shared | active | 003 output, API | data/derived (nba) / league interim (ncaam) | b_data_004* | root or scripts/ingest |
| b_data_005_ingest_player_boxscores.py | b_data_005 | nba | active | data/derived/nba_games_joined.json, API | data/derived/nba_boxscores_player.* | — | root or scripts/ingest |
| b_data_006_aggregate_team_3pt.py | b_data_006 | nba | active | data/derived (player, joined) | data/derived/nba_team_3pt_recent.* | — | root or scripts/ingest |
| b_data_007_ingest_injuries.py | b_data_007 | nba | active | API | data/derived/nba_injuries_raw.* | — | root or scripts/ingest |

### 2.3 Joins / canonical

| Current path | Script name | League scope | Active | Direct inputs | Direct outputs | Replaces | Recommended target folder |
|--------------|-------------|--------------|--------|---------------|----------------|----------|---------------------------|
| d_gen_021_build_canonical_games.py | d_gen_021 | shared | active | data/derived (nba) / league canonical+interim (ncaam) | data/nba/view canonical* / data/ncaam/canonical | d_nba_021, d_ncaam_021 | root or scripts/canonical |
| d_gen_022_collapse_to_game_level.py | d_gen_022 | shared | active | 021 output | data/nba/view game_level* / data/ncaam/canonical game_level | d_nba_022, d_ncaam_022 | root or scripts/canonical |

### 2.4 Feature engineering

| Current path | Script name | League scope | Active | Direct inputs | Direct outputs | Replaces | Recommended target folder |
|--------------|-------------|--------------|--------|---------------|----------------|----------|---------------------------|
| c_calc_010_add_team_rest_days.py | c_calc_010 | nba | active | data/derived/nba_boxscores_team.json | data/derived/nba_games_with_rest.* | — | root or scripts/features |
| c_calc_011_flag_back_to_backs.py | c_calc_011 | nba | active | data/derived/nba_games_with_rest.json | data/derived/nba_games_with_b2b.* | — | root or scripts/features |
| c_calc_012_compute_fatigue_score.py | c_calc_012 | nba | active | data/derived/nba_games_with_b2b.json | data/derived/nba_games_with_fatigue.* | — | root or scripts/features |
| c_calc_013_calc_rest_home_away_averages.py | c_calc_013 | nba | active | data/derived/nba_games_with_b2b.json | data/derived/nba_team_averages.* | — | root or scripts/features |
| c_calc_014_rolling_team_averages.py | c_calc_014 | nba | active | data/derived/nba_games_joined.json | data/derived/nba_team_rolling_averages.json | — | root or scripts/features |
| c_calc_015_build_last5_momentum.py | c_calc_015 | nba | active | data/derived/nba_games_joined.json | data/derived/nba_team_last5.json | — | root or scripts/features |
| c_calc_020_build_team_injury_impact.py | c_calc_020 | nba | active | data/derived (injuries, games_joined) | data/derived/nba_team_injury_impact.json | — | root or scripts/features |
| c_ncaam_001_build_avg_score_features.py | c_ncaam_001 | ncaam | active | league canonical/game_level | model inputs | — | root or scripts/features |
| c_ncaam_015_build_last5_momentum.py | c_ncaam_015 | ncaam | active | league data | model inputs | — | root or scripts/features |
| c_ncaam_099_merge_model_features.py | c_ncaam_099 | ncaam | active | league model dir | merged features | — | root or scripts/features |

### 2.5 Market / odds

| Current path | Script name | League scope | Active | Direct inputs | Direct outputs | Replaces | Recommended target folder |
|--------------|-------------|--------------|--------|---------------|----------------|----------|---------------------------|
| e_gen_031_get_betline.py | e_gen_031 | shared | active | config/league paths, odds | league raw/processed betline | e_nba_031, e_ncaam_031 | root or scripts/market |
| e_gen_032_get_betline_flatten.py | e_gen_032 | shared | active | 031 output | data/derived (nba) / league (ncaam) flattened | e_nba_032, e_ncaam_032 | root or scripts/market |
| f_gen_041_add_betting_lines.py | f_gen_041 | shared | active | game view, odds, config | data/nba/view + data/derived (nba) / league view (ncaam) | f_nba_0041, f_ncaam_041 | root or scripts/market |
| e_ncaam_033_audit_market_names.py | e_ncaam_033 | ncaam | active | market/audit | audit outputs | — | root or tools |

### 2.6 Model

| Current path | Script name | League scope | Active | Direct inputs | Direct outputs | Replaces | Recommended target folder |
|--------------|-------------|--------------|--------|---------------|----------------|----------|---------------------------|
| eng/models/model_gen_0051_runner.py | model_gen_0051 | shared | active | io_helpers game state path | data/nba/view multi_model* / data/ncaam/model multi_model* | model_0051_runner, model_0051_runner_ncaam | eng/models |
| eng/models/model_gen_0052_add_model.py | model_gen_0052 | shared | active | 0051 output, io_helpers | data/nba/view final* / data/ncaam/view final* | model_0052_add_model, model_0052_add_model_ncaam | eng/models |
| eng/models/model_0052_add_model.py | model_0052 (NBA) | nba | superseded | data/view (legacy) | data/view | — | legacy (already replaced by gen) |
| eng/models/model_0052_add_model_ncaam.py | model_0052_ncaam | ncaam | uncertain | league view | league view | — | eng/models (still modified; may be used by gen) |
| eng/models/joel_baseline_model.py | joel_baseline | nba | active | (model) | (used by 0051) | — | eng/models |
| eng/models/ncaam_avg_score_model.py | ncaam_avg_score | ncaam | active | (model) | (used by 0051) | — | eng/models |
| eng/models/* (injury, market_blend, market_pressure, momentum_5game, ncaam_*) | various | nba/ncaam | active | (model) | (used by runners) | — | eng/models |
| eng/arbitration/confidence_engine.py | confidence_engine | shared | active | (logic) | (used by 0052) | — | eng/arbitration |
| eng/arbitration/confidence_gate.py | confidence_gate | shared | active | (logic) | (used by 0052) | — | eng/arbitration |
| eng/decision_explainer.py | decision_explainer | shared | active | (logic) | (used by 0052) | — | eng |
| eng/eval_sanity.py | eval_sanity | shared | active | (logic) | (used by 0052) | — | eng |
| eng/agent_stub.py | agent_stub | shared | active | (logic) | (used by 0052, r_101) | — | eng |

### 2.7 Final view / daily

| Current path | Script name | League scope | Active | Direct inputs | Direct outputs | Replaces | Recommended target folder |
|--------------|-------------|--------------|--------|---------------|----------------|----------|---------------------------|
| eng/daily/build_gen_daily_view.py | build_gen_daily_view | shared | active | io_helpers final view, calibration | data/nba/daily/* / data/ncaam/daily/* | — | eng/daily |
| eng/daily/build_daily_view.py | build_daily_view | nba | active | (called by build_gen_daily_view for nba) | data/nba/daily | — | eng/daily |
| eng/daily/build_daily_view_ncaam.py | build_daily_view_ncaam | ncaam | active | (called by build_gen_daily_view for ncaam) | data/ncaam/daily | — | eng/daily |

### 2.8 Backtest / calibration

| Current path | Script name | League scope | Active | Direct inputs | Direct outputs | Replaces | Recommended target folder |
|--------------|-------------|--------------|--------|---------------|----------------|----------|---------------------------|
| eng/backtest_gen_runner.py | backtest_gen_runner | shared | active | io_helpers model runner JSON, get_output_root | data/{league}/backtests/backtest_{ts}/ | backtest_runner, backtest_runner_ncaam | eng |
| eng/backtest_grader.py | backtest_grader | shared | active | (imported by backtest_gen_runner) | — | — | eng |
| eng/backtest_summary.py | backtest_summary | shared | legacy helper | (imported by legacy/root/eng/backtest_runner only) | — | — | eng (do not move without fixing legacy import) |
| eng/calibration/build_calibration_snapshot.py | build_calibration_snapshot | shared | active | io_helpers get_backtest_output_root, latest backtest_* | eng/calibration/calibration_snapshot_v1.json, calibration_snapshot_ncaam_v1.json | — | eng/calibration |

### 2.9 Execution / agents

| Current path | Script name | League scope | Active | Direct inputs | Direct outputs | Replaces | Recommended target folder |
|--------------|-------------|--------------|--------|---------------|----------------|----------|---------------------------|
| eng/execution/build_execution_overlay.py | build_execution_overlay | nba | active | view/final, calibration | (overlay logic) | — | eng/execution |
| eng/execution/timing_agent.py | timing_agent | shared | active | (agent) | — | — | eng/execution |
| eng/execution/live_monitor_agent.py | live_monitor_agent | shared | active | eng/outputs/analysis, etc. | — | — | eng/execution |

### 2.10 Reporting / analysis

| Current path | Script name | League scope | Active | Direct inputs | Direct outputs | Replaces | Recommended target folder |
|--------------|-------------|--------------|--------|---------------|----------------|----------|---------------------------|
| r_101_report_backtest_vegas.py | r_101_report | nba | active | backtest, view | data/view/report_backtest_vegas.csv | — | root or eng/reports |
| eng/analysis/analysis_001_*.py … analysis_040_*.py | analysis_001–040 | nba (most) | active | data/view/*, eng/outputs/backtests (many) | (stdout/reports) | — | eng/analysis |
| eng/analysis/analysis_gen_003_bias_detection.py | analysis_gen_003 | shared | active | data/{league}/backtests | (bias report) | — | eng/analysis |
| eng/analysis_gen_manager.py | analysis_gen_manager | shared | active | backtest path, league | eng/outputs/analysis/bias_report_{league}.json | — | eng |

### 2.11 UI / CLI

| Current path | Script name | League scope | Active | Direct inputs | Direct outputs | Replaces | Recommended target folder |
|--------------|-------------|--------------|--------|---------------|----------------|----------|---------------------------|
| eng/ui/bookiex_dashboard.py | bookiex_dashboard | shared | active | io_helpers get_daily_view_output_dir(nba/ncaam) | (Streamlit UI) | — | eng/ui |
| eng/cli/bookiex_cli.py | bookiex_cli | nba | active | io_helpers get_daily_view_output_dir(nba) | (CLI print) | — | eng/cli |

### 2.12 Tools / diagnostics

| Current path | Script name | League scope | Active | Direct inputs | Direct outputs | Replaces | Recommended target folder |
|--------------|-------------|--------------|--------|---------------|----------------|----------|---------------------------|
| tools/push_daily.py | push_daily | shared | active | (git) | stages data/nba/daily/, data/ncaam/daily/ | — | tools |
| tools/push_selected_daily_views.py | push_selected_daily | nba | active | data/nba/daily/*.json | git push | — | tools |
| tools/push_ui_only.py | push_ui_only | — | active | (git) | — | — | tools |
| tools/check_bookiex_health.py | check_health | — | active | (various) | — | — | tools |
| tools/generate_past_alerts.py | generate_past_alerts | — | active | — | — | — | tools |
| tools/inspect_ncaam_schedule_shape.py | inspect_ncaam_schedule | ncaam | active | league schedule | — | — | tools |
| tools/check_ncaam_inventory.py | check_ncaam_inventory | ncaam | active | — | — | — | tools |
| tools/build_historical_schedules.py | build_historical_schedules | shared | active | — | raw schedule artifacts | — | tools |
| tools/fetch_missing_raw.py | fetch_missing_raw | — | active | — | — | — | tools |
| tools/merge_and_heal.py | merge_and_heal | — | active | — | — | — | tools |
| tools/sync_historical_odds.py | sync_historical_odds | — | active | — | — | — | tools |
| tools/mermaid_pipeline_diagram.py | mermaid_pipeline | — | active | — | docs | — | tools |
| verify_isolation.py | verify_isolation | — | active | (paths) | — | — | root or tools |

### 2.13 Config / helpers (no pipeline stage)

| Current path | Script name | League scope | Active | Direct inputs | Direct outputs | Replaces | Recommended target folder |
|--------------|-------------|--------------|--------|---------------|----------------|----------|---------------------------|
| configs/league_nba.py | league_nba | nba | active | — | paths (DATA_ROOT, RAW_DIR, VIEW_DIR, DAILY_DIR, DERIVED_DIR, etc.) | — | configs |
| configs/league_ncaam.py | league_ncaam | ncaam | active | — | paths (DATA_ROOT, VIEW_DIR, MODEL_DIR, BACKTEST_DIR, DAILY_DIR, etc.) | — | configs |
| utils/io_helpers.py | io_helpers | shared | active | — | get_* path helpers (game_state, daily_view_output_dir, backtest_output_root, final_view, model_runner, etc.) | — | utils |
| utils/audit_helpers.py | audit_helpers | shared | active | — | audit_file_consistency, audit_csv_consistency | — | utils |
| utils/mapping_helpers.py | mapping_helpers | shared | active | — | (mapping logic) | — | utils |
| utils/risk_management.py | risk_management | shared | active | — | (Kelly etc.) | — | utils |
| utils/decorators.py | decorators | shared | active | — | add_agent_reasoning_to_rows, etc. | — | utils |
| utils/run_log.py | run_log | shared | active | — | logging | — | utils |

---

## 3. FOLDER INVENTORY (tree summary)

*Counts are approximate; exclude .git, __pycache__, node_modules, .cursor. legacy/ listed separately.*

| Folder path | Files (approx) | Subfolders | Status | Description |
|-------------|----------------|------------|--------|-------------|
| (repo root) | 50+ .py, 000_*, a_*, b_*, c_*, d_*, e_*, f_*, r_*, verify_* | many | active | Launchers, pipeline scripts, configs reference |
| configs/ | 3 | 0 | active | league_nba.py, league_ncaam.py, bankroll.json |
| eng/ | 79 .py | 6+ | active | backtest, calibration, cli, daily, execution, models, ui, analysis, arbitration |
| eng/analysis/ | 41 .py | 0 | active | analysis_001–041, analysis_gen_003 |
| eng/arbitration/ | 2 | 0 | active | confidence_engine, confidence_gate |
| eng/calibration/ | 1 .py + JSON | 0 | active | build_calibration_snapshot.py, calibration_snapshot_*.json |
| eng/cli/ | 1 | 0 | active | bookiex_cli.py |
| eng/daily/ | 3 | 0 | active | build_daily_view.py, build_daily_view_ncaam.py, build_gen_daily_view.py |
| eng/execution/ | 3 | 0 | active | build_execution_overlay, live_monitor_agent, timing_agent |
| eng/models/ | 20+ | 0 | active | model_gen_0051/0052, model_0052*, base_model, *model.py |
| eng/ui/ | 1 | 0 | active | bookiex_dashboard.py |
| tools/ | 15 .py | 0 | active | push_daily, push_selected_daily_views, check_*, build_*, fetch_*, etc. |
| utils/ | 8+ .py | 0 | active | io_helpers, audit_helpers, mapping_helpers, risk_management, decorators, run_log |
| data/ | (many) | nba, ncaam, view, derived, static, archive | mixed | Runtime/generated artifacts; data/nba, data/ncaam = target structure; data/view, data/derived = legacy NBA |
| data/nba/ | (varies) | raw, processed, view, daily, backtests | active/generated | League-scoped NBA (target) |
| data/ncaam/ | (varies) | raw, interim, canonical, processed, view, model, daily, backtests, market | active/generated | League-scoped NCAAM (target) |
| data/view/ | (varies) | 0 | legacy/mixed | NBA legacy view artifacts (fallback in io_helpers) |
| data/derived/ | (varies) | 0 | legacy/mixed | NBA intermediate (nba_games_joined, nba_boxscores_team, nba_team_*, etc.) |
| docs/ | (varies) | 0 | active | REFACTOR_DOMAIN_ISOLATION.md, pipeline_diagram*, etc. |
| logs/ | (varies) | 0 | generated | Runtime logs |
| legacy/ | (many) | root, zzz_cleanup_* | legacy | legacy/root/ = moved replaced scripts; zzz_* = archived; do not treat as active |
| archive/ | (varies) | legacy_scripts, etc. | legacy | Old script copies; not active reference |
| TRUTH/ | 2 | 0 | uncertain | build_baseline_manifest, verify_determinism |
| scripts/ | (varies) | 0 | uncertain | run_migration etc. |
| assets/ | images | 0 | active | UI assets |

---

## 4. ACTIVE VS LEGACY / AMBIGUOUS

### 4.1 Active canonical files (in pipeline or required by it)

- All scripts listed in section 2 as “active” and referenced by 000_RUN_ALL*, 000_AUTO*, 000_bookiex_launcher_ui, 000_launch_bookiex_dashboard, or imported by those scripts.
- configs/league_nba.py, configs/league_ncaam.py.
- utils/io_helpers.py, utils/audit_helpers.py, utils/mapping_helpers.py, utils/risk_management.py, utils/decorators.py, utils/run_log.py.
- eng/backtest_grader.py, eng/decision_explainer.py, eng/eval_sanity.py, eng/agent_stub.py, eng/arbitration/*.py, eng/models/* (except superseded model_0052_add_model.py).

### 4.2 Legacy / superseded files

| Current path | Likely replacement | Confidence |
|--------------|--------------------|------------|
| legacy/root/b_data_001_nba_schedule.py | b_gen_001_ingest_schedule.py | high |
| legacy/root/b_data_001_ncaam_schedule.py | b_gen_001_ingest_schedule.py | high |
| legacy/root/b_data_003_join_schedule_teams.py | b_gen_003_join_schedule_teams.py | high |
| legacy/root/b_data_003_join_ncaam_schedule_teams.py | b_gen_003_join_schedule_teams.py | high |
| legacy/root/b_data_004_ingest_boxscores.py | b_gen_004_ingest_boxscores.py | high |
| legacy/root/b_data_004_ncaam_ingest_boxscores.py | b_gen_004_ingest_boxscores.py | high |
| legacy/root/d_nba_021_build_canonical_games.py | d_gen_021_build_canonical_games.py | high |
| legacy/root/d_nba_022_collapse_to_game_level.py | d_gen_022_collapse_to_game_level.py | high |
| legacy/root/d_ncaam_021_build_canonical_games.py | d_gen_021_build_canonical_games.py | high |
| legacy/root/d_ncaam_022_collapse_to_game_level.py | d_gen_022_collapse_to_game_level.py | high |
| legacy/root/e_nba_031_get_betline.py | e_gen_031_get_betline.py | high |
| legacy/root/e_nba_032_get_betline_flatten.py | e_gen_032_get_betline_flatten.py | high |
| legacy/root/e_ncaam_031_get_betline.py | e_gen_031_get_betline.py | high |
| legacy/root/e_ncaam_032_get_betline_flatten.py | e_gen_032_get_betline_flatten.py | high |
| legacy/root/eng/backtest_runner.py | eng/backtest_gen_runner.py | high |
| legacy/root/eng/backtest_runner_ncaam.py | eng/backtest_gen_runner.py | high |
| legacy/root/eng/models/model_0051_runner.py | eng/models/model_gen_0051_runner.py | high |
| legacy/root/eng/models/model_0051_runner_ncaam.py | eng/models/model_gen_0051_runner.py | high |
| legacy/root/f_nba_0041_add_betting_lines.py | f_gen_041_add_betting_lines.py | high |
| legacy/root/f_ncaam_041_add_betting_lines.py | f_gen_041_add_betting_lines.py | high |
| eng/models/model_0052_add_model.py | eng/models/model_gen_0052_add_model.py | high (not in launchers; comments in confidence_engine) |

Deleted (not on disk; were candidates for legacy/root/): a_data_static_000_ncaam_market_team_map, 001–006, eng/ui/zz_0204-02-bookiex_dashboard.py.

### 4.3 Ambiguous (do not move automatically)

| Current path | Reason |
|--------------|--------|
| eng/backtest_summary.py | Only imported by legacy/root/eng/backtest_runner.py; moving would break legacy runner unless import fixed. |
| eng/models/model_0052_add_model_ncaam.py | Modified; may still be referenced or in use; confirm before moving. |
| TRUTH/*, scripts/* | Role in pipeline unclear; verify before moving. |
| data/view/, data/derived/ | Still written/read by active NBA pipeline; migrate only after consumers use data/nba/*. |

---

## 5. DATA / ARTIFACT CONTRACT MAP

| Path | Who writes | Who reads | League scope | Matches target? |
|------|------------|-----------|--------------|-----------------|
| data/nba/raw/ | b_gen_001 (nba), odds ingestion | b_gen_003, config | nba | yes |
| data/nba/processed/ | (gen scripts can write here per config) | config, io_helpers | nba | yes |
| data/nba/view/ | d_gen_021/022, f_gen_041, model_gen_0051/0052 (per config) | build_daily_view, io_helpers (get_final_view, get_game_state) | nba | yes |
| data/nba/daily/ | build_gen_daily_view (nba) | dashboard, push_daily, push_selected_daily_views, bookiex_cli (via io_helpers) | nba | yes |
| data/nba/backtests/ | backtest_gen_runner (nba) | build_calibration_snapshot (via io_helpers get_backtest_output_root) | nba | yes |
| data/ncaam/* | NCAAM pipeline (b_gen_*, d_gen_*, e_*, f_*, model_gen_*, build_gen_daily_view, backtest_gen_runner) | Same + dashboard, push_daily, calibration | ncaam | yes |
| data/view/ | Still written by some NBA steps (model_0052_add_model, d_022, etc. if using legacy paths); 000_RUN_ALL_NBA inline audit references data/view | io_helpers (NBA fallback), many eng/analysis scripts (analysis_001, 003, 004, 007, 009, 014–018, 020, 022, 024–025, 029–030), r_101 | nba (legacy) | no (legacy fallback) |
| data/derived/ | b_gen_003/004, b_data_005/006/007, c_calc_*, d_gen_021, e_gen_032, f_gen_041 (legacy path) | b_gen_004, b_data_005/006/007, c_calc_*, d_gen_021, b_gen_003 (nba_games_joined.csv) | nba | no (legacy NBA intermediate) |
| eng/calibration/ | build_calibration_snapshot.py | build_daily_view.py (CALIBRATION_PATH) | nba (v1), ncaam (ncaam_v1) | yes (code under eng/) |
| eng/outputs/backtests/ | (none in active pipeline; backtest_gen_runner writes data/{league}/backtests/) | eng/analysis/* (many: 001–004, 007, 009, 014–018, 020–022, 025–029, 031–034, 036–040), eng/analysis_gen_manager | nba (legacy) | no (migrated to data/{league}/backtests/) |
| eng/outputs/analysis/ | eng/analysis_gen_manager | eng/execution/live_monitor_agent, utils/decorators | ncaam (bias_report_ncaam.json) | uncertain |

---

## 6. IMPORT / DEPENDENCY RISKS

### 6.1 Scripts that still reference old paths

- **data/view/** (hardcoded): eng/analysis/analysis_001_edge_distribution.py (INPUT_PATH), analysis_004_model_comparison.py, analysis_005_cross_model_edge_stats.py, analysis_007_model_edge_correlation.py, analysis_009_fatigue_activation_rate.py, analysis_014_disagreement_bucket.py, analysis_015_confidence_backtest.py, analysis_017_confidence_backtest_v2.py, analysis_018_spread_edge_strength_curve.py, analysis_019_spread_direction_check.py, analysis_024_field_presence_audit.py, analysis_029_model_pipeline_trace.py, analysis_030_projection_math_validation.py; eng/models/model_0052_add_model.py (VIEW_DIR); r_101_report_backtest_vegas.py (OUT_CSV data/view/report_backtest_vegas.csv).
- **data/derived/** (hardcoded): c_calc_010–015, c_calc_020; b_data_005, b_data_006, b_data_007; b_gen_003_join_schedule_teams.py (nba_games_joined.csv); b_gen_004_ingest_boxscores.py; d_gen_021_build_canonical_games.py (NBA_DATA_DIR); e_gen_032_get_betline_flatten.py (NBA_OUT_*).
- **eng/outputs/backtests** (hardcoded): eng/analysis/analysis_002, 003, 016, 021, 022, 025, 026, 027, 028, 032, 033, 034, 036, 037, 038, 039; eng/analysis_gen_manager (and default --output eng/outputs/analysis/). Backtest producer now writes to data/{league}/backtests/; calibration was patched to read from there; analysis scripts still point at eng/outputs/backtests.

### 6.2 Forward-only / migration risks

- NBA still reads from data/view and data/derived when data/nba/* is missing (io_helpers fallbacks). Moving only artifacts without switching all readers can break pipeline.
- 000_RUN_ALL_NBA.py inline audits reference data/view and data/derived for NBA (e.g. d_gen_022 audit: data/view/nba_games_canonical.csv, nba_games_game_level.csv). These must be updated when NBA moves fully to data/nba/view.

### 6.3 Duplicate / parallel helpers

- configs/league_nba.py DERIVED_DIR and BOXSCORES_TEAM_* point at data/derived; rest of league_nba points at data/nba. So one config mixes legacy and target paths.
- eng/backtest_summary.py is used only by legacy/root/eng/backtest_runner.py; backtest_gen_runner builds summary inline. Two implementations of “backtest summary” (one legacy, one active).

### 6.4 Likely broken or partial migrations

- Analysis scripts (eng/analysis/*) that read eng/outputs/backtests will not see backtest output from backtest_gen_runner (which writes data/{league}/backtests/). Either update analysis to use io_helpers.get_backtest_output_root(league) or keep a symlink/copy.
- f_gen_041_add_betting_lines.py uses legacy_view = Path("data/view") and legacy_derived = Path("data/derived") for fallback; ensure NBA path priority is correct and eventually remove legacy.

---

## 7. TARGET PLACEMENT RECOMMENDATION TABLE

| Current Path | File Type | Status | League Scope | Recommended Target Path | Move / Keep / Leave Alone | Why |
|--------------|-----------|--------|--------------|--------------------------|----------------------------|-----|
| 000_RUN_ALL_NBA.py | script | active | nba | (root or scripts/launchers) | Keep | Launcher; path refs need update when data moves |
| 000_RUN_ALL_NCAAM.py | script | active | ncaam | (root or scripts/launchers) | Keep | Launcher |
| 000_RUN_ALL_NBA_NCAA.py | script | active | both | (root or scripts/launchers) | Keep | Launcher |
| 000_AUTO_BOOKIEX.py | script | active | nba | (root or scripts/launchers) | Keep | Launcher |
| 000_bookiex_launcher_ui.py | script | active | both | (root or scripts/launchers) | Keep | Launcher |
| 000_launch_bookiex_dashboard.py | script | active | — | (root or scripts/launchers) | Keep | Launcher |
| a_data_static_000_nba_team_map.py | script | active | nba | (root or scripts/static) | Keep | In pipeline |
| a_data_static_000a_build_ncaam_team_map_from_ncaa.py | script | active | ncaam | (root or scripts/static) | Keep | In pipeline |
| a_data_static_000b_ncaam_team_map.py | script | active | ncaam | (root or scripts/static) | Keep | In pipeline |
| b_gen_001_ingest_schedule.py | script | active | shared | (root or scripts/ingest) | Keep | In pipeline |
| b_gen_003_join_schedule_teams.py | script | active | shared | (root or scripts/ingest) | Keep | In pipeline |
| b_gen_004_ingest_boxscores.py | script | active | shared | (root or scripts/ingest) | Keep | In pipeline |
| b_data_005_ingest_player_boxscores.py | script | active | nba | (root or scripts/ingest) | Keep | In pipeline |
| b_data_006_aggregate_team_3pt.py | script | active | nba | (root or scripts/ingest) | Keep | In pipeline |
| b_data_007_ingest_injuries.py | script | active | nba | (root or scripts/ingest) | Keep | In pipeline |
| c_calc_010_add_team_rest_days.py … c_calc_020_*.py | script | active | nba | (root or scripts/features) | Keep | In pipeline |
| c_ncaam_001_*.py, c_ncaam_015_*.py, c_ncaam_099_*.py | script | active | ncaam | (root or scripts/features) | Keep | In pipeline |
| d_gen_021_build_canonical_games.py | script | active | shared | (root or scripts/canonical) | Keep | In pipeline |
| d_gen_022_collapse_to_game_level.py | script | active | shared | (root or scripts/canonical) | Keep | In pipeline |
| e_gen_031_get_betline.py | script | active | shared | (root or scripts/market) | Keep | In pipeline |
| e_gen_032_get_betline_flatten.py | script | active | shared | (root or scripts/market) | Keep | In pipeline |
| f_gen_041_add_betting_lines.py | script | active | shared | (root or scripts/market) | Keep | In pipeline |
| e_ncaam_033_audit_market_names.py | script | active | ncaam | (root or tools) | Keep | Tool |
| eng/models/model_gen_0051_runner.py | script | active | shared | eng/models | Keep | In pipeline |
| eng/models/model_gen_0052_add_model.py | script | active | shared | eng/models | Keep | In pipeline |
| eng/models/model_0052_add_model.py | script | legacy | nba | legacy/root/eng/models | Move | Superseded by model_gen_0052 |
| eng/models/model_0052_add_model_ncaam.py | script | uncertain | ncaam | eng/models | Leave alone | Still modified; confirm refs |
| eng/backtest_gen_runner.py | script | active | shared | eng | Keep | In pipeline |
| eng/backtest_grader.py | script | active | shared | eng | Keep | In pipeline |
| eng/backtest_summary.py | script | legacy helper | shared | eng | Leave alone | Used by legacy/root runner; fix import before move |
| eng/calibration/build_calibration_snapshot.py | script | active | shared | eng/calibration | Keep | In pipeline |
| eng/daily/build_gen_daily_view.py | script | active | shared | eng/daily | Keep | In pipeline |
| eng/daily/build_daily_view.py | script | active | nba | eng/daily | Keep | In pipeline |
| eng/daily/build_daily_view_ncaam.py | script | active | ncaam | eng/daily | Keep | In pipeline |
| eng/execution/build_execution_overlay.py | script | active | nba | eng/execution | Keep | In pipeline |
| eng/execution/timing_agent.py | script | active | shared | eng/execution | Keep | In pipeline |
| eng/execution/live_monitor_agent.py | script | active | shared | eng/execution | Keep | In pipeline |
| eng/ui/bookiex_dashboard.py | script | active | shared | eng/ui | Keep | In pipeline |
| eng/cli/bookiex_cli.py | script | active | nba | eng/cli | Keep | In pipeline |
| r_101_report_backtest_vegas.py | script | active | nba | (root or eng/reports) | Keep | In pipeline; update OUT_CSV when view moves |
| eng/analysis/analysis_001_*.py … analysis_040_*.py | script | active | nba | eng/analysis | Keep | In pipeline; update backtest/view paths |
| eng/analysis/analysis_gen_003_bias_detection.py | script | active | shared | eng/analysis | Keep | Uses data/{league}/backtests |
| eng/analysis_gen_manager.py | script | active | shared | eng | Keep | Update backtest/output paths if needed |
| tools/push_daily.py | script | active | shared | tools | Keep | In pipeline |
| tools/push_selected_daily_views.py | script | active | nba | tools | Keep | In pipeline |
| tools/push_ui_only.py | script | active | — | tools | Keep | Tool |
| tools/check_bookiex_health.py | script | active | — | tools | Keep | Tool |
| tools/generate_past_alerts.py | script | active | — | tools | Keep | Tool |
| tools/inspect_ncaam_schedule_shape.py | script | active | ncaam | tools | Keep | Tool |
| tools/check_ncaam_inventory.py | script | active | ncaam | tools | Keep | Tool |
| tools/build_historical_schedules.py | script | active | shared | tools | Keep | Tool |
| tools/fetch_missing_raw.py | script | active | — | tools | Keep | Tool |
| tools/merge_and_heal.py | script | active | — | tools | Keep | Tool |
| tools/sync_historical_odds.py | script | active | — | tools | Keep | Tool |
| tools/mermaid_pipeline_diagram.py | script | active | — | tools | Keep | Tool |
| verify_isolation.py | script | active | — | root or tools | Keep | Tool |
| configs/league_nba.py | config | active | nba | configs | Keep | Path authority; align DERIVED_DIR with target |
| configs/league_ncaam.py | config | active | ncaam | configs | Keep | Path authority |
| configs/bankroll.json | config | active | — | configs | Keep | Config |
| utils/io_helpers.py | helper | active | shared | utils | Keep | Path contract |
| utils/audit_helpers.py | helper | active | shared | utils | Keep | In pipeline |
| utils/mapping_helpers.py | helper | active | shared | utils | Keep | In pipeline |
| utils/risk_management.py | helper | active | shared | utils | Keep | In pipeline |
| utils/decorators.py | helper | active | shared | utils | Keep | In pipeline |
| utils/run_log.py | helper | active | shared | utils | Keep | In pipeline |
| data/nba/* | data | generated | nba | data/nba/* | Keep | Target structure |
| data/ncaam/* | data | generated | ncaam | data/ncaam/* | Keep | Target structure |
| data/view/* | data | mixed | nba legacy | (migrate to data/nba/view) | Leave alone until consumers updated | Legacy NBA; many readers |
| data/derived/* | data | mixed | nba legacy | (migrate to data/nba/processed or interim) | Leave alone until consumers updated | Legacy NBA intermediate |
| eng/calibration/*.json | data | generated | nba/ncaam | eng/calibration | Keep | Written/read by active code |
| eng/outputs/backtests | data | legacy | nba | (deprecated; use data/nba/backtests) | Leave alone / remove when analysis updated | Analysis scripts still reference |
| eng/outputs/analysis | data | generated | ncaam | eng/outputs/analysis or data/ncaam/analysis | Uncertain | analysis_gen_manager writes here |
| legacy/root/* | script | legacy | — | legacy/root/* | Leave alone | Already moved; do not treat as active |
| legacy/zzz_* | script | legacy | — | legacy | Leave alone | Archived; not active reference |

---

## 8. SUMMARY COUNTS

| Metric | Count |
|--------|--------|
| Active scripts (in pipeline or required by it) | ~95 (root + eng + tools + utils launcher-called or imported) |
| Legacy/superseded scripts (in legacy/root or identified superseded) | 21 (20 in legacy/root + model_0052_add_model.py) |
| Ambiguous scripts (do not move automatically) | 4+ (backtest_summary, model_0052_add_model_ncaam, TRUTH/*, scripts/*) |
| Generated/runtime artifact folders | data/nba/*, data/ncaam/*, data/view, data/derived, eng/calibration, eng/outputs, logs/ |
| Top-level folders (meaningful) | configs, eng, tools, utils, data, docs, logs, legacy, archive, TRUTH, scripts, assets |
| Active launcher/orchestrator files | 6 (000_RUN_ALL_NBA.py, 000_RUN_ALL_NCAAM.py, 000_RUN_ALL_NBA_NCAAM.py, 000_AUTO_BOOKIEX.py, 000_bookiex_launcher_ui.py, 000_launch_bookiex_dashboard.py) |

---

*End of inventory. Review only; no code edits, moves, or refactors.*
