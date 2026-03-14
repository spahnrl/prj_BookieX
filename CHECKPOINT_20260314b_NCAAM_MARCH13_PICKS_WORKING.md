# Checkpoint — 2026-03-14 — NCAAM March 13 Picks Working

---

## 1. Objective

Fix the remaining no-pick problem so NCAAM March 13 (and other) rows that have market lines can produce actionable spread/total picks and non-IGNORE confidence tiers in the daily view and UI.

---

## 2. What was fixed in this final step

- After slate restoration, March 13 rows with lines still showed "Take No Spread Pick / No Total Pick — IGNORE | 0%".
- Review confirmed that `home_avg_points_for`, `home_avg_points_against`, `away_avg_points_for`, and `away_avg_points_against` were not reaching the model runner (0051); the authority model (`ncaam_avg_score_model`) requires all four to produce picks.
- The 0051 NCAAM path loaded only `load_game_state("ncaam")` (041 output: `ncaam_canonical_games_with_lines.json`) and never merged the existing feature table produced by 001/099.

---

## 3. Root cause confirmed

- **Artifact gap:** `eng/pipelines/ncaam/c_ncaam_001_build_avg_score_features.py` computes the four avg_score fields and writes them to `ncaam_game_level_with_avg_features.csv`; `c_ncaam_099_merge_model_features.py` carries them into `data/ncaam/model/ncaam_model_input_v1.csv`. The model runner (`eng/models/shared/model_gen_0051_runner.py`) loads only 041's game-state JSON and never merged that CSV, so games passed to the models had no avg_score inputs.

---

## 4. Change made

- **eng/models/shared/model_gen_0051_runner.py:** In `run_ncaam()`, after `games = load_game_state("ncaam")`, the runner now loads `data/ncaam/model/ncaam_model_input_v1.csv`, indexes it by `canonical_game_id`, and for each game merges in the following keys when present and when the game does not already have a non-empty value:
  - `home_avg_points_for`
  - `home_avg_points_against`
  - `away_avg_points_for`
  - `away_avg_points_against`
  - optionally: `home_games_in_history`, `away_games_in_history`
- If the feature CSV is missing, games are left unchanged and a log line reports that no feature table was found.
- Logging added: total games loaded, count enriched with all four avg fields, count still missing avg after merge.

---

## 5. Observed results

- Latest run output showed:
  - `NCAAM avg features:   merged from ncaam_model_input_v1.csv; enriched=4986, still_missing_avg=1148`
  - `Active rows: 3599`
  - `Daily rows: 38`
  - `Rows with spread picks: 4`
  - `Rows with total picks: 6`
  - `Rows with any picks: 6`
- The NCAAM March 13 UI now shows actual picks and non-IGNORE confidence tiers for at least some games.
- The project moved from "missing slate / all IGNORE" to "working downstream picks with some remaining coverage/quality limitations."

---

## 6. Current known-good state

- NCAAM March 13 slate is present downstream; 041 provides lines for a subset of March 13 rows.
- 0051 NCAAM now bridges the artifact gap between 041 game-state input and 099 feature output by merging avg_score (and optional history) fields from `ncaam_model_input_v1.csv` before running the model registry.
- The authority model receives avg_score inputs for games that exist in the feature table; those games can produce spread/total picks and non-IGNORE tiers when lines are also present.
- This was the final blocker for March 13 actionable picks; remaining issues are now polish/coverage, not pipeline survival.

---

## 7. Remaining optional follow-ups

- Increase coverage: more games with lines and/or more games with avg_score features in the feature table (022/001/099 pipeline and run order).
- Odds feed coverage: a portion of March 13 (and other) games remain without lines because the odds source does not list those matchups; no code change for that.
- Ranking, presentation, and execution-overlay polish for the daily view and UI.

---

## 8. Recommended next chat scope

- Optional: improve coverage (feature pipeline run order, date range, or diagnostics for still_missing_avg).
- Optional: improve one-sided TBD fallback or odds matching for edge cases.
- Keep focus on coverage/quality polish; do not revisit ingestion, canonical admission, or 041 line-join logic unless new evidence of regression appears.

---

## 9. Files changed in this step

| File | Change |
|------|--------|
| `eng/models/shared/model_gen_0051_runner.py` | In `run_ncaam()`, after loading game state, load `ncaam_model_input_v1.csv`, index by `canonical_game_id`, merge avg_score (and optional history) fields into each game when present and non-overwriting; add log counts for enriched vs still_missing_avg. |
