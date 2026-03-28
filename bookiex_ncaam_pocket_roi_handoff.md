# BookieX — NCAAM Pocket ROI implementation handoff

**Checkpoint date:** 2026-03-28  
**Scope:** NCAAM only for this layer (mirrors the NBA Pocket ROI pattern).  
**Purpose:** Single reference after completing the NCAAM port; safe freeze before GitHub push.

---

## 1. Purpose of the NCAAM Pocket ROI layer

Expose **historical pocket performance** (single-model and combo pockets) against the **current live slate** in a **read-only** UI lens. It does **not** change pick authority, sizing, or model arbitration for NCAAM. Operators can compare **how the slate lines up** with pocket / ROI history without mutating upstream pipeline outputs.

---

## 2. What is implemented

- **Model-level pockets** and **combo pockets** computed in execution and written as JSON (same statistical pattern as NBA).
- **Full current** and **live-slate** pocket game views for NCAAM (`final_game_view_ncaam.json` scope + latest `daily_view_ncaam_*_v1.json` order).
- **Live pocket leaderboard** (pair/triple spread & total combos, single-model lanes, cluster / pass / cold diagnostics — spread-first emphasis where applicable).
- **Leaderboard validation** artifact (tercile / historical diagnostics, same methodology family as NBA).
- **Per-game collapse:** `ncaam_best_pocket_per_game.json`.
- **Ranked opportunities:** `ncaam_ranked_pocket_opportunities.json` — one row per ROI-backed opportunity on the live slate, globally ranked.
- **Dashboard:** **Standard Slate View** vs **Pocket ROI View** for **NCAAM** (same UX family as NBA).
- **No NBA-only model exclusions:** NCAAM registry is avg score, momentum5, market pressure — **`EXCLUDED_MODELS` is empty** in `build_ncaam_model_pockets.py`.

---

## 3. Exact files changed (implementation + maintenance surfaces)

| Area | File |
|------|------|
| Artifact generation | `eng/execution/build_ncaam_model_pockets.py` |
| Validation companion | `eng/execution/build_ncaam_pocket_leaderboard_validation.py` |
| Dashboard UI, loaders, slate resolver, Pocket ROI view | `eng/ui/bookiex_dashboard.py` |
| Runner registration | `000_RUN_ALL_NCAAM.py` (runs `build_ncaam_model_pockets.py` after dynamic 039b) |
| Daily push staging | `tools/push_daily.py` (NCAAM pocket JSON globs + script paths) |
| Changelog | `CHANGELOG.MD` |
| This handoff | `bookiex_ncaam_pocket_roi_handoff.md` |

*NBA counterparts remain `build_nba_model_pockets.py`, `build_nba_pocket_leaderboard_validation.py`, `000_RUN_ALL_NBA.py`, and the NBA sections of `bookiex_dashboard.py`.*

---

## 4. Exact artifacts created (names only)

Produced under the **latest NCAAM backtest directory** `data/ncaam/backtests/backtest_*/` when **`eng/execution/build_ncaam_model_pockets.py`** runs (after `backtest_games.json` exists). The dashboard resolves **latest** by newest `backtest_*` folder mtime unless files are rebuilt in-session.

| Artifact | Role |
|----------|------|
| `ncaam_model_pockets.json` | Single-model pocket stats (historical ROI, graded games, edge buckets, state). |
| `ncaam_model_combo_pockets.json` | Combo pocket stats (pair/triple per market). |
| `ncaam_current_game_pocket_view.json` | Pocket view for all games in final view scope. |
| `ncaam_live_game_pocket_view.json` | Pocket view sliced to **live slate** (from latest `daily_view_ncaam_*_v1.json`). |
| `ncaam_live_pocket_leaderboard.json` | Ranked live-slate rows: combos, singles, clusters, pass/cold, etc. |
| `ncaam_pocket_leaderboard_validation.json` | Historical validation / diagnostic companion. |
| `ncaam_best_pocket_per_game.json` | One consolidated **best pocket per game** row (spread-focused UI summary). |
| `ncaam_ranked_pocket_opportunities.json` | All ROI-backed opportunities on the live slate, one row each, globally ranked. |

---

## 5. Current dashboard behavior (NCAAM)

### Modes

- **Standard Slate View** — Default NCAAM slate experience; caption points users to Pocket ROI View for pocket boards.
- **Pocket ROI View** — Renders `_render_ncaam_pocket_roi_view` only: same major sections as NBA (ranked opportunities, pocket-type filter, parlay v1, best pocket per game expander, admin/debug, diagnostic tables, historical validation).

### Slate resolution

- **`_resolve_ncaam_pocket_slate_rows`** aligns daily JSON row order with pocket rows using **`identity.game_id` → `game_id` → `canonical_game_id` → `espn_game_id`** so NCAAM id fields match the final view / backtest join.

---

## 6. Current ranking / selection rules (ranked opportunities)

Same **concept** as NBA (see `build_ncaam_model_pockets.py` — `build_ncaam_ranked_pocket_opportunities`):

- **Combos:** From leaderboard lists `best_pair_spread`, `best_triple_spread`, `best_pair_total`, `best_triple_total` where `graded_games > 0`.
- **Singles:** `best_single_model_spread` / `best_single_model_total` joined to **`ncaam_model_pockets.json`** on `(model, market_type, edge_bucket)` with `graded_games > 0`.
- **Excluded:** Cluster-style slices without per-row historical ROI (same rule family as NBA).
- **Sort:** ROI descending, then `graded_games` descending, then `win_rate` descending; `rank` assigned after sort.
- **UI filter:** All / Spread Only / Total Only — **display only**; global `rank` unchanged when filtered.

---

## 7. Current parlay rules (v1)

Identical **behavior** to NBA Pocket ROI v1:

- **Spread-only** legs; `eligible_for_parlay` set in builder for spread + positive ROI + non-empty pick (totals not parlay-eligible).
- Walks the **full** ranked `opportunities` list in **global** order (not the filtered table), except **Total Only** → info message, no parlay build.
- First **two** eligible rows with **distinct** `game_id`.
- **Not** parlay EV math — diagnostic / entertainment framing in UI.

---

## 8. Validation findings (as of checkpoint)

- `python -m py_compile` on NCAAM pocket modules and dashboard passes in dev.
- `python eng/execution/build_ncaam_model_pockets.py` succeeds when a NCAAM backtest directory and `backtest_games.json` exist; validation JSON writes when combo + pocket inputs exist.
- Pocket ROI path is **read-only** with respect to authority; missing ranked/best JSON can be rebuilt in-session from leaderboard + pockets list (same pattern as NBA).
- **Manual:** Streamlit — league **NCAAM**, **Pocket ROI View**, exercise filters and parlay messaging under **Total Only**.

---

## 9. NCAAM-specific assumptions / adaptations

- **Models:** Three runners only (avg score, momentum5, market pressure) — **no injury / fatigue models** in pocket math.
- **Daily view glob:** `daily_view_ncaam_*_v1.json`; date key in filename uses the segment after `daily_view_ncaam_` (dashboard-aligned).
- **Game IDs:** Resolver prefers canonical / ESPN ids when `identity.game_id` is empty (common on NCAAM daily rows).
- **Exclusions:** No `MonkeyDarts_v2` (not in NCAAM registry); `EXCLUDED_MODELS` is empty.
- **Formulas:** Same -110 leg accounting and state thresholds as documented in artifact `formulas` metadata (aligned with NBA builder constants).

---

## 10. Known caveats

- **Sample depth:** Fewer models than NBA → fewer combo signatures; triples exist but the space is smaller.
- **Slate / leaderboard date drift:** If latest daily used for live slice date ≠ dashboard-selected date, UI warns (same class of issue as NBA).
- **Parlay:** Often **no** two distinct positive-ROI spread legs on thin slates — expected.
- **Single-model ranked rows** depend on a clean join to `ncaam_model_pockets.json`; missing pockets doc limits in-session rebuild for singles.

---

## 11. Recommended next step after checkpoint

- **Push:** Stage/commit with confidence — implementation is frozen at this handoff; this doc + `CHANGELOG.MD` are the pre-push record.
- **Optional follow-up:** Manual Streamlit pass on NCAAM Pocket ROI; tune operator-facing copy only if needed (no logic change required for parity).

**Cross-reference:** NBA spec and behavior — `bookiex_nba_pocket_roi_handoff.md` and `eng/execution/build_nba_model_pockets.py`.
