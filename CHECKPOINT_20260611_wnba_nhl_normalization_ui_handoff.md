# CHECKPOINT 2026-06-11 - WNBA/NHL Normalization + Streamlit UI Handoff

## Current Stop Point

This session expanded BookieX from NBA/NCAAM-only UI selection toward a configurable multi-league architecture. The online Streamlit app now exposes WNBA and NHL in the visible `League` dropdown, and WNBA has been pushed toward an NBA-style dashboard shell. The work is still mostly UI/presentation plus normalization scaffolding. WNBA/NHL do not yet have real daily-view model artifacts, backtests, Pocket ROI artifacts, or calculated picks.

Important distinction for next session:

- NBA/NCAAM are real calculated pipelines with daily views, model outputs, backtests, and Pocket ROI artifacts.
- WNBA/NHL are configured and visible, but currently rely on pending/placeholder dashboard shells until real league pipelines generate artifacts.

## Key Commits

Recent relevant commits on `main`:

- `be9c9573` - Add config-driven odds normalization registry
- `0d626326` - Expose configured leagues in Streamlit selector
- `3d17804a` - Harden Streamlit league dropdown options
- `b95297ba` - Show model status for new Streamlit leagues
- `d9ac6208` - Route new league no-data states to model status
- `2d8c082d` - Add ROI parity surface for new leagues
- `99c3c3a6` - Match new league presentation to NCAAM model surface
- `69121ee0` - Render WNBA with NBA-style dashboard shell

There are also newer daily dashboard commits after that:

- `942c04ad` - Daily dashboard push 2026-06-11 05:18
- `e1640037` - Daily dashboard push 2026-06-11 11:43

Do not assume the working tree is clean globally. This repo has a lot of pre-existing noisy/unrelated changes. The focused files from this stream were clean before this handoff file was created.

## Files Added Or Changed

Normalization architecture:

- `eng/normalization/__init__.py`
- `eng/normalization/base.py`
- `eng/normalization/config.py`
- `eng/normalization/odds_api.py`
- `eng/normalization/registry.py`

League normalization configs:

- `configs/normalization/leagues/basketball_nba.json`
- `configs/normalization/leagues/basketball_ncaab.json`
- `configs/normalization/leagues/basketball_wnba.json`
- `configs/normalization/leagues/icehockey_nhl.json`
- `configs/normalization/leagues/basketball_wnba.sample.json`
- `configs/normalization/leagues/icehockey_nhl.sample.json`

Dashboard/UI:

- `eng/ui/bookiex_dashboard.py`

Test:

- `tests/test_config_driven_normalization.py`

Backups created during the work:

- `eng/ui/bookiex_dashboard.py.bak_20260611_normalization_dropdown`
- `eng/ui/bookiex_dashboard.py.bak_20260611_league_dropdown_fallback`
- `eng/ui/bookiex_dashboard.py.bak_20260611_new_league_model_status`
- `eng/ui/bookiex_dashboard.py.bak_20260611_force_new_league_status`
- `eng/ui/bookiex_dashboard.py.bak_20260611_new_league_roi_status`
- `eng/ui/bookiex_dashboard.py.bak_20260611_ncaam_parity_new_leagues`
- `eng/ui/bookiex_dashboard.py.bak_20260611_wnba_nba_parity_shell`

## What Works Now

1. Config-driven normalization package exists.

   The new registry loads enabled JSON league configs by The Odds API sport key. It currently supports:

   - `basketball_nba`
   - `basketball_ncaab`
   - `basketball_wnba`
   - `icehockey_nhl`

2. Streamlit `League` dropdown includes:

   - NBA
   - NCAAM
   - WNBA
   - NHL

3. WNBA/NHL no longer fall through to the generic Streamlit error:

   - `No daily view data for WNBA...`
   - `No daily view data for NHL...`

   Instead they route to a pending dashboard shell.

4. WNBA has an NBA-style shell in `eng/ui/bookiex_dashboard.py`:

   - Header/sidebar bankroll
   - `Standard Slate View` / `Pocket ROI View`
   - ROI / predictive value surface
   - KBX Bet Sizing expander
   - Model vs Market section
   - Pending matchup card
   - Full model breakdown table
   - Pocket ROI pending tables

5. Local rendered Streamlit harness passed for WNBA:

   ```text
   wnba_standard_errors= 0
   wnba_standard_exceptions= 0
   wnba_pocket_errors= 0
   wnba_pocket_exceptions= 0
   ```

6. Config-driven normalization test passed earlier:

   ```powershell
   .venv\Scripts\python.exe -m unittest tests.test_config_driven_normalization
   ```

## What Is Still Missing

This is the core product gap.

WNBA and NHL still do not have the real calculated artifacts that NBA/NCAAM have. The UI can display a parity shell, but there are no real values for:

- daily WNBA/NHL games
- WNBA/NHL model projections
- spread/total picks
- edge values
- execution overlay ROI
- Pocket ROI
- best pocket per game
- leaderboard validation ROI
- Kelly sizing
- backtest Win%, ROI, graded games

No fake business logic was intentionally invented. Pending values are intentionally labeled pending.

## How NCAAM Actually Works

NCAAM uses the shared model runner:

- `eng/models/shared/model_gen_0051_runner.py`

NCAAM model stack:

- `eng/models/ncaam/ncaam_avg_score_model.py`
- `eng/models/ncaam/ncaam_momentum5_model.py`
- `eng/models/ncaam/ncaam_market_pressure_model.py`

Contract returned by each model:

- `model_name`
- `total_projection`
- `total_distance`
- `total_edge`
- `total_pick`
- `home_line_proj`
- `spread_distance`
- `spread_edge`
- `spread_pick`
- `parlay_edge_score`
- `context_flags`

NCAAM daily view:

- `eng/daily/build_daily_view_ncaam.py`

Dashboard presentation includes:

- Standard Slate View
- Pocket ROI View
- Model vs Market
- ROI / Win% / graded games
- ranked Pocket ROI opportunities
- best pocket per game
- validation ROI tables
- Kelly sizing when execution overlay artifacts exist

## Recommended Next Build Pass

The next session should stop improving placeholders and start generating real WNBA data artifacts. Recommended sequence:

1. Create WNBA league config module mirroring NBA/NCAAM path structure.

   Suggested file:

   - `configs/leagues/league_wnba.py`

   Required directories:

   - `data/wnba/raw`
   - `data/wnba/interim`
   - `data/wnba/derived`
   - `data/wnba/model`
   - `data/wnba/view`
   - `data/wnba/daily`
   - `data/wnba/backtests`

2. Extend `utils/io_helpers.py` to understand `wnba`.

   Needed helpers:

   - `get_game_state_path("wnba")`
   - `get_daily_view_output_dir("wnba")`
   - `get_final_view_json_path("wnba")`
   - model runner output paths
   - backtest root path

3. Add WNBA data ingestion path.

   Best controlled option:

   - Reuse shared odds normalization for `basketball_wnba`.
   - Build a minimal WNBA daily slate from Odds API event data first.
   - Then add ESPN/boxscore historical features when available.

4. Add WNBA model runner support.

   There are two viable choices:

   - NBA-style stack: clone/adapt NBA model registry but gate any missing injury/fatigue/3pt features.
   - NCAAM-style stack: average score, momentum5, market pressure. This is lower risk because it requires fewer sport-specific dependencies.

   User most recently asked for WNBA to look and behave like NBA. UI currently reflects NBA-style lanes, but real data may be easier to bootstrap with NCAAM-style models first.

5. Generate a real `data/wnba/daily/daily_view_wnba_<date>_v1.json`.

   The dashboard currently looks for:

   - `data/wnba/daily/daily_view_wnba_*_v1.json`

6. Create WNBA Pocket ROI artifacts only after there are settled backtest rows.

   Expected names should follow the existing pattern:

   - `wnba_model_pockets.json`
   - `wnba_model_combo_pockets.json`
   - `wnba_current_game_pocket_view.json`
   - `wnba_live_game_pocket_view.json`
   - `wnba_live_pocket_leaderboard.json`
   - `wnba_best_pocket_per_game.json`
   - `wnba_ranked_pocket_opportunities.json`
   - `wnba_pocket_leaderboard_validation.json`

7. Only after WNBA is working, repeat for NHL.

   NHL should probably not reuse NBA math blindly because puck line/scoring distributions differ. It can reuse the display contract, normalization registry, daily-view schema, and ROI/backtest framework.

## Suggested First Concrete Task For Next Session

Build WNBA minimal daily-view artifact from real Odds API data:

1. Load `basketball_wnba` raw odds if available.
2. Normalize via `eng.normalization`.
3. Emit a WNBA daily view JSON with the same outer structure the dashboard expects:

   ```json
   {
     "schema_version": "WNBA_DAILY_VIEW_V1",
     "model_version": "PENDING_REAL_MODEL_V1",
     "date": "YYYY-MM-DD",
     "games": []
   }
   ```

4. Once the UI has real games, add model calculations.

This gets the app past pure placeholder state and gives the user a visible slate.

## Validation Commands Used

Useful commands:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_config_driven_normalization
.venv\Scripts\python.exe -m py_compile eng\ui\bookiex_dashboard.py
.venv\Scripts\python.exe -c "from streamlit.testing.v1 import AppTest; app=AppTest.from_file('eng/ui/bookiex_dashboard.py'); app.run(timeout=30); app.selectbox[0].select('WNBA').run(timeout=30); print(len(app.error), len(app.exception))"
```

## User Expectations To Preserve

The user is not asking for another status page. They want WNBA and eventually NHL to feel and function like NBA/NCAAM:

- same presentation
- same model/predictive-value sections
- visible ROI
- visible Pocket ROI
- calculated picks where possible
- no fake numbers
- no empty dead-end pages

Be direct if data does not exist, but prioritize building real artifacts over describing missing pieces.

## GO / NO-GO

GO for the next pass:

- Implement WNBA real artifact generation first.
- Keep the UI shell, but replace pending rows with real WNBA daily slate/model rows as soon as possible.

NO-GO:

- Do not keep adding cosmetic-only status tables.
- Do not invent ROI, win rate, or picks without settled backtest data.
