# Checkpoint — 2026-03-14 — NCAAM March 13 Slate Restored

---

## 1. Objective

Restore the NCAAM March 13 slate so games appear downstream (daily view, UI) instead of being missing or blank, and ensure the pipeline does not preserve stale TBD matchups.

---

## 2. What was broken

- NCAAM March 13 slate was previously missing or blank downstream (e.g. daily view showed 0 or very few rows for that date).
- Canonical row count was far lower than raw schedule event count; many games never reached 021 or 041.
- Many tournament games with one known team and one TBD opponent were dropped before canonical.
- After canonical was fixed, 041 still loaded only the old model-input artifact (4451 rows) instead of the fresh canonical output (6098 rows).
- Stale per-date raw schedule files caused TBD opponents to persist even when ESPN had already resolved the matchup.

---

## 3. Root causes confirmed

- **Stale reuse of per-date NCAAM raw schedule files** in `b_gen_001_ingest_schedule.py`: when `ncaam_schedule_raw_YYYYMMDD.json` existed and was valid, the ingest skipped the ESPN fetch for that date and reused the file, preserving old TBD rows.
- **041 reading the wrong NCAAM input:** `f_gen_041_add_betting_lines.py` was still reading `data/ncaam/model/ncaam_model_input_v1.csv` (old artifact) instead of the fresh canonical CSV produced by `d_gen_021_build_canonical_games.py`.
- **Canonical admission rule:** `d_gen_021_build_canonical_games.py` required both team IDs to be present; one-sided TBD tournament rows were excluded with `no_team_ids_no_backfill`.
- **Team-name resolution gaps:** Some named games failed to resolve in `b_gen_003_join_schedule_teams.py` due to incomplete team map or alias coverage, and there was no explicit visibility into unresolved vs TBD rows.

---

## 4. Changes made

- **b_gen_001_ingest_schedule.py:** NCAAM no longer reuses existing per-date raw files during current runs; each run fetches fresh ESPN scoreboard payloads for each requested date. Per-date cache files are still written, but events where either competitor is literally `TBD` are excluded from the written cache so future reuse (if reintroduced) would not persist stale TBD. Helpers added: `_ncaam_event_has_tbd`, `_ncaam_event_competitor_name`. One log line: "NCAAM ingest policy: always fetch fresh per-date scoreboard payloads (no raw reuse)"; per-date log includes fetched count, excluded TBD count, and count written to cache.
- **b_gen_003_join_schedule_teams.py:** Unresolved diagnostics added: `ncaam_schedule_unresolved_diagnostics.json` with `tbd_rows` vs `named_unresolved_rows`, `candidate_alias_map_add_list`, and summary counts. Matching improved: state semantics extended so norm keys containing `"state"` match map entries (e.g. Kennesaw State Owls → Kennesaw St.); `NCAAM_ALIAS_MAP` in `utils/mapping_helpers.py` extended (Southern Jaguars, Arkansas-Pine Bluff Golden Lions, Western Kentucky Hilltoppers, Kennesaw State Owls). Logs now surface NAMED-BUT-UNRESOLVED count and path to diagnostics.
- **d_gen_021_build_canonical_games.py:** One-sided TBD admission: when exactly one team ID is present and the other is missing (placeholder/TBD), the missing side is filled with deterministic placeholders (`tbd_<espn_game_id>_home` / `tbd_<espn_game_id>_away`, display `TBD_HOME` / `TBD_AWAY`). Rows admitted this way are marked with `admission_tbd_placeholder` (`"home"` or `"away"`). Exclusion diagnostics added: `ncaam_canonical_excluded_diagnostics.json` with per-row exclusion reason, mapping source, and march13_focus section. Both-sides-unresolved rows remain excluded.
- **f_gen_041_add_betting_lines.py:** NCAAM input source switched from `MODEL_DIR / "ncaam_model_input_v1.csv"` to `get_canonical_games_csv_path("ncaam")` (fresh canonical from 021). One log line: "NCAAM 041 input (canonical from 021): <path>". One-sided TBD fallback added: for games with exactly one placeholder side, match odds by known team + slate/date; if exactly one candidate market row, accept as fallback and set `line_join_method = "one_sided_known_team_fallback"`; if zero or multiple candidates, leave unmatched and set `line_join_method` to `one_sided_fallback_miss` or `one_sided_known_team_ambiguous`. Diagnostics: fallback matched, ambiguous, and miss counts logged.

---

## 5. Observed results

- Canonical row count increased materially (e.g. from 4451 to 6098 after TBD placeholder admission and 003 alias hardening).
- 041 now loads the same row count as canonical (6098) instead of the old model input (4451).
- After a full rerun (001 → 003 → 021 → 041 and downstream), the NCAAM March 13 slate appears in the UI; games are no longer missing and TBD rows no longer dominate due to stale cache.
- Downstream artifacts (daily view, final view) now receive more NCAAM rows; the problem space has narrowed from "missing slate" to "pick/actionability quality."

---

## 6. Current known-good state

- NCAAM schedule ingest always fetches fresh per-date payloads; per-date cache files do not persist TBD events.
- 003 emits unresolved diagnostics and improved alias/state matching; more named games resolve.
- 021 admits one-sided TBD games with deterministic placeholders and writes exclusion diagnostics.
- 041 reads canonical from 021 and applies one-sided fallback matching for TBD games; `line_join_method` and fallback counts are logged.
- March 13 slate is present in the UI; no longer blank or dominated by stale TBD.

---

## 7. Open issue(s)

- The current remaining issue is not missing games; it is that many games still show **"Take No Spread Pick / No Total Pick — IGNORE | 0%"** (pick/actionability quality rather than presence).

---

## 8. Recommended next chat scope

- Focus on why many NCAAM March 13 (and similar) rows remain IGNORE / 0%: odds matching quality, line availability, or model/arbitration logic that results in no spread/total pick.
- Optionally reintroduce conditional reuse of per-date raw cache (e.g. reuse only when the cached file contains no TBD events for that date) to reduce API load while avoiding stale TBD propagation.

---

## 9. Files changed in this recovery cycle

| File | Change |
|------|--------|
| `eng/pipelines/shared/b_gen_001_ingest_schedule.py` | Removed per-date raw reuse; always fetch. Per-date cache write excludes TBD events; helpers and logging added. |
| `eng/pipelines/shared/b_gen_003_join_schedule_teams.py` | Unresolved diagnostics (tbd vs named_unresolved), candidate alias list, state-in-name matching, NCAAM_ALIAS_MAP additions. |
| `eng/pipelines/shared/d_gen_021_build_canonical_games.py` | One-sided TBD placeholder admission; exclusion diagnostics; `admission_tbd_placeholder` field. |
| `eng/pipelines/shared/f_gen_041_add_betting_lines.py` | NCAAM input from `get_canonical_games_csv_path("ncaam")`; one-sided fallback matching; `line_join_method`; fallback diagnostics. |
| `utils/mapping_helpers.py` | NCAAM_ALIAS_MAP entries: Southern Jaguars, Arkansas-Pine Bluff Golden Lions, Western Kentucky Hilltoppers, Kennesaw State Owls. |

Other files (e.g. `eng/daily/build_daily_view_ncaam.py`, `build_gen_daily_view.py`, `model_gen_0052_add_model.py`, `utils/datetime_bridge.py`) were modified in earlier related work (final-view contract, slate_date_cst, daily input source); they are part of the overall March 13 recovery context but not the minimal set changed in this specific "slate restored" cycle.
