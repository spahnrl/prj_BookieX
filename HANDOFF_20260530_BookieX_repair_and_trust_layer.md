# HANDOFF — 2026-05-30 — BookieX Repair and Pocket Robustness Trust Layer

## A. Executive summary

BookieX was repaired, NBA daily-view gaps were backfilled, NBA season recap and pocket
robustness analysis tools were added, and the NBA dashboard now supports a robustness trust
layer. The trust layer (KEEP / WATCH / FADE / KILL) is the decision layer that sits on top of
the historical season-long hot/warm/cold pocket state.

## B. What broke

- After 2026-05-17, BookieX stopped updating.
- Cause: malformed JSON in `data/nba/backtests/backtest_20260517_100524/backtest_games.json`
  (`Expecting property name enclosed in double quotes: line 280298 column 9`).
- Fix: quarantine/rename the corrupted file and rerun automation (`000_AUTO_BOOKIEX.py`).
  New backtests generated successfully and the Streamlit dashboard recovered.

## C. What was added

- NBA daily backfill script — `tools/backfill_nba_daily_views.py`.
- NBA season recap analysis script — `tools/analysis/analyze_nba_season_recap.py`.
- NBA pocket robustness analysis script — `tools/analysis/analyze_nba_pocket_robustness.py`.
- Stable robustness artifact — `data/nba/view/nba_pocket_robustness_latest.json` (via `--emit-latest`).
- Dashboard trust display — NBA Pocket ROI View in `eng/ui/bookiex_dashboard.py`.
- Automation/push integration — soft robustness step in `000_AUTO_BOOKIEX.py`; artifact staged by `tools/push_daily.py`.

## D. Current artifact flow

```
Backtest (backtest_games.json)
  → NBA pocket artifacts (build_nba_model_pockets.py)
    → NBA robustness analysis (analyze_nba_pocket_robustness.py --emit-latest)
      → data/nba/view/nba_pocket_robustness_latest.json
        → dashboard trust display (bookiex_dashboard.py)
          → push_daily.py (stages the stable artifact for the deployed app)
```

## E. Important files

- `000_AUTO_BOOKIEX.py` — top-level automation. Runs the live model run, rebuilds NBA/NCAAM
  pocket artifacts, runs NBA robustness as a **non-blocking** step (warn-and-continue), then pushes.
- `tools/push_daily.py` — stages dashboard-relevant artifacts with targeted `git add -f`, commits,
  and pushes. Now also stages `data/nba/view/nba_pocket_robustness_latest.json` (guarded by an
  existence check so a missing file does not abort the push).
- `tools/backfill_nba_daily_views.py` — regenerates missing NBA daily-view JSONs for a date range;
  skips existing files unless `--force`, validates output JSON, prints a summary (created / skipped /
  zero-game / errors).
- `tools/analysis/analyze_nba_season_recap.py` — read-only full-season NBA recap (regular vs
  play-in vs playoffs, pockets, execution overlay, model comparison, calibration, daily timeline).
  Writes to a timestamped `data/nba/analysis/season_recap_*` folder.
- `tools/analysis/analyze_nba_pocket_robustness.py` — read-only robustness recompute from
  `backtest_games.json`; stress-tests pockets across segments, a recent window, an out-of-sample
  second-half hold-out, and the postseason; assigns KEEP/WATCH/FADE/KILL + a 0–100 trust score.
  `--emit-latest` also writes the stable join-ready artifact.
- `data/nba/view/nba_pocket_robustness_latest.json` — stable artifact consumed by the dashboard.
  Keys: singles `(model, market_type, edge_bucket)`; combos `(market_type, combo_kind, models_key,
  state_signature)`. Each row carries rating, trust_score, full/second-half/recent/postseason ROI,
  flags, recommendation, plus `source_backtest_dir` for staleness checks.
- `eng/ui/bookiex_dashboard.py` — Streamlit dashboard. NBA Pocket ROI View now joins the robustness
  artifact, shows trust columns, hides FADE/KILL by default, and includes the field-guide expander.
- `eng/execution/build_nba_model_pockets.py` — NBA pocket builder. Single-model ranked opportunity
  rows now emit `edge_bucket`; combo rows emit `edge_bucket = None` for schema consistency.
- `eng/execution/build_ncaam_model_pockets.py` — same `edge_bucket` fix mirrored for NCAAM (no NCAAM
  trust dashboard yet).

## F. How to run

```
python 000_AUTO_BOOKIEX.py

python tools/analysis/analyze_nba_season_recap.py --play-in-start-date 2026-04-14 --playoff-start-date 2026-04-18 --min-sample-size 20

python tools/analysis/analyze_nba_pocket_robustness.py --play-in-start-date 2026-04-14 --playoff-start-date 2026-04-18 --min-keep-sample 100 --min-post-sample 20 --emit-latest

python tools/backfill_nba_daily_views.py
```

## G. Dashboard behavior

- The NBA Pocket ROI View now has trust columns (Trust Rating, Trust Score, 2nd-Half ROI, Recent
  ROI, Postseason ROI, Robustness Warning, Recommendation).
- **Trust Rating is the decision layer.** Historical hot/warm/cold state is context only.
- When trust and historical state conflict, trust the Trust Rating.
- FADE/KILL rows are hidden by default; use the **Show FADE / KILL pockets** checkbox to reveal them.
- The **How to read Pocket ROI View** expander explains every field and the two-layer model.
- If the NBA slate has no games (e.g. season over), the ranked board is empty, so the trust columns
  may not visibly populate even though the artifact and join logic are present.

## H. Known limitations

- NBA only for the dashboard trust layer.
- NCAAM has the `edge_bucket` fix but no trust dashboard yet.
- Robustness uses historical backtest data; it is not proof of future profitability.
- Postseason samples can be thin.
- The repo has many unrelated pending changes (modified/deleted/untracked).

## I. Recommended next steps

1. Confirm the deployed Streamlit shows the **How to read Pocket ROI View** expander.
2. Run full automation once and verify `nba_pocket_robustness_latest.json` updates.
3. Add NCAAM robustness only after the NBA trust layer is stable.
4. Consider adding dashboard controls later for robustness thresholds.
5. Eventually clean or isolate unrelated working-tree changes.

## Important pushed commits

- `b73617c0` — Backfill NBA daily views for May 2026 gap
- `68247a2d` — Add NBA pocket robustness trust layer
- `b94f2be5` — Add NBA season recap analysis tool

## Safety reminder

- Do **not** run `git add .` — the working tree has many unrelated changes.
- Use targeted `git add <path>` only.
