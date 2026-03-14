# Checkpoint: NCAAM historical odds and matching closeout (2026-03-13)

## Summary
- Matched rows: **3385 → 3678**. Unmatched: **1064 → 771**.
- Two bugs were fixed; remaining unmatched games are due to incomplete historical API coverage, not pipeline logic.

## Bugs fixed
1. **Finalized lock (f_gen_041):** Finalized games with existing previous state were always reusing that state and never applying current odds from the index. Now, when a finalized game previously had `line_join_status = unmatched` and current odds exist for the join key, current odds are applied instead of preserving the stale unmatched state. This allowed previously “stuck” unmatched games (e.g. 2025-11-03 St. Bonaventure vs Bradley, Ohio vs IUPUI, Winthrop vs Queens) to match after alias/canonical and raw backfill.
2. **Gap-fill covered dates (e_gen_031):** “Covered” was derived from every game’s `commence_time` in all raw files, so 2025-11-04 was incorrectly treated as covered when 20251103 contained games commencing 2025-11-04 UTC. Covered is now derived only from gap-fill snapshot filenames (`ncaam_odds_raw_YYYYMMDD.json`), so 2025-11-04 and other missing calendar days are fetched and written correctly.

## Remaining unmatched (provider coverage)
- Sampled 2025-11-04 games (e.g. TCU vs New Orleans, Ole Miss vs Louisiana, Bucknell vs Delaware) are **not** present in `ncaam_odds_raw_20251104.json`. The historical API response for that date included only a subset of games (e.g. 21); those matchups were not in the response.
- These cases correctly remain **missing_in_odds_source**. No pipeline change is required; any improvement would depend on provider historical coverage or alternate request parameters.