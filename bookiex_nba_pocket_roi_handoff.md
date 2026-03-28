# BookieX — NBA Pocket ROI implementation handoff

**Checkpoint date:** 2026-03-27  
**Scope:** NBA only. NCAAM is not implemented for this layer in this checkpoint.  
**Purpose:** Single reference before porting Pocket ROI concepts to NCAAM.

---

## 1. Purpose of the NBA Pocket ROI layer

Expose **historical pocket performance** (single-model and combo pockets) against the **current live slate** in a **read-only** UI lens. It does **not** change pick authority, sizing, or model arbitration. It helps operators compare **what the slate looks like** under pocket / ROI history without mutating pipeline outputs upstream of this view.

---

## 2. What is implemented

- **Model-level pockets** and **combo pockets** computed in execution and serialized to JSON.
- **Full current** and **live-slate** pocket game views for NBA.
- **Live pocket leaderboard** ranking live-slate games with best pair/triple spread & total combos, single-model hints, cluster / pass / cold diagnostic lanes (spread-first emphasis where applicable).
- **Leaderboard validation** artifact for spread-cluster and related diagnostics.
- **Per-game collapse:** `nba_best_pocket_per_game.json` — one summary row per live game (spread-focused consolidation for UI).
- **All-pocket ranked board:** `nba_ranked_pocket_opportunities.json` — one row per opportunity with historical ROI/sample where available; excludes cluster rows lacking per-row ROI on the leaderboard.
- **Dashboard:** Top-level **Standard Slate View** vs **Pocket ROI View** for NBA; Pocket ROI View hosts the tables, filter, parlay v1, expanders, and diagnostics.
- **MonkeyDarts_v2** is **excluded** from pocket math in `build_nba_model_pockets.py`.

---

## 3. Primary implementation files (code)

| Area | File |
|------|------|
| Artifact generation | `eng/execution/build_nba_model_pockets.py` |
| Dashboard UI, loaders, filter, parlay | `eng/ui/bookiex_dashboard.py` |
| Runner registration | `000_RUN_ALL_NBA.py` (lists `build_nba_model_pockets.py` in execution chain) |
| Daily push staging (optional) | `tools/push_daily.py` (NBA backtest JSON globs) |

*This checkpoint doc does not list every historical edit; the above are the active maintenance surfaces.*

---

## 4. NBA pocket artifacts (exact names)

All of the following are produced under the **latest NBA backtest directory** `data/nba/backtests/backtest_*/` when **`eng/execution/build_nba_model_pockets.py`** runs (after a backtest exists). The dashboard resolves **“latest”** by newest `backtest_*` folder mtime unless rebuilt in-session.

| Artifact | Role |
|----------|------|
| `nba_model_pockets.json` | Single-model pocket stats (historical ROI, graded games, buckets, etc.). |
| `nba_model_combo_pockets.json` | Combo pocket definitions/stats. |
| `nba_current_game_pocket_view.json` | Pocket view for all games in the final view scope. |
| `nba_live_game_pocket_view.json` | Pocket view sliced to the **live slate** (from latest daily view convention). |
| `nba_live_pocket_leaderboard.json` | Ranked live-slate rows: best combos, singles, clusters, pass/cold lanes, etc. |
| `nba_pocket_leaderboard_validation.json` | Validation / diagnostic companion for leaderboard (spread cluster, etc.). |
| `nba_best_pocket_per_game.json` | One consolidated **best pocket per game** row (UI summary). |
| `nba_ranked_pocket_opportunities.json` | **All** ROI-backed opportunities on the live slate, one row each, globally ranked. |

---

## 5. Current dashboard behavior (NBA)

### Two top-level modes

- **Standard Slate View** — Default NBA game/slate experience; caption points users to Pocket ROI View for pocket boards.
- **Pocket ROI View** — Renders `_render_nba_pocket_roi_view` only: pocket artifacts, ranked table, parlay, secondary BPP expander, admin, diagnostics.

### Pocket ROI View contents (in rough order)

1. **Ranked Pocket Opportunities** — Table from `nba_ranked_pocket_opportunities.json` (or in-session rebuild from leaderboard + `nba_model_pockets.json` pockets list). **Pocket type filter** (`st.radio`): *All Pockets* / *Spread Only* / *Total Only* — filters **display rows only**; does not rewrite artifacts.
2. **Best pocket per game (secondary summary)** — Collapsed expander; `nba_best_pocket_per_game.json` (or rebuild from leaderboard).
3. **Best 2-leg parlay (positive ROI only)** — v1 rules below.
4. **NBA pocket admin / debug** — Paths, slate counts, parlay-eligible pool count, artifact load flags.
5. **Detailed diagnostic pocket tables** — Live spread-first tables, formulas expander, historical leaderboard validation tables.

---

## 6. Current selection / ranking rules (ranked opportunities artifact)

- **Sources:** Leaderboard lists `best_pair_spread`, `best_triple_spread`, `best_pair_total`, `best_triple_total` (rows with `graded_games > 0`); `best_single_model_spread` / `best_single_model_total` joined to `nba_model_pockets.json` via `(model, market_type, edge_bucket)` with `graded_games > 0`.
- **Excluded from ranked file:** Leaderboard slices without usable per-row historical ROI for ranking (e.g. cluster-primary rows as noted in builder `notes`).
- **Sort (global):** ROI descending, then `graded_games` descending, then `win_rate` descending. Row `rank` is assigned after sort.
- **Display filter (UI):** Spread = `market_type == "spread"` or `pocket_type` suffix `_spread`; Total = `market_type == "total"` or suffix `_total`. **Rank column** stays the **global** rank from the JSON even when the table is filtered.

---

## 7. Current parlay rules (v1)

- **Spread-only:** Only rows with `eligible_for_parlay` (set in builder for spread + positive ROI + pick present; totals are not parlay-eligible).
- **Pool order:** Always walks the **full** `opportunities` list in **global rank order** (not the filter-trimmed table), except when the user selects **Total Only** — then **no** parlay is built; UI shows an info message that parlay is spread-only v1.
- **Legs:** First **two** rows with `eligible_for_parlay` and **distinct** `game_id`.
- **Copy:** Not parlay EV math — entertainment / diagnostic framing in UI.

---

## 8. Validation findings (as of checkpoint)

- Python compile checks on touched modules pass in dev sessions.
- Pocket ROI path is **read-only** relative to authority; missing ranked/best-pocket files can be rebuilt in-session from leaderboard + pockets.
- **Manual:** Run Streamlit and flip Standard vs Pocket ROI, all three pocket-type filters, and confirm parlay message under **Total Only**.

---

## 9. Known caveats

- **NCAAM:** No equivalent pocket ROI dashboard or artifact set in this checkpoint.
- **Single-model rows** in ranked opportunities need a clean join to `nba_model_pockets.json`; missing pockets doc limits in-session rebuild enrichment for singles.
- **Cluster** opportunities are not fabricate-ranked in `nba_ranked_pocket_opportunities.json` without historical ROI on the leaderboard row.
- **Parlay** does not use totals; **All Pockets** table can show totals while parlay still pulls spread legs from the full list by global order.

---

## 10. Recommended next step

**NCAAM port (next chat):** Mirror the **concept** (artifacts + dashboard lens + read-only guarantees) for NCAAM with league-appropriate paths and keys, without breaking NBA behavior. Start from this doc + `eng/execution/build_nba_model_pockets.py` + `eng/ui/bookiex_dashboard.py` Pocket ROI blocks as the functional spec.
