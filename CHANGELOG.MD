
# CHANGE LOG — prj_BookieX

**Session Date:** 2026-01-16
**Status:** ✅ Stable Stop Point
**Focus:** NBA data ingestion pipeline (schedule → rest → OT → fatigue)

---

## ✅ Major Accomplishments

### 1. Established Deterministic Data Pipeline Order

Confirmed and enforced **strict forward-only ingestion**.
No script reads data generated later in the chain.

**Current `a_data` Order:**

1. `a_data_001_ingest_schedule.py`
2. `a_data_002_team_map.py`
3. `a_data_003_join_schedule_teams.py`
4. `a_data_004_ingest_boxscores.py`
5. `calc_005_compute_team_rest_days.py`
6. `calc_006_add_b2b_flags.py`
7. `calc_007_compute_fatigue_score.py`

Each stage:

* Reads **only** the immediately prior output
* Writes a new derived artifact
* Is independently runnable and debuggable

---

### 2. Resolved NBA API Reliability Issues

* Encountered multiple **403 and SSL failures** from NBA endpoints
* Switched to **CDN-safe, working endpoints**
* Added defensive request handling:

  * timeouts
  * graceful failures
  * default fallbacks

**Outcome:** Pipeline no longer fails hard due to network instability.

---

### 3. Implemented Overtime Detection (OT Flags)

Added OT enrichment via boxscore ingestion:

* `went_ot`
* `ot_minutes`
* `home_went_ot`
* `away_went_ot`

**Design decision:**

* OT is **flagged**, not filtered
* No boxscore scoring logic added yet (future-safe)

---

### 4. Added Observability to Long-Running Jobs

Improved UX for slow, network-bound steps:

* Progress logging (`Processed X / N games`)
* Visible confirmation of forward progress
* Prevented false “hung process” assumptions

This directly prevented accidental job termination and data loss.

---

### 5. Fixed JSON Write / Read Integrity Issues

* Identified partial-write JSON causing `JSONDecodeError`
* Ensured:

  * writes occur only after full completion
  * downstream jobs read valid, complete artifacts

Pipeline now fails **early and clearly** when inputs are missing or invalid.

---

### 6. Clarified Season / Preseason Handling

* Season classification derived from NBA schedule metadata
* No betting logic or season filtering applied yet
* Preseason games remain present and flagged (future decision point)

---

### 7. Defined Next Data Layer: Betting Lines (Not Implemented)

Explicitly deferred betting-line ingestion due to:

* Paid data access via Joel
* Possible private API or scrape source
* Need to align on access and legality

**Locked-in design decision:**

* Betting lines treated as **exogenous market data**
* Ingested via **CSV or paid API**
* Joined *after* fatigue metrics
* Never inferred or recomputed

---

## 📌 Current Stable Outputs

* `nba_games_with_ot.json`
* `nba_games_with_b2b.json`
* `nba_games_with_fatigue.json`
* Corresponding CSVs in `data/derived/`

All artifacts verified present and consistent.

---

## 🛑 Intentional Stop

Pipeline is now:

* Correct
* Observable
* Deterministic
* Extendable

Next step is a **data-source decision**, not code.

---
Absolutely — here’s a **clean, end-to-end CHANGELOG / session markdown** you can drop straight into `CHANGELOG.md` or OneNote.
This captures **the entire chat**, decisions, bugs, fixes, and the final stable architecture.

---

**Session Date:** 2026-01-23
**Session:** NBA Fatigue → Betting Lines Integration
**Status:** ✅ Stable / Canonical
**Outcome:** One-record-per-game dataset with fatigue + market lines
**Stop Point:** Analytics-ready, no plumbing debt

---

## 🎯 Session Goal

Extend the completed **NBA fatigue pipeline** to safely ingest and join **betting market data** (spreads, totals, moneylines) **without violating deterministic, forward-only design rules**.

This session focused on **data correctness**, not modeling or betting decisions.

---

## 🧱 Baseline (Confirmed at Start)

### Verified Pipeline (Locked)

**Ingestion**

1. NBA schedule
2. Team metadata
3. Schedule ↔ team join
4. Boxscores (OT flags only)

**Derived Metrics**
5. Rest days
6. B2B / B2B2B flags
7. Fatigue score

**Design Rules**

* Forward-only ingestion
* CSV + JSON at every step
* No inferred betting data
* Audit-safe, reproducible

---

## ✅ Major Accomplishments (Chronological)

---

### 1. Betting Data Source Selected

**Decision:** Use **The Odds API**
**Reasoning:**

* Free tier available
* Supports NBA + other sports
* Real-time odds (not just historical)
* Multiple bookmakers per game

**Clarified API Behavior**

* One API call returns **all games** for a sport
* Call limits apply per request, not per game
* Odds timestamps are **UTC-based**

---

### 2. Betting Line Ingestion Implemented

Created a dedicated betting ingestion step that:

* Pulled current odds into `odds_api_current.csv`
* Preserved **one row per outcome per bookmaker**
* Did **not** infer or normalize prices

This preserved raw market truth for later aggregation.

---

### 3. Canonical Game-Day Problem Discovered

**Symptom**

* Odds missing for “today’s” games
* West coast games frequently unmatched

**Root Cause**

* NBA schedule dates = **local game day**
* Odds API dates = **UTC start time**
* Evening games spill into the *next UTC day*

**Example**

```
NBA schedule: 2026-01-23
Odds API:     2026-01-24T03:10:00Z
```

Same game — different calendar day.

---

### 4. Canonical Join Strategy Defined (Critical Fix)

Introduced a **reusable `canonical_game_day`**:

```text
YYYY-MM-DD
```

**Design Decision**

* Canonical day becomes the **join backbone**
* Applied upstream, reused everywhere
* Required for odds, injuries, refs, future joins

---

### 5. ±1 Day Tolerance Added (Industry Standard)

To safely handle UTC/local drift:

* Odds indexed by canonical day
* Game joins allow:

  * same day
  * +1 day
  * −1 day

This eliminated false negatives **without introducing duplicates**.

---

### 6. Upstream File Fixed (Authoritative)

Updated:

```
b_data_003_join_schedule_teams.py
```

**Added**

* `canonical_game_day`
* Persisted into JSON + CSV
* Became the **source of truth** for downstream joins

This unlocked all later fixes.

---

### 7. One-Record-Per-Game Model Finalized

Resolved confusion between:

* one row per team
* one row per game

**Final Model**

* Exactly **one row per game**
* Explicit `home_*` and `away_*` fields
* No loss of team-level metrics

This enabled clean market comparisons.

---

### 8. Betting Lines Successfully Joined

Final script:

```
nba_03_add_betting_lines.py
```

**Attached**

* Spread (home / away)
* Total
* Moneyline (home / away)

**Key Properties**

* Uses `canonical_game_day`
* ±1 day tolerant
* Handles multiple bookmakers
* Produces:

  * JSON (nested betting object)
  * CSV (flattened review-friendly)

---

### 9. Permissions & Output Stability Fixed

Resolved:

* Windows CSV permission errors
* Partial-write risks
* Directory creation issues

Ensured:

* Deterministic writes
* Safe reruns
* No file locking surprises

---

## 📦 Final Stable Outputs

### Game-Level (No Odds)

```
data/view/nba_games_game_level.json
data/view/nba_games_game_level.csv
```

### Game-Level + Betting Lines

```
data/view/nba_games_game_level_with_odds.json
data/view/nba_games_game_level_with_odds.csv
```

Each row now answers:

* Who played?
* Home / away?
* Rest & fatigue context?
* OT impact?
* Market expectations?

---

## 🧠 Key Design Decisions (Locked)

* Betting data is **exogenous**
* No inferred lines
* No price averaging yet
* Canonical day is the join spine
* ±1 day tolerance is mandatory

---

## 🛑 Intentional Stop Point

Plumbing is **complete and correct**.

Next steps are **pure analytics**, not engineering:

* Fatigue vs spread delta
* Total projection vs O/U
* Market mispricing detection
* Backtest logic (future sprint)

---

## ✅ Session Outcome

**Status:** 🟢 Production-grade data foundation
**Risk:** Low
**Technical Debt:** None
**Ready for:** Analysis, modeling, portfolio demo

---

**Session Date:** 2026-01-24
**Project:** prj_BookieX
**Component:** NBA Projection & Bet Explanation Layer
**Status:** ✅ Stable / Canonical
**Scope:** Baseline betting model (Joel) + human-readable parlay output

---

## 🎯 Purpose

Introduce a **deterministic, auditable projection layer** on top of
`nba_games_game_level_with_odds`, producing:

* Explicit **spread & total bets**
* Quantified **edges vs market**
* A **human-readable explanation** suitable for parlays
* No filtering, no row removal, no inference beyond defined formulas

---

## 🧱 Baseline (Starting Point)

**Input**

* `nba_games_game_level_with_odds.json`
* One record per game
* Betting lines present (spread, total, moneyline)
* No projections or bet logic

**Constraints**

* Forward-only pipeline
* CSV + JSON outputs
* JP_Edit column compatibility
* Audit-safe, deterministic math only

---

## ✅ Development Milestones (Chronological)

---

### 1️⃣ Joel Baseline Projection Model Implemented

Added explicit projections using Joel’s formulas:

* **Projected Home Score**
  `avg(home_avg_points_for, away_avg_points_against)`
* **Projected Away Score**
  `avg(home_avg_points_against, away_avg_points_for)`
* **Total Projection**
  `Projected Home + Projected Away`
* **Home Line Projection**
  `Projected Away − Projected Home`

No fatigue adjustments applied at this stage.

---

### 2️⃣ Spread & Total Bet Decisions Added

Derived deterministic bet directions:

* **Line Bet**

  * HOME / AWAY / PUSH
* **Total Bet**

  * OVER / UNDER / PUSH

Rules:

* Comparison only vs market lines
* No thresholds
* No confidence filtering

---

### 3️⃣ Strict JP_Edit Column Alignment Enforced

Ensured **1:1 column parity** with `nba_games_game_level_with_odds_JP_Edit.csv`:

* Matched column names and order
* Preserved existing market fields
* Deferred `Line Result` as post-game placeholder

This eliminated ambiguity when comparing CSVs side-by-side.

---

### 4️⃣ Betting Fields Fully Flattened

Resolved structural mismatch:

* Removed nested `betting` object
* Broke out:

  * `spread_home`
  * `spread_away`
  * `total`
  * `moneyline_home`
  * `moneyline_away`

Flattening applied **without removing data**, preserving compatibility with Excel and downstream tooling.

---

### 5️⃣ Edge Metrics Introduced (Key Enhancement)

Added explicit separation-from-market metrics:

* **Spread Edge**
  `|Projected Margin − Market Spread|`
* **Total Edge**
  `|Projected Total − Market Total|`
* **Parlay Edge Score**
  `Spread Edge + Total Edge`

These are **confidence / ranking metrics**, not probabilities.

---

### 6️⃣ Human-Readable Explanation Column Added

Introduced **`Explanation`** column to describe bets in plain English.

Final format (ASCII-safe):

```
Take Detroit Pistons -2.5. Model projects win by 7.0 (edge +4.5).
Take OVER 214.5. Model total 228.4 (edge +13.9).
Combined parlay edge score: 18.4
```

Properties:

* One or two legs per game
* PUSH legs omitted
* Parlay-ready wording
* Copy/paste friendly

---

### 7️⃣ Encoding Issue Identified & Resolved

**Issue**

* UTF-8 em dash (`—`) rendered as `â€”` in CSV / Excel

**Fix**

* Replaced em dash with sentence breaks (`.`)
* Capitalized “Model” for clarity

Result:

* CSV-safe
* Excel-safe
* JSON-safe
* No encoding flags required

---

### 8️⃣ Data Integrity Rules Locked

Confirmed and enforced:

* ❌ No filtering
* ❌ No row removal
* ❌ No conditional inclusion
* ✅ All games preserved
* ✅ Additive columns only

---

## 📦 Final Outputs

* `nba_games_game_level_with_odds_model.json`
* `nba_games_game_level_with_odds_model.csv`

Each row now includes:

* Market lines
* Model projections
* Bet directions
* Edge metrics
* Human-readable parlay explanation

---

## 🧠 Design Decisions (Locked)

* This file = **baseline model only**
* Fatigue adjustments belong in `nba_05_*`
* Result evaluation belongs in `nba_06_*`
* Edge score is **ranking signal**, not probability
* Explanation column is authoritative human output

---

## 🛑 Stable Stop Point

`nba_04_add_model.py` is now:

* Deterministic
* Auditable
* Excel-safe
* Parlay-ready
* Architecturally clean

**Next logical steps (out of scope here):**

* Fatigue deltas
* Edge thresholds
* Parlay construction logic
* Backtesting / grading

---

# CHANGELOG — prj_BookieX

## NBA Odds Integration, Time Normalization & Explanation Enhancements

**Session Date:** 2026-01-25
**Status:** ✅ Stable / Canonical Stop
**Scope:** Odds ingestion, time correctness, explainability, and auditability
**Rule Enforced:** Additive changes only — no data removed

---

## 🎯 Session Goal

Improve the NBA betting pipeline so that:

* **Real game start times** (from odds data) flow through the system
* Odds can be **historically backtested** without date hacks
* All joins are **auditable and explainable**
* Human-readable betting explanations include **time + model context**
* CSV outputs remain readable and consistent with prior versions

---

## ✅ Additions & Enhancements (What Changed)

### 1️⃣ Real Odds-Based Game Time Added (Authoritative)

Added **explicit game tip time from the Odds API** as first-class data:

* `odds_commence_time_utc`
  *True scheduled tip time (UTC) from market data*
* `odds_commence_time_cst`
  *Human-readable Central Time conversion*

**Why this matters**

* Eliminates reliance on fake midnight NBA `game_date`
* Removes need for ±1 day matching hacks
* Enables honest backtesting and downstream joins

---

### 2️⃣ Odds Snapshot Timing Added (Backtest Safety)

Added:

* `odds_snapshot_utc`

This records **when the betting market was observed**, allowing:

* Verification that odds existed **before tip**
* Prevention of look-ahead bias
* Clear audit trails for historical analysis

---

### 3️⃣ Explicit Odds Match Audit Field Added

Added:

* `odds_match_method`

Purpose:

* Documents *how* odds were joined to games
* Makes joins explainable instead of implicit
* Future-proofs multi-source odds ingestion

---

### 4️⃣ No Data Removed (Schema Is Strictly Additive)

Confirmed and enforced:

* ❌ No rows filtered
* ❌ No columns removed
* ❌ No prior outputs altered
* ✅ All changes additive only

Previous CSVs remain fully comparable.

---

### 5️⃣ CSV Column Order Restored (Readability Fix)

Because schema-safe CSV writing reorders columns automatically, a **preferred column order** was reintroduced:

* Original column order preserved
* New odds time fields inserted **next to `game_date`**
* Technical audit fields placed at the end

This makes side-by-side review with older CSVs straightforward.

---

### 6️⃣ Human-Readable Explanation Enhanced (Context Added)

The `Explanation` column was enhanced to include **contextual headers** when (and only when) the model produces a betting signal:

**Prepended (non-destructive):**

* Tip Off time (CST)
* Model name

**Example output:**

```
Tip Off: 1/25/2026 at 7:10pm
Model: Fatigue_01 (JP)
Take Phoenix Suns -4.0. Model projects win by 7.0 (edge +3.0).
Take OVER 226.0. Model total 230.5 (edge +4.5).
Combined parlay edge score: 7.5
```

---

### 7️⃣ Explanation Guard Added (Bug Fix)

Fixed a logic issue where static text (e.g., model name) appeared even when:

* No spread pick
* No total pick
* No actionable signal

**Rule now enforced:**

> Explanations are generated **only if at least one betting signal exists**.

Games without signals have:

```
Explanation = None
```

---

### 8️⃣ Terminal Visibility Added (Developer UX)

Added **runtime logging** so every game that generates an explanation is printed to the terminal:

* `game_id`
* teams
* odds commence time (CST)
* full Explanation block

This removes the need to hunt through CSVs during development and debugging.

---

## 📦 Final Outputs (Stable)

* `nba_games_game_level_with_odds_model.json`
* `nba_games_game_level_with_odds_model.csv`

Each record now contains:

* Game identity & rest context
* Market lines
* Model projections
* Edge metrics
* **Authoritative tip time**
* **Market snapshot time**
* **Human-readable explanation with context**

---

## 🧠 Design Decisions (Locked)

* Odds data defines **game time**
* NBA schedule dates are **not authoritative for time**
* No inferred or averaged betting data
* Explanations imply **actionable signals only**
* Pipeline remains forward-only and auditable

---

## 🛑 Stable Stop Point

The BookieX NBA pipeline is now:

* Time-correct
* Backtest-safe
* Explainable
* CSV/Excel-friendly
* Ready for modeling extensions (fatigue deltas, thresholds, grading)

**Next steps are analytical, not plumbing.**

---

## CHANGELOG — Preseason Exclusion & Dual Aggregation Fix

**Session Date:** 2026-01-25
**Project:** prj_BookieX
**Component:** Team Averages (`data_006_calculate_team_averages.py`)
**Status:** ✅ Stable / Approved Design Implemented
**Scope Rule:** Additive only — no renames, no deletions, no downstream edits

---

### 🎯 Problem Identified

The downstream betting model was unintentionally using **preseason statistics**, which Joel explicitly does **not** want included in model calculations.

Constraints:

* ❌ No auditing or editing of ~10 downstream files
* ❌ No renaming or removal of existing fields
* ❌ No data loss (preseason stats must remain available)
* ✅ Playoffs must continue to be included

---

### 🧠 Root Cause Discovered

* Existing aggregation logic treated **all completed games equally**
* No reliable `is_preseason` flag existed in derived datasets
* As a result, “exclude preseason” logic never triggered
* This caused **identical values** between updated fields and new `_all` fields

---

### ✅ Key Design Decisions (Locked)

1. **Preseason detection is derived from `game_id`**, not missing flags
   NBA-standard encoding used:

   * `001xxxxxxx` → preseason
   * `002xxxxxxx` → regular season
   * `004xxxxxxx` → playoffs

2. **Preseason is excluded — not regular season**

   * Regular season **and playoffs** are included
   * Only preseason games are excluded from model-facing aggregates

3. **Single-file change strategy**

   * All logic isolated to `data_006_calculate_team_averages.py`
   * No downstream script changes required

---

### 🔧 What Changed (Technical Summary)

#### 1️⃣ Added Deterministic `season_type` Derivation

* New helper derives:

  * `preseason`
  * `regular`
  * `playoffs`
* Based solely on `game_id` prefix
* Improves transparency and auditability

#### 2️⃣ Updated Existing Aggregate Fields (Behavior Change Only)

Existing fields now represent:

> **Games that have been played AND are NOT preseason**
> (regular season + playoffs)

Affected fields (names unchanged):

* `games_played`
* `avg_points_for`
* `avg_points_against`
* `net_rating`

This fixes the model input **without touching downstream code**.

#### 3️⃣ Added New `_all` Fields to Preserve Legacy Behavior

New additive fields retain the original “ALL games” logic:

* `games_played_all`
* `avg_points_for_all`
* `avg_points_against_all`
* `net_rating_all`

This preserves preseason data for:

* presentations
* historical review
* exploratory analysis

---

### 🧪 Validation Outcome

* Identified that `_all` fields initially matched updated fields
* Traced issue to missing preseason detection
* Corrected via `game_id`-based classification
* Post-fix expectation:

  * `games_played_all ≥ games_played`
  * Differences visible for teams with preseason games

---

### 📦 Impact Summary

| Area             | Impact                         |
| ---------------- | ------------------------------ |
| Downstream model | ✅ Preseason excluded           |
| Playoffs         | ✅ Included                     |
| Existing fields  | ✅ Preserved (behavior updated) |
| New fields       | ✅ Added (legacy behavior)      |
| Data loss        | ❌ None                         |
| Downstream files | ❌ No changes                   |

---

### 🛑 Stable Stop Point

The pipeline now:

* Excludes preseason data **only where required**
* Preserves full historical data
* Remains forward-only, auditable, and deterministic
* Requires **zero downstream refactors**

Next work is optional validation or analytics — **no plumbing debt remains**.

---

# CHANGE LOG — prj_BookieX

## NBA 3PT Aggregation, Odds Join, and Model Visibility Pass-Through

**Session Date:** 2026-01-25
**Status:** ✅ Stable Stop Point
**Scope:** Team 3PT aggregation → odds join → model visibility
**Rule Enforced:** Additive only — no filtering, no row loss

---

## 🎯 Session Goal

Extend the NBA pipeline to:

* Aggregate **team-level recent 3PT shooting**
* Carry all new fields cleanly through **canonical → odds → model**
* Preserve **one-record-per-game** integrity
* Improve **model transparency**, not complexity

No strategy changes. No thresholds. No inference beyond defined math.

---

## ✅ Major Accomplishments

### 1️⃣ Team 3PT Aggregation Added (Recent Games)

Created and validated:

```
b_data_006_aggregate_team_3pt.py
```

**Outputs:**

* `nba_team_3pt_recent.json`
* `nba_team_3pt_recent.csv`

**Metrics (per team):**

* `team_3pm`
* `team_3pa`
* `team_3pt_pct`

**Properties:**

* Recent-window aggregation (deterministic)
* No preseason assumptions
* Fully auditable
* No dependency on betting data

---

### 2️⃣ Canonical → Game-Level Join Verified

Confirmed that aggregated 3PT metrics:

* Correctly join at **game level**
* Split into explicit fields:

```
home_team_3pm / 3pa / 3pt_pct
away_team_3pm / 3pa / 3pt_pct
```

No duplication, no row explosion, no silent drops.

---

### 3️⃣ Odds Attachment Layer Extended (Visibility Only)

Updated:

```
f_nba_0041_add_betting_lines.py
```

**Additions:**

* Explicit passthrough of team 3PT fields
* New derived visibility fields:

```
avg_team_3pm
avg_team_3pa
avg_team_3pt_pct
home_away_3pt_pct_diff
```

**Key Rule:**
These fields are **observational only** — not used in betting logic yet.

---

### 4️⃣ Model Layer Pass-Through Confirmed (No Refactor Needed)

Re-ran:

```
f_nba_0042_add_model.py
```

**Outcome:**

* All new 3PT fields flow through automatically
* No schema changes required
* No overwrites or losses
* CSV + JSON both validated

This confirmed the pipeline is **schema-stable and additive-safe**.

---

### 5️⃣ Terminal Explainability Preserved

Model explanations now display alongside:

* Correct odds-based tip time
* Market snapshot timing
* Projection + edge context

No regressions introduced while adding new data.

---

## 📦 Final Stable Outputs

* `nba_team_3pt_recent.json / csv`
* `nba_games_game_level_with_odds.json / csv`
* `nba_games_game_level_with_odds_model.json / csv`

Each game row now includes:

* Fatigue & rest context
* Betting lines
* Team 3PT shooting (home / away)
* Aggregate 3PT visibility
* Model projections & edges
* Human-readable explanation (when applicable)

---

## 🧠 Design Decisions (Locked)

* 3PT data is **contextual**, not yet predictive
* No model weighting added in this session
* No rows filtered
* No historical data removed
* Forward-only pipeline preserved

---

## 🛑 Intentional Stop Point

The pipeline is now:

* Correct
* Transparent
* Extensible
* Analytics-ready

Next steps are **model design choices**, not plumbing.

---
# CHANGELOG — prj_BookieX

## Incremental Boxscore & Player Ingestion (No Reprocessing)

**Session Date:** 2026-02-06  
**Status:** ✅ Stable / Verified  
**Scope:** NBA boxscores + per-player boxscores  
**Rule Enforced:** Forward-only, additive ingestion

---

## 🎯 Problem

Two ingestion scripts were re-running unnecessary work:

1. **Game boxscore ingestion**
   * Re-fetched boxscores for all games on every run
2. **Player boxscore ingestion**
   * Limited to a recent-date window
   * Overwrote historical player data instead of appending

This caused:
* Slow reruns
* Unnecessary API traffic
* Loss of historical player rows on rerun

---

## ✅ Solution Implemented

### 1️⃣ Incremental Game Boxscore Ingestion

Updated `b_data_004_ingest_boxscores.py` to:

* Load existing enriched output (`nba_games_with_ot.json`)
* Track processed `game_id`s
* Fetch boxscores **only for new games**
* Append new records instead of recomputing all games

**Result:**  
Game-level OT enrichment now runs incrementally and safely.

---

### 2️⃣ Full-History Player Boxscore Ingestion (Incremental)

Updated `b_data_005_ingest_player_boxscores.py` to:

* Remove date-based refresh window
* Treat `game_id` as the atomic ingestion unit
* Load existing player rows from `nba_player_boxscores.json`
* Skip games already ingested
* Append new player rows only

**Critical Fix:**  
Resolved output overwrite bug by writing:

---

## CHANGELOG — prj_BookieX

### Minor Refactor & Pipeline Hygiene Pass

**Session Date:** 2026-02-08
**Status:** ✅ Stable
**Scope:** Small refactors, naming alignment, and pipeline hygiene
**Rule Enforced:** No behavior change, no schema breakage

---

### 🔧 What Changed (Refactor Only)

#### 1️⃣ File Naming & Layer Alignment

* Standardized script prefixes to reinforce pipeline intent:

  * `b_data_*` → raw / external ingestion
  * `c_calc_*` → derived calculations
  * `d_nba_*` → canonical integration
* Moved older variants into `zzz_*` without deletion to preserve audit history.

**Impact:**
Improves readability and mental mapping of pipeline stages.
No logic or output changes.

---

#### 2️⃣ Path & Output Consistency Cleanup

* Normalized use of:

  * `data/external/`
  * `data/derived/`
  * `data/view/`
* Removed hard-coded or legacy output paths where discovered.
* Ensured CSV + JSON pairs remain written together.

**Impact:**
More predictable reruns and fewer accidental overwrites.
No schema changes.

---

#### 3️⃣ Incremental Ingestion Guardrails (Stability Pass)

* Reconfirmed incremental logic in:

  * `b_data_004_ingest_boxscores.py`
  * `b_data_005_ingest_player_boxscores.py`
* Ensured:

  * `game_id` remains the atomic dedupe key
  * Existing records are loaded before append
  * No full reprocessing on rerun

**Impact:**
Performance + API safety improvement.
Behavior unchanged from last stable version.

---

#### 4️⃣ Canonical Builder Clarification

* Minor refactor in `d_nba_021_build_canonical_games.py`:

  * Clarified optional vs required inputs
  * Defensive defaults (`None` / `0`) made explicit
  * Comments updated to reflect actual join behavior

**Impact:**
Documentation-level clarity.
Canonical output unchanged.

---

#### 5️⃣ Import & Header Hygiene

* Removed unused imports discovered during review.
* Standardized docstring headers (Purpose / Inputs / Outputs).
* No functional code paths altered.

**Impact:**
Cleaner diffs, easier review, no runtime effect.

---

### ✅ Verification

* Pipeline rerun completed without errors
* Row counts unchanged
* CSV/JSON schemas unchanged
* Deterministic outputs preserved

---

### 🛑 Intentional Stop

This was a **refactor + hygiene pass only**.
No new metrics, joins, or model logic introduced.

Next work should be **analytic or modeling**, not plumbing.

---

# CHANGELOG – prj_BookieX Odds Integration

## [Unreleased] – Odds Pipeline Refactor (In Progress)

### ✅ Accomplished

#### 1. Root Cause Identified: Odds Misalignment
- Confirmed that `f_nba_0041_add_betting_lines.py` was attaching odds to incorrect games due to **identity mismatch**, not logic errors.
- Identified that Odds API games must be matched by **teams + authoritative time**, not inferred or truncated dates.

#### 2. Separation of Concerns (Correct Architectural Direction)
- Determined that `f_nba_0041_add_betting_lines.py` was doing too much:
  - Fetching
  - Flattening
  - Aggregating
  - Joining
- Agreed to split responsibilities:
  - **ETL / flattening** → `e_nba_032_get_betline_flatten.py`
  - **Game-level joining** → `f_nba_0041_add_betting_lines.py`

#### 3. Odds Flattening Design Defined
- Designed `e_nba_032_get_betline_flatten.py` to:
  - Preserve **raw Odds API data**
  - Emit **one row per game**
  - Include:
    - `odds_commence_time_raw`
    - `odds_game_date_utc`
    - `odds_snapshot_last_utc`
  - Provide both:
    - **LAST** line (single bookmaker, deterministic)
    - **CONSENSUS** line (across bookmakers)

#### 4. Consensus Bug Identified and Fixed (Conceptually)
- Discovered consensus values were distorted because:
  - Multiple snapshots per bookmaker were being averaged
- Correct definition locked in:
  - **Consensus = latest line per bookmaker, then aggregate**
- Added transparency requirement:
  - `consensus_book_count`

#### 5. Critical Identity Bug Identified (Key Insight)
- Found that grouping by:
  ```text
  (home_team, away_team, odds_game_date_utc)
  

## [2026-02-09] e_nba_032_get_betline_flatten – Identity + Consensus Architecture Lock

### Added
- Added **true game identity** using `(home_team, away_team, odds_commence_time_raw)` to prevent same-day team collisions.
- Added **`*_consensus_all_time` fields** (opening market consensus) for spreads and totals:
  - `spread_home_consensus_all_time`
  - `spread_away_consensus_all_time`
  - `total_consensus_all_time`
- Added **`all_time_snapshot_count`** to expose total historical market depth per game.

### Changed
- Rebuilt `e_nba_032_get_betline_flatten.py` as **pure ETL** with no joins or NBA schedule logic.
- Excluded **h2h markets entirely** to eliminate outcome ambiguity.
- Fixed consensus calculation to:
  - Collapse to **latest snapshot per bookmaker first**
  - Then average across bookmakers (no snapshot double-counting).
- Enforced deterministic **LAST line selection** via bookmaker priority + snapshot recency.

### Removed
- Removed invalid grouping by `(home_team, away_team, game_date)` which caused odds to attach to incorrect games.
- Removed snapshot-level averaging and implicit merging across games.

### Impact
- Guarantees **ONE ROW PER GAME** with stable identity.
- Enables downstream **momentum, drift, and volatility modeling** without reprocessing raw odds.
- Makes backtests deterministic, auditable, and collision-safe.

# CHANGELOG — prj_BookieX  
## Phase: Datetime Contract Stabilization + Odds Join Repair  
**Date:** 2026-02-09  
**Scope:** NBA betting pipeline (ETL → game-level join)  
**Status:** ✅ LOCKED / STABLE

---

## 🎯 Executive Summary

This phase resolved a long-standing class of bugs caused by **datetime / timezone mismatches** between NBA schedule data and Odds API market data. The core issue was not math or aggregation, but **semantic misalignment of “game day” vs “game start instant.”**

A single, deterministic **bridge field** was designed, implemented, and frozen, enabling correct, auditable joins with no tolerances, hacks, or inference.

The betting pipeline is now **deterministic, backtest-safe, and extensible** (NBA → college).

---

## 🧠 Root Cause Identified

- NBA schedule data defines games by **calendar day** (`game_date`)
- Odds API defines games by **exact start instant** (`commence_time`, UTC)
- These concepts were incorrectly treated as interchangeable
- UTC conversion caused games to drift to adjacent dates
- Result: odds attaching to incorrect games or silently mis-joining

**Key insight:**  
> This is a *semantic contract problem*, not a coding or math problem.

---

## 🧱 Architectural Fix (Core Design)

### ✅ New Canonical Bridge Field

**Field name**
```text
nba_game_day_local

## 2026-02-08 — Betting Line ETL Stabilization & h2h Reintegration

### Summary
This update completes the correction and hardening of the NBA betting-line ETL by:
- Resolving game/odds datetime misalignment
- Introducing a canonical bridge field for joins
- Re-adding h2h (moneyline) markets in a deterministic, auditable way
- Locking one-row-per-game behavior across all markets

---

### 🔧 Root Causes Identified
- Odds were not joining to games due to **timezone / date boundary drift** between:
  - NBA schedule `game_date` (calendar-based)
  - Odds API `commence_time` (UTC, market-based)
- h2h (moneyline) markets were previously excluded, causing downstream feature gaps.

---

### 🧩 Architectural Changes

#### 1. Canonical Datetime Bridge Introduced
- Added shared utility:
  - `utils/datetime_bridge.py`
- New authoritative field:
  - `nba_game_day_local`
- Rules:
  - Derived from `odds_commence_time_raw`
  - League-aware (NBA)
  - Resolves UTC → local game day boundary issues
- Purpose:
  - Provides a **stable join anchor** between NBA schedule data and odds data
  - Prevents future misjoins across leagues or seasons

---

### 📦 e_nba_032_get_betline_flatten.py (PURE ETL)

#### Markets Supported (Updated)
- `spreads`
- `totals`
- **`h2h` (moneyline) — RE-ADDED**

#### New Fields Added (Non-Breaking)
- `nba_game_day_local`
- Moneyline (h2h) features:
  - `moneyline_home_last`
  - `moneyline_away_last`
  - `moneyline_home_consensus`
  - `moneyline_away_consensus`
  - `moneyline_home_consensus_all_time`
  - `moneyline_away_consensus_all_time`

#### Logic Guarantees
- ONE row per game (grouped by home, away, commence_time)
- Deterministic LAST selection:
  - Most recent snapshot
  - Book priority tie-breaker
- Consensus logic:
  - Average of latest price per bookmaker
- All-time consensus:
  - Average of opening (earliest) price per bookmaker
- No joins
- No NBA schedule logic
- No recomputation downstream

---

### 🔗 f_nba_0041_add_betting_lines.py (JOIN ONLY)

- Join key remains locked:



## 2026-02-09 — Model + Agent Stabilization (Odds LAST Contract)

### Fixed
- Resolved a latent `NameError` in `eng/confidence_gate.py` caused by undefined confidence thresholds.
- Identified root cause as Python short-circuit masking due to previously missing or mis-attached odds.
- Bug surfaced only after odds correctness was restored upstream (expected and correct behavior).

### Added
- Explicit confidence policy constants defined in `eng/confidence_gate.py`:
  - `MIN_SPREAD_EDGE`
  - `MIN_TOTAL_EDGE`
  - `MIN_PARLAY_EDGE`
- Thresholds are now owned by the confidence gate agent, ensuring deterministic, standalone behavior across pipelines and future agentic workflows.

### Changed
- `f_nba_0042_add_model.py` updated to explicitly select **LAST** flattened odds fields:
  - `spread_home_last`
  - `total_last`
  - `moneyline_home_last`
  - `moneyline_away_last`
- Removed legacy nested-odds fallback logic to prevent silent input corruption.
- Added `odds_source_used = "LAST"` for auditability and downstream clarity.

### Verified
- Model preserves original Joel baseline math and behavior.
- No rows filtered or removed; additive-only changes maintained.
- Confidence gating now executes correctly with valid odds inputs.
- End-to-end run is deterministic and backtest-stable.

### Notes
- This change locks the contract between:
  - `e_nba_032_get_betline_flatten.py` (PURE ETL)
  - `f_nba_0041_add_betting_lines.py` (JOIN ONLY)
  - `f_nba_0042_add_model.py` (explicit odds selection)
- Future models may introduce CONSENSUS-based logic, but must do so as separate, explicit implementations.

# CHANGELOG — prj_BookieX

---

## 2026-02-10 — Cleanup of Old Files & Unused Iterations

**Time:** 10:38 AM  
**Type:** Maintenance / Hygiene  
**Scope:** File system cleanup + IDE-tracked deletions  
**Behavior Change:** ❌ None (no logic or schema changes)

---

### 🧹 Cleanup Actions

#### File System (Explorer)
- Created a **full pre-cleanup backup** of the project to preserve rollback safety.
  - Backup location:
    ```
    C:\Users\Rick_DellXPS\OneDrive\Dev\Python\zzz_BkUp_PythonPrj\
    prj_BookieX_20260210_1036_preCleanUp.zip
    ```
- Moved **all data files not modified on 2/10/2026** (i.e., not part of the current end-to-end run) to a quarantine notes folder.
- Relocated **all unused `zzz_*` Python iterations** to the same notes area for potential future reintegration.

  - Cleanup holding location:
    ```
    C:\Users\Rick_DellXPS\OneDrive\Dev\Python\zzz_Notes\
    notes_prj_BookieX\zzz_prj_bookieX_cleanup_files_20260210
    ```

#### IDE (PyCharm)
- Deleted unused files **from within PyCharm** to ensure:
  - Deletions are tracked
  - Dependency warnings surface immediately if refactoring is required
  - Ability to pause and reassess safely if references break

---

### ✅ Outcome
- Reduced repository clutter
- Improved signal-to-noise during development
- Preserved full rollback and reintegration paths
- No impact to pipeline behavior, outputs, or schemas

---

**Status:** Stable  
**Next Step:** Continue development on cleaned canonical codebase

---

## 2026-02-10 — Incremental Boxscore Refresh & Eligibility Gating Fix

**Component:** `b_data_004_ingest_boxscores.py`  
**Type:** Bug fix / performance & correctness correction  
**Scope Rule:** Additive only (no schema break)

### Problem
Incremental boxscore ingestion exhibited two related issues:

1. Games ingested while incomplete were **not reliably refreshed** once finalized, causing stale overtime indicators.
2. A naive refresh strategy risked **full historical reprocessing**, while later optimizations still resulted in repeated polling of historical games that would never finalize.

Root cause analysis showed that **eligibility gating based on `nba_game_day_local` was insufficient**, as it did not properly account for postponed, rescheduled, or canonically shifted games.

### Fix
- Introduced additive audit field `_boxscore_status`:
  - `"FINAL"` → NBA `gameStatus == 3`
  - `"SKIPPED_NOT_FINAL"` → scheduled or in-progress
- Updated ingestion logic to:
  - Re-fetch **only** games not yet marked FINAL
  - Treat legacy rows (missing `_boxscore_status`) as FINAL by default
  - Merge refreshed rows by `game_id` without duplication
- **Corrected eligibility gating** to use authoritative scheduling metadata:
  - Replaced `nba_game_day_local` checks with `canonical_game_day`
  - Boxscores are now polled **only when `canonical_game_day <= today`**
  - Prevents infinite polling of historical games that will never finalize
  - Preserves correct behavior for postponed and rescheduled games

### Impact
- ✅ Correctly refreshes partial → final games
- ✅ Prevents full historical reprocessing
- ✅ Eliminates infinite polling loops for never-final games
- ✅ Dramatically faster steady-state execution
- ✅ No existing fields removed or renamed
- ➕ One additive column: `_boxscore_status`

### Downstream Safety
Schema remains backward-compatible.  
All changes are additive and safe for dependent pipeline stages.

---

## 2026-02-10 — Player Boxscore Shooting Breakdown Fix

**Component:** `b_data_005_ingest_player_boxscores.py`  
**Type:** Bug fix / schema correction  
**Scope Rule:** Additive only (no field removals)

### Problem
Per-player boxscore ingestion incorrectly populated `ftm` / `fta` using **2PT field-goal values**, resulting in:
- Incorrect free throw statistics
- FT, 2PT, and 3PT metrics being indistinguishable
- Internal shooting consistency violations

Additionally, incremental ingestion correctly skipped existing games, preventing newly added fields from populating without an explicit rebuild.

### Fix
- Corrected stat extraction to use authoritative NBA boxscore fields:
  - `freeThrowsMade`
  - `freeThrowsAttempted`
  - `fieldGoalsMade`
  - `fieldGoalsAttempted`
  - `threePointersMade`
  - `threePointersAttempted`
- Added proper derivation of:
  - `fg2m`, `fg2a`, `fg2_pct`
- Ensured FT, 2PT, and 3PT stats are **distinct, consistent, and auditable**
- Performed a one-time rebuild by deleting the existing player boxscore JSON to allow new fields to populate

### Impact
- ✅ Free throw, 2PT, and 3PT stats correctly separated
- ✅ Shooting percentages internally consistent
- ✅ Incremental ingestion behavior unchanged and verified
- ❌ No downstream schema break
- ❌ No data loss (full rebuild intentional)

### Verification
- Player rows re-ingested successfully
- New fields populated for all finalized games
- Spot-checked FG = FG2 + FG3 consistency

---

## 2026-02-10 — Secure API Key Handling (Odds Ingestion)

**Component:** `e_nba_031_get_betline.py`  
**Type:** Security / configuration fix  
**Scope Rule:** No behavior change, no schema change

### Change
- Removed hard-coded Odds API key from source code.
- Moved API key to external `.env` file using `python-dotenv`.

### Implementation
- Added deterministic `.env` loading via:
  ```python
  load_dotenv(Path(__file__).parent / ".env")

Replaced inline secret with:
API_KEY = os.getenv("ODDS_API_KEY")

Added explicit runtime guard:

Raises error if ODDS_API_KEY is missing.

Impact

✅ Improves security and audit compliance
✅ Enables safe repo sharing and CI usage
✅ No change to runtime behavior or outputs
❌ No data or schema changes

Status: Stable

## 2026-02-10 — Rest Days Pipeline Contract Fix (Datetime Field Regression)

**Component:** `c_calc_010_add_team_rest_days.py`  
**Type:** Bug fix / contract alignment  
**Impact:** Restored downstream pipeline execution  
**Scope Rule:** No schema changes, additive-safe behavior only

### 🐛 Problem
`c_calc_010_add_team_rest_days.py` began failing with:

KeyError: 'game_datetime_utc'

This prevented `nba_games_with_rest.json` from being written, breaking all downstream
calculation stages (B2B flags, fatigue, canonical build).

### 🔍 Root Cause
An upstream refactor removed the `game_datetime_utc` field from
`nba_boxscores_team.json`, but `c_calc_010_add_team_rest_days.py` still
hard-indexed that field in its sort key.

This caused a hard failure before any output was produced.

### ✅ Fix Implemented
- Removed direct dependency on `game_datetime_utc`
- Updated game sorting logic to use the existing, deterministic helper:

```python
parse_datetime(g["game_date"], g.get("game_time_utc"))

This preserves correct chronological ordering using NBA schedule data

No new fields introduced

No schema or output changes

🧠 Design Decision (Locked)

Rest day calculations follow NBA schedule chronology

Market-based datetime logic (datetime_bridge.py) is explicitly NOT used

Datetime bridge remains reserved for odds / market joins only

📦 Outcome

nba_games_with_rest.json and .csv successfully regenerated

Downstream pipeline stages unblocked

Deterministic, audit-safe behavior restored

Status: ✅ Stable


---

# CHANGELOG — prj_BookieX

## 2026-02-11 — OneDrive Sync Conflict Incident & Hardening

**Component:** Entire Project (Code + Data + Git)
**Type:** Environmental incident / recovery / stability hardening
**Scope Rule:** No model logic changes; structural stabilization only
**Status:** ✅ Stable / Recovered

---

## 🎯 Incident Summary

A large-scale OneDrive cloud migration (photo cleanup + external drive move) ran concurrently with active Python development and ETL execution inside the synced project directory.

This resulted in:

* Mass creation of `-DESKTOP-42S5DOC` conflict copies
* Conflict copies across:

  * All pipeline scripts
  * All derived JSON artifacts
  * Canonical + model outputs
  * `.git/index`
* Partial / stale JSON artifacts
* Pipeline attempting full rebuild due to upstream state mismatch

This was not a code defect, but an environmental concurrency issue between:

* OneDrive sync engine
* Large multi-day file migration
* Active JSON rewrite-heavy ETL processes

---

## 🔍 Root Cause

OneDrive detected concurrent file mutations and protected both versions by renaming local variants:

```
filename-DESKTOP-42S5DOC.py
```

Because:

* JSON artifacts are fully rewritten each run
* Git index mutates frequently
* Large photo migration triggered extended cloud reconciliation
* Sync overlapped with ETL write cycles

Result: conflict copies created across entire pipeline.

---

## 🛠 Recovery Actions Taken

### 1️⃣ Full Project Backup (Pre-Fix Snapshot)

Created:

* Full folder copy
* ZIP archive

Ensured rollback safety before any mutation.

---

### 2️⃣ Manual Conflict Normalization

For every `*-DESKTOP-42S5DOC` file:

* Verified timestamps
* Confirmed newest versions were preserved
* Manually renamed DESKTOP variants back to canonical filenames
* Removed duplicate stale originals
* Ensured zero remaining conflict copies

Affected areas:

* All `b_data_*`
* All `c_calc_*`
* All `d_nba_*`
* All `e_nba_*`
* All `f_nba_*`
* All derived JSON outputs
* `.git/index`

---

### 3️⃣ JSON Integrity Validation

Validated:

* Files not truncated
* Proper closing brackets
* Loadable via `json.load`
* Row counts consistent

Avoided full pipeline rerun until integrity confirmed.

---

### 4️⃣ Git Integrity Verified

Confirmed:

* `git status` clean
* No index corruption
* Repository functional

---

## 🔐 Hardening Measures Implemented

### A. Conflict Guard Added (Pipeline Protection)

Design decision: fail fast if OneDrive conflict files exist.

Startup guard pattern introduced for `000_RUN_ALL.py`:

* Scan for `*-DESKTOP-*`
* Abort pipeline if found
* Prevent silent stale-code execution

This converts sync incidents into immediate visible failures.

---

### B. Operational Rule Locked

Never mix:

> Large OneDrive cloud migrations
> with
> Active ETL development inside synced directory

Explicit separation rule adopted.

---

### C. Architectural Awareness Established

Recognized structural mismatch:

| OneDrive Assumes    | ETL Pipeline Assumes   |
| ------------------- | ---------------------- |
| Occasional edits    | Continuous rewrites    |
| Slow mutation       | Rapid full-file writes |
| No Git churn        | Heavy Git churn        |
| Minimal concurrency | High concurrency       |

Conclusion:

This was an environmental concurrency event, not a logic defect.

---

## 🧠 Lessons Locked

* OneDrive is deterministic, not confused.
* JSON full rewrites are high-risk inside active sync.
* Cloud sync tools are not version control.
* Git index conflicts are particularly dangerous.
* Always stabilize before rerunning pipeline after environmental event.

---

## 📦 System State Post-Recovery

* All canonical scripts normalized
* All JSON artifacts verified
* Pipeline stable
* No logic regressions
* No schema changes
* No model alterations

---

## 🛑 Intentional Stop Point

System stabilized after environmental incident.

Next work may resume normally.

Environmental safeguards now in place to prevent recurrence.

---
## 2026-02-15 — Phase 1.5 Stabilization Complete (Deterministic Core Locked)

**Component:** Core Processing Pipeline  
**Type:** Architectural Stabilization  
**Scope Rule:** No model changes. No logic changes. Determinism enforcement only.

---

### Objective

Stabilize the BookieX deterministic core before introducing agentic layers, multi-model framework, or NCAA expansion.

Goal:
> Same input → identical output (row count, schema, hash)

---

### What Was Implemented

#### 1️⃣ LIVE vs LAB Mode Separation

Added dual execution modes in `000_RUN_ALL.py`:

- **LIVE MODE**
  - Full ingestion (API + dynamic sources)
  - Production runs

- **LAB MODE**
  - Skips ingestion layer
  - Runs deterministic processing only
  - Used for reproducibility verification

This cleanly separated:
- Data acquisition
- Data processing

---

#### 2️⃣ Ordering & Append Drift Fixes

Resolved nondeterminism caused by:

- Incremental append ordering
- Unsorted merges
- Inconsistent write order
- Dynamic ingestion refresh behavior

Enforced explicit sorting before JSON writes in ingestion scripts.

---

#### 3️⃣ Determinism Verification Framework

Created `TRUTH/` directory containing:

- `baseline_snapshot/`
- `build_baseline_manifest.py`
- `verify_determinism.py`

Verification checks:
- Row count
- Schema equality
- SHA256 hash consistency

---

#### 4️⃣ Clean Baseline Rebuild

Rebuilt baseline under LAB mode only.

Removed dynamic backtest artifacts and timestamped outputs from manifest.

---

### Final Result

## 2026-02-15 — Phase 1.5 Complete: Deterministic Stabilization & Calibration Freeze

**Scope:** Engine hardening, reproducibility validation, statistical characterization  
**Status:** COMPLETE — Phase 2 unlocked  

---

### 🔒 Phase Lock (Core Freeze)

Confirmed and froze deterministic core:

- ETL layer
- Canonical joins
- Odds enrichment logic
- Baseline model
- Confidence gating
- Backtest logic

Actions taken:
- Stopped refactoring
- Separated LIVE vs LAB execution
- Created stable boundary between ingestion and deterministic layers

---

### 🧪 Deterministic Rebuild Validation (TRUTH Framework)

Built reproducibility harness:

- Created `TRUTH/` directory
- Built `baseline_manifest.json`
- Implemented `verify_determinism.py`
- Enforced deterministic sorting in ingestion layers
- Fixed append drift issues
- Separated ingestion from deterministic computation

Cold rebuild under LAB mode:


---

## 2026-02-15 — Phase 2 Completion & Architectural Freeze

**Phase:** Phase 2 — Analyst Layer  
**Type:** Architecture milestone  
**Scope Rule:** Additive only (no core refactors)

---

### Summary

Phase 2 is now architecturally complete and formally frozen.

This phase introduced a read-only Analyst layer designed to interpret frozen model outputs without modifying computation, thresholds, ingestion, or calibration logic.

No changes were made to the deterministic core.

---

### Completed Components

#### 1. Question Contract
- Created `docs/PHASE_2_QUESTION_CONTRACT.md`
- Defined 6 locked daily questions:
  - ACTION
  - IGNORE
  - WHY
  - DISAGREEMENT
  - WHAT CHANGED
- Enforced non-agentic, read-only framing

#### 2. Analyst Agent Role
- Defined read-only explainer role
- Explicitly prohibited:
  - Pick modification
  - Threshold modification
  - Recalculation
  - Ingestion access

#### 3. Daily View Schema
- Implemented `eng/daily/build_daily_view.py`
- Produces `DAILY_VIEW_V1`
- Deterministic output
- Consumes only:
  - Frozen model artifact
  - Calibration snapshot

#### 4. Agent Read Scope
- Created `docs/PHASE_2_AGENT_READ_SCOPE.md`
- Restricted Analyst to:
  - `data/daily/daily_view_*.json`
- Explicitly denied access to:
  - Raw model artifacts
  - Backtest outputs
  - Ingestion data
  - Engine logic

#### 5. Initial Analyst Prompt Set
- Created `docs/PHASE_2_ANALYST_PROMPTS.md`
- Defined first 5 read-only Analyst prompts
- Enforced no recomputation rule

---

### Governance Decision

Phase 2 is now frozen.

- No schema changes without Phase 4 approval
- No expansion of Analyst read scope
- No modification of deterministic compute layer

Phase 3 will introduce a minimal interaction layer (CLI) to operationalize the Analyst prompts.

---

### Core Integrity

Deterministic compute layer remains unchanged.
TRUTH framework unaffected.
LAB mode determinism preserved.
LIVE vs LAB separation preserved.

---

Status: PHASE 2 LOCKED

---

Perfect. Lock it properly.

Below is a clean, governance-grade CHANGELOG entry for Phase 3.
Copy/paste directly into `CHANGELOG.md`.

---

# 2026-02-15 — Phase 3: Deterministic CLI Interaction Layer (LOCKED)

**Component:** `eng/cli/bookiex_cli.py`
**Contract:** `docs/PHASE_3_CLI_CONTRACT.md`
**Scope:** Presentation Layer Only
**Type:** Additive Feature (No Core Refactor)

---

## Objective

Introduce a minimal, deterministic CLI interaction layer that operationalizes the Phase 2 daily question contract without expanding computational authority or read scope.

Phase 3 enables a human to query BookieX directly without spreadsheets or JSON inspection.

---

## Architectural Position

Pipeline Layers:

```
Compute → Freeze → Explain → Present
```

* Phase 1.5 froze Compute.
* Phase 2 defined Explain (Analyst role).
* Phase 3 introduces Present (CLI only).

No upstream logic modified.

---

## Added

### 1️⃣ CLI Entry Point

```
eng/cli/bookiex_cli.py
```

Supports:

* `action`
* `ignore`
* `why`
* `disagreement`
* `changes` (stub v1)

---

### 2️⃣ Deterministic File Resolution

* Reads only:

  ```
  data/daily/daily_view_YYYY-MM-DD_v1.json
  ```
* Enforces `_v1` suffix naming
* Rejects arbitrary file paths
* Defaults to most recent DAILY_VIEW if no date provided

---

### 3️⃣ Wrapped DAILY_VIEW Handling

* Extracts `data["games"]` from DAILY_VIEW_V1 wrapper object
* Supports list fallback safely
* Fails fast on invalid format

---

### 4️⃣ Deterministic Output Rules

* Stable sorting:

  * Primary: descending `parlay_edge_score`
  * Secondary: `game_id`
* Explicit numeric rounding (1 decimal)
* Explicit `+` sign formatting
* Suppresses `None` values
* Clean header formatting
* No JSON dumps
* No timestamps in output
* No upstream artifact leakage

---

### 5️⃣ Presentation Polish (Usability Refinement)

Refined:

* ACTION now displays:

  * Pick direction
  * Edge magnitude
  * Confidence reason
* WHY now:

  * Suppresses `None`
  * Shows Pick
  * Uses consistent `+` formatting
  * Displays Parlay Score
* IGNORE clean bullet format
* DISAGREEMENT threshold-based (display only)
* CHANGES implemented as safe stub (no recompute)

---

## Governance

Created:

```
docs/PHASE_3_CLI_CONTRACT.md
```

Defines:

* Strict read scope
* Determinism rules
* Command lock
* Non-negotiable constraints
* Versioning requirements
* No computational authority

---

## Explicit Non-Changes

Phase 3 did NOT:

* Modify model logic
* Modify thresholds
* Modify calibration
* Modify ingestion
* Modify joins
* Modify schema
* Modify backtests
* Expand read scope beyond DAILY_VIEW
* Introduce agentic behavior
* Introduce caching
* Introduce persistence
* Introduce external data calls

Strictly presentation layer only.

---

## Validation

Validated via controlled TEST DAILY_VIEW artifact:

* ACTION: PASS
* IGNORE: PASS
* WHY: PASS (after polish)
* DISAGREEMENT: PASS
* CHANGES: Safe stub

No crashes.
No nondeterminism.
No scope violations.

---

## Phase 3 Gate

```
PHASE 3 GATE: PASS
```

The CLI interaction layer deterministically operationalizes
Phase 2 daily questions and produces clean, decision-ready
human-readable output without expanding computational authority.

---

Status: LOCKED
Presentation layer stabilized.

---

## 2026-02-15 — Phase 4 Fatigue Pipeline Repair & Model Framework Stabilization

### Component

* `c_calc_011_flag_back_to_backs.py`
* `c_calc_012_compute_fatigue_score.py`
* `d_nba_021_build_canonical_games.py`
* `d_nba_022_collapse_to_game_level.py`
* `f_nba_0041_add_betting_lines.py`
* `f_nba_0042_add_model.py`
* `eng/models/fatigue_plus_model.py`
* Multiple `eng/analysis/*` scripts

---

## 🔎 Problem

FatiguePlus model was showing near-perfect correlation with Baseline model (~0.9995), indicating fatigue signal was not materially influencing projections.

Root causes identified:

1. Fatigue scores were not passing through canonical → collapse → odds layers.
2. `fatigue_diff_home_minus_away` was not propagated to game-level.
3. Back-to-back flags were not being correctly generated due to undefined `record`.
4. Fatigue model logic relied only on boolean flags instead of actual score deltas.
5. `fatigue_diff_home_minus_away` values were zero at model layer despite upstream calculation.

---

## 🛠 Fixes Applied

### 1️⃣ Back-to-Back Logic Repair

**File:** `c_calc_011_flag_back_to_backs.py`

* Added missing `record = dict(g)` inside loop.
* Ensured flags are written per game before append.
* Regenerated `nba_games_with_b2b.json`.

Result:

* B2B flags correctly computed and persisted.

---

### 2️⃣ Fatigue Score Validation & Linking Audit

**File:** `c_calc_012_compute_fatigue_score.py`

* Verified correct linking on:

  * `home_rest_days`
  * `away_rest_days`
  * `home_back_to_back`
  * `away_back_to_back`
* Confirmed asymmetric fatigue now generated.

Validation:

* 593 games with non-zero fatigue diff
* Range: -1.6 to +1.6
* Std Dev ≈ 0.93

---

### 3️⃣ Canonical Layer Enhancement

**File:** `d_nba_021_build_canonical_games.py`

Added passthrough:

```python
fatigue_record = fatigue_map.get(game_id, {})

"fatigue_flag": fatigue_record.get(f"{side}_fatigue_score", 0.0) > 0,
"fatigue_score": fatigue_record.get(f"{side}_fatigue_score", 0.0),
"fatigue_diff_home_minus_away": fatigue_record.get(
    "fatigue_diff_home_minus_away", 0.0
),
```

Result:

* Canonical now carries fatigue score + diff properly.

---

### 4️⃣ Game-Level Collapse Fix

**File:** `d_nba_022_collapse_to_game_level.py`

Added passthrough:

```python
f"{side}_fatigue_score": r.get("fatigue_score"),
"fatigue_diff_home_minus_away": r.get("fatigue_diff_home_minus_away"),
```

Result:

* Game-level file now includes fatigue scores and diff.

---

### 5️⃣ Odds Join Layer Preservation

**File:** `f_nba_0041_add_betting_lines.py`

Confirmed non-destructive join preserved fatigue fields.

No overwrites occurred.

---

### 6️⃣ Model Layer Now Receives Fatigue Signal

**File:** `f_nba_0042_add_model.py`

Confirmed:

* Fatigue fields preserved into final model file.
* `fatigue_diff_home_minus_away` now present in:

  * `nba_games_game_level_with_odds_model.json`
  * CSV output

---

### 7️⃣ FatiguePlus Model Updated

**File:** `eng/models/fatigue_plus_model.py`

* Now reads fatigue data.
* Applies deterministic projection adjustment.
* Edge recalculated from adjusted projection.
* Context flags added.

Result:

* Correlation reduced from 0.9995 → 0.9957
* Model now measurably diverges.

---

## 📊 Validation Results

### Fatigue Diff Distribution

* Non-zero games: 593
* Mean: -0.0442
* Std Dev: 0.9304
* Min: -1.6
* Max: 1.6

### Cross-Model Edge Stats

FatiguePlus now shows distinct edge distribution vs baseline.

### Correlation Matrix

Baseline vs FatiguePlus:

* Before: 0.9995
* After: 0.9957

Fatigue signal now flowing end-to-end.

---

## ✅ Outcome

* Full fatigue pipeline integrity restored.
* Canonical → Collapse → Odds → Model flow verified.
* Multi-model framework structurally stable.
* Phase 4 no longer blocked by silent fatigue passthrough failure.

---

## 📌 Status

Phase 4: ~70% complete
Next milestone: FatiguePlus_v2 directional implementation + Injury model

---

## 2026-02-16 — Phase 4: Multi-Model Framework Implementation & Validation

**Component:** `model_runner.py`, model registry, plugin models
**Type:** Architectural expansion (additive only)
**Scope Rule:** Deterministic, non-destructive, baseline preserved

---

### 🎯 Objective

Advance BookieX from single-model evaluation to a deterministic multi-model comparison framework capable of measuring model divergence, disagreement value, and decision usefulness.

---

## 1️⃣ Multi-Model Plugin Framework

**Files Added/Updated:**

* `eng/model_runner.py`
* `eng/models/`
* Model registry integration

### Summary

Implemented a plugin architecture allowing multiple models to:

* Consume the same final game-level dataset
* Emit structured outputs:

  * `model_name`
  * `projection`
  * `edge`
  * `context_flags`
* Operate in parallel without mutating baseline logic

### Result

* Deterministic execution
* JSON + CSV validated
* Model independence measurable via correlation matrix
* Baseline model preserved as anchor

---

## 2️⃣ FatiguePlus_v2 (Directional Upgrade)

### Enhancement

Upgraded fatigue model from passthrough logic to directional adjustment model using:

* `fatigue_diff_home_minus_away`
* `home_fatigue_score`
* `away_fatigue_score`

### Behavior

* Directional spread adjustment
* Secondary total compression
* Deterministic weighting

### Validation

* Baseline vs Fatigue correlation ≈ 0.42
* Disagreement bucket:

  * Baseline Win % ≈ 24%
  * FatiguePlus Win % ≈ 75%

### Result

Fatigue signal confirmed as materially differentiating and decision-relevant.

---

## 3️⃣ MonkeyDarts Model (Dispersion Benchmark)

### Purpose

Introduce random baseline to validate:

* Structural independence
* Edge dispersion realism
* Non-overfitting of deterministic models

### Validation

* Correlation vs Baseline ≈ 0.78
* Acts as independent variance reference

### Result

Confirmed multi-model separation is real, not artifact.

---

## 4️⃣ InjuryModel_v1 → v2 (Player-Weighted)

### Phase 4 Step

**Initial Version:**

* Team-level injury count weighted by status

**Upgrade (v2):**

* Player-weighted injury impact using:

  * Rolling average minutes (last 5 games)
  * Status weights (OUT, DOUBTFUL, QUESTIONABLE, PROBABLE)
  * Formula:

```
injury_weight = status_weight × (avg_minutes / 36)
```

### Pipeline Integration

* Injury history append-only archive
* Canonical ingest updated
* Collapse layer passthrough added
* No changes to baseline model
* No changes to betting layer

### Current State

* Architecture validated
* Signal dormant during NBA All-Star break
* Live divergence pending resumed games

---

## 5️⃣ Correlation & Cluster Analysis

### Model Correlation Matrix Observations

* Baseline vs Fatigue ≈ 0.42
* Fatigue vs Market ≈ 0.07
* Fatigue vs Injury ≈ 0.99 (due to dormant injury variance)
* Market cluster structurally independent
* Monkey remains dispersion reference

### Conclusion

Distinct model families exist:

* Cluster A: Fatigue/Injury
* Cluster B: MarketPressure
* Cluster C: Random benchmark
* Baseline anchor

Multi-model architecture is functioning as designed.

---

## 6️⃣ Phase 4 Gate Evaluation

**Gate Question:**
Does multi-model comparison provide meaningful decision insight?

### Evidence:

* Proven disagreement edge (Fatigue vs Baseline)
* Structural cluster independence
* Deterministic reproducibility maintained
* Analyst layer compatible
* No baseline mutation

### Decision:

```
PHASE 4 GATE STATUS: PROVISIONAL PASS
(Multi-model comparison is decision-useful.
Injury live validation pending post–All-Star break games.)
```

---

# 🔒 Determinism Confirmation

* No refactors to Phase 1–3 core
* No schema breaks
* No baseline mutation
* All additions additive only
* LIVE vs LAB boundary preserved

---

# 📈 Strategic Outcome of Phase 4

BookieX is no longer a single-signal engine.

It is now:

* A clustered multi-model decision system
* Capable of disagreement analysis
* Architecturally extensible
* Deterministic and reproducible
* Ready for arbitration layer (Phase 4.5)

---

# 🚦 Next Phase

Phase 4.5 — Confidence & Arbitration Layer
(Deterministic confidence scoring based on cluster agreement/disagreement)

---

## 2026-02-16 — Phase 4.5 Confidence Validation (Analytical Layer Only)

**Component:** `eng/analysis/analysis_017_confidence_backtest_v2.py`  
**Type:** Additive analytical validation (LAB-only)  
**Scope Rule:** No deterministic core mutation. No schema changes. No pipeline refactors.

---

### Context

Phase 4 introduced a multi-model framework (`model_runner.py`) that runs parallel models
against the frozen deterministic grading artifact:

- Baseline_v1
- FatiguePlus_v2
- InjuryModel_v1
- MarketPressureModel
- MonkeyDartsModel

However, the grading pipeline (`f_nba_0042_add_model.py → backtest_runner.py`)
remains intentionally frozen under Phase 1.5 lock.

Phase 4.5 required validating whether model agreement/disagreement
meaningfully separates historical performance — **without modifying
the deterministic grading pipeline.**

---

### Initial Attempt

- Attempted to persist `model_results` inside backtest artifacts.
- Determined multi-model output is not part of grading pipeline.
- Confirmed pipeline separation is intentional and correct.
- Reverted to frozen architecture.

Conclusion:  
Confidence validation must occur in a separate analytical layer.

---

### Implemented

Added new analysis script:

```

eng/analysis/analysis_017_confidence_backtest_v2.py

```

This script:

1. Loads `nba_games_multi_model_v1.json`
2. Loads latest `eng/outputs/backtests/<timestamp>/backtest_games.json`
3. Joins on `game_id`
4. Applies deterministic confidence classification
5. Computes win rate by tier

No pipeline mutation.
No artifact mutation.
No grading logic changes.

---

### Confidence Methods Tested

#### 1. Sign Agreement Count
Result: All games classified HIGH → not useful.

#### 2. Projection Variance-Based Tiering
Result: Minimal performance separation across tiers.

#### 3. Directional Disagreement-Based Tiering
Final logic:

- HIGH → All model edges same sign
- LOW → Positive and negative edges present (directional conflict)
- MEDIUM → Fallback / weak signal

---

### Historical Validation Results

| Tier | Games | Win Rate |
|------|-------|----------|
| HIGH (Agreement) | 70 | 62.9% |
| LOW (Disagreement) | 62 | 67.7% |

Overall baseline win rate ≈ 65.2%

---

### Insight

Model **disagreement** outperformed agreement.

This suggests:

- Meaningful divergence between models may signal structural opportunity.
- Confidence ≠ consensus.
- Cross-cluster conflict may identify regime shifts or contextual signal.

---

### Architectural Status

- Deterministic grading pipeline remains frozen.
- No changes to `f_nba_0042_add_model.py`
- No changes to `backtest_runner.py`
- No changes to `DATA_CONTRACT.md`
- Multi-model framework remains analytical layer only.
- Confidence layer validated in LAB mode.

---

### Phase Status

```

PHASE 4.5 GATE: PROVISIONAL PASS

Confidence layer validated analytically.
Directional disagreement shows lift vs agreement.
No deterministic core mutation.
System architecture remains layered and stable.

```

---

### Next Phase

Phase 4.6 — Agent Integration

Expose disagreement awareness in CLI and Analyst outputs
without modifying grading logic.
```

---

## 2026-02-16 — Daily View Contract Reconciliation (Post Phase 4.5)

**Component:** `eng/daily/build_daily_view.py`  
**Type:** Schema reconciliation / contract alignment  
**Scope Rule:** Additive + corrective only. No upstream mutation. Deterministic core untouched.

---

### Context

After completing Phase 4.5 (Confidence Validation),  
`build_daily_view.py` failed when run against historical dates due to:

- Calibration snapshot structure drift
- Model artifact naming inconsistencies
- Context flag field mismatches
- Duplicate logic blocks
- Overly strict dictionary access

This was not a pipeline failure.  
It was schema drift between:

- Phase 1.5 Calibration Snapshot
- Frozen Model Artifact
- Phase 2 Daily View consumer

---

### Fixes Applied

#### 1️⃣ Bucket Boundary Logic Restored

Removed dependency on calibration bucket definitions.

Replaced:

```python
determine_bucket(edge_value, bucket_definitions)

With deterministic boundary logic:

if abs_edge < 1: return "0-1"
elif abs_edge < 2: return "1-2"
elif abs_edge < 4: return "2-4"
elif abs_edge < 8: return "4-8"
else: return "8+"

Bucket boundaries are deterministic.
Calibration snapshot now only stores win rates.

2️⃣ Calibration Key Alignment

Updated references:

spread_bucket_win_rates

spread_edge_percentiles

total_edge_percentiles

Removed reference to deprecated:

bucket_win_rates

3️⃣ Model Artifact Field Alignment

Daily View updated to match actual model artifact field names:

Expected	Actual Artifact
projected_home_score	"Projected Home Score"
projected_away_score	"Projected Away score"
home_line_projection	"Home Line Projection"
projected_total	"Total Projection"
spread_pick	"Line Bet"
total_pick	"Total Bet"

Replaced strict indexing with .get() for safety.

4️⃣ Context Flag Derivation Standardized

Removed nonexistent fields:

home_b2b_flag

away_b2b_flag

Derived from:

home_rest_bucket == "b2b"

Preserves deterministic behavior without upstream mutation.

5️⃣ Defensive Access Enforcement

Converted direct dict indexing to .get() where appropriate
to prevent KeyError during artifact evolution.

6️⃣ Removed Duplicate Logic Block

Eliminated duplicated spread/percentile computation block
inside build_daily_view().

Result

Successfully rebuilt:

data/daily/daily_view_2026-02-08_v1.json

Daily View now:

Reads frozen model artifact correctly

Reads calibration snapshot correctly

Computes deterministic buckets

Computes percentiles

Produces structured, schema-stable output

Does not mutate upstream pipeline

Architectural Status

Deterministic Core: LOCKED
Calibration Snapshot: STABLE
Daily View Layer: RECONCILED
CLI Layer: UNCHANGED

No model recomputation.
No ingestion modification.
No threshold mutation.

Phase Status

Phase 4.5 Confidence Validation: COMPLETE
Daily View Stabilization: COMPLETE

System layered integrity restored.
Ready for controlled Phase 4.6 enhancement.

---

# 2026-02-18 — Runner, Analysis & Confidence Stabilization

## Type

Architecture Cleanup / Deterministic Execution Fix / Confidence Layer Alignment

---

## 1️⃣ 000_RUN_ALL.py — Corrected Execution Logic

### Problem

* `--analysis-only` was still executing full LIVE ingestion pipeline.
* Only 4 analysis scripts were being run instead of all 17.
* Execution order logic was ambiguous when mixing:

  * `--mode`
  * `--analysis`
  * `--analysis-only`

### Fix

Rewrote mode logic to:

```python
if ANALYSIS_ONLY:
    SCRIPTS = ANALYSIS
else:
    if MODE == "LIVE":
        SCRIPTS = INGESTION + FEATURES + CANONICAL + MARKET + MODELS + EVALUATION
    elif MODE == "LAB":
        SCRIPTS = FEATURES + CANONICAL + MODELS + EVALUATION

    SCRIPTS += DAILY_VIEW

    if RUN_ANALYSIS:
        SCRIPTS += ANALYSIS
```

### Result

* `--analysis-only` now runs **only analysis scripts**
* `--analysis` now runs **all 17 analysis scripts**
* No unintended ingestion
* Deterministic execution order preserved

---

## 2️⃣ Full Analysis Suite Added to Runner

Previously only:

```
analysis_001
analysis_002
analysis_003
analysis_017
```

Now includes all:

```
analysis_001 → analysis_017
```

Full deterministic evaluation coverage restored.

---

## 3️⃣ Confidence Layer Conflict Resolved

### Problem

`analysis_016_confidence_on_backtest.py` crashed with:

```
TypeError: string indices must be integers
```

Cause:

* `classify_game()` expected:

  ```python
  game["models"] → list[dict]
  ```
* But backtest artifacts contain flattened model structure
* `analysis_017` had embedded v2 confidence logic
* Arbitration layer expected legacy structure

### Architectural Issue

Two competing confidence implementations existed:

| Location                                    | Type                     |
| ------------------------------------------- | ------------------------ |
| `eng/arbitration/build_confidence_layer.py` | Deterministic classifier |
| `analysis_017_confidence_backtest_v2.py`    | Embedded v2 logic        |

### Decision (Option C)

We **did not modify the arbitration layer**.

Instead:

* Recognized structural mismatch
* Documented that analysis_017 contains v2 logic
* Left arbitration classifier as-is for future formalization

### Result

* No emergency refactor
* System remains stable
* Confidence v2 still usable in analysis context

---

## 4️⃣ Backtest Runner Path Fix

### Problem

`eng/backtest_runner.py` referenced:

```
eng/data/view/...
```

which does not exist.

### Fix

Corrected to:

```python
PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_JSON = PROJECT_ROOT / "data/view/final_game_view.json"
```

### Result

* Backtest runs clean
* No more FileNotFoundError

---

## 5️⃣ PUSH Handling Bug Identified (Grader)

Observed crash:

```
ValueError: Invalid Line Bet value: PUSH
```

Root Cause:

* `line_bet` field occasionally equals `"PUSH"`
* `grade_spread_bet()` only supports `"HOME"` or `"AWAY"`

Status:

* Identified
* Not yet refactored (low priority)
* Deterministic pipeline otherwise stable

---

## 6️⃣ Launcher UI Improvements

### Improvements

* Removed LAB buttons
* Replaced with toggle switch
* Clarified impact of:

  * LIVE
  * LAB
  * ANALYSIS
  * ANALYSIS-ONLY
* Added Streamlit launch button
* Log window moved to right
* Execution streaming stabilized

### Result

Control panel now:

* Clean
* Deterministic
* Explainer-ready for Joel
* Architecturally aligned with 000_RUN_ALL

---

## 7️⃣ Pipeline State Validation

Confirmed:

✔ Ingestion working
✔ Feature engineering stable
✔ Canonical build stable
✔ Market integration working
✔ Model injection working
✔ Backtest running
✔ Daily View building
✔ Full 17 analysis scripts executable

---

# Current System State

| Layer                 | Status                            |
| --------------------- | --------------------------------- |
| Deterministic Core    | ✅ Frozen & Stable                 |
| Multi-Model Framework | ✅ Active                          |
| Confidence Logic      | ⚠ Split (analysis vs arbitration) |
| Runner                | ✅ Corrected                       |
| UI                    | ✅ Operational                     |
| Agent Layer           | 🟡 Stubbed                        |
| Phase 6               | Not started                       |

---

# Next Minor Issue

Remaining non-blocker:

```
KeyError: 'identity'
```

In:

```
eng/ui/bookiex_dashboard.py
```

This is UI-only and does not impact:

* CLI
* Backtest
* Analysis
* Agent logic

Low priority.

---

# Summary

This thread accomplished:

* Proper runner architecture
* Full analysis execution restoration
* Confidence conflict identified and stabilized
* Backtest path repair
* UI control modernization
* Deterministic execution verified end-to-end

System is now structurally clean and ready for:

👉 Phase 6 Agent Architecture
or
👉 Formal confidence artifact unification

---

# 📘 CHANGELOG

## 2026-02-19 — Multi-Model Stabilization + Master Artifact Refactor

### 🔧 Structural Refactor

**1. Model Layer Reorganization**

* Moved `f_nba_0042_add_model.py` → `eng/models/model_0052_add_model.py`
* Renamed `model_runner.py` → `eng/models/model_0051_runner.py`
* Updated `000_RUN_ALL.py` execution order accordingly
* Removed redundant runner execution call
* Enforced correct upstream dependency ordering:

  * `model_0051_runner.py` → `model_0052_add_model.py`

---

### 🧠 Duplicate Record Bug (Critical Fix)

**Issue Identified:**

* `nba_games_multi_model_v1.json` contained duplicate game entries.
* Caused by accidental double `append()` inside `model_0051_runner.py`.

**Root Cause:**

```python
multi_output.append(...)
multi_output.append(...)   # duplicated block
```

**Fix:**

* Removed duplicate append.
* Verified:

  * 1 record per game in `nba_games_multi_model_v1.json`
  * 1 record per game in `final_game_view.json`

**Impact:**

* Eliminated many-to-many linking errors.
* Prevented downstream arbitration and backtest inconsistencies.

---

### 📊 Master Artifact Renaming (Agnostic Refactor)

Removed `nba_` prefix to generalize system:

| Old                      | New                 |
| ------------------------ | ------------------- |
| `final_game_view.json` → | `games_master.json` |
| `final_game_view.csv` →  | `games_master.csv`  |

Updated:

* `build_confidence_layer.py`
* `backtest_runner.py`
* `000_RUN_ALL.py`

Pipeline now sport-agnostic at master layer.

---

### 🧪 JSON Shape Debugging Framework

Created:

```
zzz_debug_shape_x.py
```

Enhancements:

* Supports multiple JSON targets
* Centralized `JSON_SHAPE_LIST`
* Dynamic schema inspection
* Field fill-rate analysis
* Example value preview

Used to diagnose:

* Missing projections
* Edge population rates
* Confidence tier anomalies
* Nested model dict inconsistencies

---

### 🎯 Confidence Layer Investigation

Identified Schema Evolution Issue:

* Confidence logic originally read from `model_results`
* Artifact now stores flattened fields:

  * `Spread Edge`
  * `Total Edge`
  * `Parlay Edge Score`

Mismatch caused:

```
confidence_tier = IGNORE (1296)
```

Despite 135 valid edges.

Root Cause:

* Classifier referencing deprecated structure.
* Nested `models` dict contains None values (expected).
* Flattened fields exist but not used by classifier.

Status:

* Isolated for correction in next thread.
* Core pipeline confirmed healthy.
* Edge generation verified correct (135 games).

---

### 🚀 Runner Pipeline Stabilization

Verified Full LIVE Mode Execution:

* 1296 total games
* 137 with market lines
* 135 graded in backtest
* No crash conditions
* Deterministic execution time: ~9 seconds

Execution Order Confirmed:

INGESTION → FEATURES → CANONICAL → MARKET → MODELS → ARBITRATION → BACKTEST → DAILY VIEW

All scripts return SUCCESS.

---

### 🛠 CSV Output Added to Confidence Layer

Added:

```
games_master.csv
```

Features:

* Flattened dashboard-ready export
* Deterministic ordering
* Sorted by game_id
* No nested dict pollution

---

### 🧱 Architectural Improvements

* Removed legacy field assumptions.
* Enforced flattened artifact as source of truth.
* Separated:

  * Projection logic
  * Arbitration logic
  * Confidence logic
  * Backtest logic
* Hardened refactor discipline (no silent variable drift).
* Confirmed zero many-to-many joins.

---

### 📌 Net Outcome of This Thread

✔ Duplicate model artifact fixed
✔ Master artifact generalized
✔ Pipeline execution stabilized
✔ Backtest restored
✔ Confidence bug isolated to schema mismatch
✔ Debug tooling enhanced
✔ CSV export hardened
✔ Execution runner corrected
✔ Multi-model framework structurally validated

---

## System State at End of Thread

* Deterministic core: ✅ Stable
* Multi-model artifact: ✅ Clean
* Master artifact: ✅ Clean
* Backtest: ✅ Functional
* Confidence logic: ⚠ Requires schema alignment (isolated, not structural)

---
2026-02-20 — ModelContract_v1 Edge Refactor & Full Decision Engine Promotion
🔒 Contract Update — ModelContract_v1 (Breaking Schema Change)

All models upgraded to enforce a unified deterministic schema.

New Required Keys Per Model
model_name

# TOTAL DOMAIN
total_projection
total_distance
total_edge
total_pick

# SPREAD DOMAIN (HOME-relative)
home_line_proj
spread_distance
spread_edge
spread_pick

# AGGREGATE
parlay_edge_score

# REQUIRED
context_flags
Rationale

Previously:

spread_edge and total_edge were absolute distances

True signed edge (directional advantage) was hidden

Models returned inconsistent formats

Downstream mapping logic was required

Now:

*_distance = absolute disagreement magnitude vs market

*_edge = signed model advantage vs market

No ambiguity between magnitude and direction

Downstream systems can reason correctly

Contract validation enforced in model_0051_runner.py

🧠 Model Upgrades
Joel_Baseline_v1

Refactored to compute:

spread_distance

spread_edge

total_distance

total_edge

Parlay scoring uses distance (risk-neutral confidence)

No logic change to projections or picks

FatiguePlus_v3

Promoted from helper to full independent decision engine

Computes adjusted margin and total

Outputs full ModelContract_v1 schema

Parlay score uses distance-based scoring

InjuryModel_v2

Promoted to full decision engine

Now returns signed edges + distance metrics

Deterministic even when injury impact is 0.0

MonkeyDarts_v2

Promoted to full decision engine

Deterministic per game_id

Returns signed edge + distance metrics

Now contract compliant

🧱 Architectural Improvement

Before:

Mixed helper vs decision engines

Schema inconsistencies

Hidden directional edge

Downstream ambiguity

After:

All models are deterministic full decision engines

Uniform contract enforced

Signed vs magnitude separation explicit

Downstream arbitration simplified

Agentic evolution safer

🚦Status

model_0051_runner.py contract validation passing

nba_games_multi_model_v1.json verified

Debug inspection for game 0022500808 confirmed correct field structure

CSV export stable

⚠️ Breaking Change Impact

Any downstream code referencing:

spread_edge
total_edge

must confirm whether it expects:

signed edge (NEW meaning)

distance magnitude (use *_distance)

---

## 📌 2026-02-21 — Injury Impact Engine Fix (Zero Output Resolution)

### 🔧 Component

`c_calc_020_build_team_injury_impact.py`

---

### 🐛 Issue

All `injury_impact` values were returning **0.0** for every game.

Root Causes Identified:

1. Injury snapshot date did not match `game_date` format (ISO vs date-only mismatch).
2. Zero-minute games were being included in rolling average calculation.
3. Player minute averages were diluted by DNP rows (`PT00M00.00S`).

---

### ✅ Fixes Implemented

#### 1️⃣ Snapshot Date Normalization

Converted both:

* `snapshot_date`
* `game_date`

To `YYYY-MM-DD` before grouping comparison.

Result:
Injuries now properly align with games.

---

#### 2️⃣ Rolling Average Adjustment

Updated rolling minute logic:

* Last 5 games window retained.
* **Zero-minute games excluded from average calculation.**

Old Logic:

```python
recent = mins[-window:]
player_avg[pid] = sum(recent) / len(recent)
```

New Logic:

```python
recent = mins[-window:]
non_zero_recent = [m for m in recent if m > 0]
player_avg[pid] = sum(non_zero_recent) / len(non_zero_recent)
```

Effect:
Removes DNP dilution.

---

#### 3️⃣ Injury Scaling Baseline Confirmed

Final injury value formula:

```python
injury_value = weight * (avg_minutes / 30.0)
```

30-minute baseline retained.

---

### 📊 Result Verification

Example output now correctly non-zero:

```json
{
  "game_id": "0022500808",
  "injury_impact": 2.609,
  "num_out": 4,
  "num_questionable": 0,
  "team_id": 1610612760
}
```

---

### 🧠 System Impact

| Area                    | Status                            |
| ----------------------- | --------------------------------- |
| InjuryModel_v2 Inputs   | ✅ Now Valid                       |
| Multi-Model Arbitration | ✅ Receives real injury values     |
| Derived Artifacts       | ✅ Deterministic + Player-Weighted |
| Backtest Compatibility  | ✅ Preserved                       |

---

### 🧱 Architecture Integrity

* Deterministic core preserved.
* No schema changes.
* No downstream model modification required.
* Fully backward compatible.

---

# 📘 CHANGELOG ENTRY

**File:** `eng/models/model_0052_add_model.py`
**Date:** 2026-02-21
**Phase:** Phase 4 – Confidence Layer Consolidation
**Status:** Experimental (Hybrid thresholds under evaluation)

---

## 🔧 Changes Made

### 1️⃣ Removed Legacy Confidence Layer Dependency

* Retired external `build_confidence_layer.py`
* Eliminated duplicate classifier definitions
* Centralized tier assignment inside 0052 pipeline

**Reason:**
Reduce competing sources of truth for confidence classification.

---

### 2️⃣ Updated `classify_game` Signature

Changed from:

```
classify_game(game_object)
```

To:

```
classify_game(models_dict)
```

**Reason:**
Confidence logic now operates directly on model outputs rather than flattened game structure.

---

### 3️⃣ Implemented Hybrid Magnitude Logic (Experimental)

Initial Logic:

```
cluster_aligned AND magnitude >= 4 → HIGH
```

Then tightened to:

```
cluster_aligned AND magnitude >= 6 → HIGH
cluster_aligned AND magnitude >= 3 → MODERATE
```

**Purpose:**
Test whether max-edge magnitude across models improves tier precision.

---

### 4️⃣ Updated `primary_model_source`

Now reflects:

```
CLUSTER_A
```

when alignment is detected.

Previously:

```
Joel_Baseline_v1
```

**Reason:**
Expose alignment authority separate from projection authority.

---

## ⚠️ Observations From Backtest

* HIGH exposure initially ~50%
* Tightened version ~31%
* HIGH tier win rate underperformed other tiers
* Indicates magnitude may not be predictive
* Further validation required before freezing

---

## 🧠 Architectural Insight

Today exposed:

* Hidden coupling between arbitration and analysis layers
* Need for deterministic backtest validation layer
* Magnitude ≠ predictive strength
* Confidence layer requires stable grading foundation

---

## 📌 Current State

* 0052 contains integrated confidence logic
* External arbitration module retired
* Backtest validation script rebuilt
* Hybrid thresholds not yet validated
* System not frozen

---

## 🛑 Freeze Recommendation

Before further tuning:

1. Build deterministic grading validator
2. Validate spread direction vs result logic
3. Confirm parlay_result correctness
4. Then resume tier calibration

---

## 2026-02-23 — Rolling Team Averages Integration + Net Rating Recalculation

**Component:**  
- `c_calc_014_rolling_team_averages.py`  
- `d_nba_021_build_canonical_games.py`  
- Downstream: `final_game_view.json` (multi-model aggregation)

**Type:**  
Schema correction / Join fix / Context recalibration

**Scope Rule:**  
Additive + corrective. Deterministic core preserved.

---

### Background

Canonical previously used:
- `nba_team_averages.json` (static / rest-bucket contextual averages)

Rolling team averages were introduced via:
- `nba_team_rolling_averages.json`

However:
- Canonical was incorrectly joining rolling data only by `game_id`
- This caused side-level misalignment risk
- `net_rating` was previously inherited from static averages

---

### Fixes Applied

#### 1️⃣ Rolling Join Correction

Updated canonical integration to:

- Use per-team, per-side rolling averages
- Ensure `2 rows per game` integrity (home + away)
- Pull:
  - `rolling_avg_points_for`
  - `rolling_avg_points_against`

Result:
```

avg_points_for     ← rolling_avg_points_for
avg_points_against ← rolling_avg_points_against

````

---

#### 2️⃣ Net Rating Recalculated

Replaced legacy static net rating with dynamic computation:

```python
net_rating = avg_points_for - avg_points_against
````

Now reflects:

* Rolling offensive performance
* Rolling defensive performance
* No dependency on deprecated aggregate file

Example (Game 0022500824 – MIN):

Before:

```
home_net_rating = 7.11  (static)
```

After:

```
116.25806451612904
-
110.6774193548387
=
5.5806451612903345
```

---

#### 3️⃣ Downstream Model Impact

Because Joel_Baseline_v1 uses:

```
home_avg_points_for
home_avg_points_against
away_avg_points_for
away_avg_points_against
```

Model projections shifted accordingly.

Observed effects:

* Home line projection changed
* Spread edge magnitude adjusted
* Total projections recalibrated
* Arbitration tier scores updated

No pipeline breakage.
No schema change.
Only contextual recalibration.

---

### Validation Performed

* `zzz_debug_shape_specfic.py` confirms:

  * Rolling values correctly appear in canonical
  * Net rating matches computed delta
* Row count unchanged: `2592`
* Multi-model artifact regenerates successfully
* No leakage detected

---

### Architectural Result

| Layer              | Status             |
| ------------------ | ------------------ |
| ETL                | Stable             |
| Canonical          | Rolling-integrated |
| Net Rating         | Dynamic            |
| Models             | Context-adjusted   |
| Arbitration        | Recalibrated       |
| Deterministic Core | Preserved          |

---

### Why This Matters

* Eliminates dependency on static team averages
* Ensures projections use game-relative form
* Aligns fatigue + scoring context
* Improves signal integrity before Phase 4+ refinement

---

**Status:** ✅ Integrated
**Risk Level:** Low (validated across canonical + multi-model layer)
**Phase Impact:** Strengthens Phase 4 model consistency

```

---

## 2026-02-23 — Confidence Engine Extraction (Phase 4.6 Structural Cleanup)

**Component:** eng/arbitration/confidence_engine.py  
**Related:** eng/models/model_0052_add_model.py  
**Type:** Architectural refactor (behavior-preserving)  
**Scope Rule:** No math changes. No threshold changes. Additive structural cleanup only.

### Background
Confidence classification logic was previously defined inline inside 
`model_0052_add_model.py`, despite earlier intent to centralize it 
as a reusable engine module.

A partial extraction had been started previously but was not 
behavior-identical, leading to duplication and governance drift.

### Action Taken
- Extracted the EXACT `classify_game()` logic from `model_0052_add_model.py`
- Created `eng/arbitration/confidence_engine.py`
- Preserved:
  - BASELINE_ONLY alignment behavior
  - refined disagreement_flag logic
  - reference_edge computation
  - tier thresholds (2 / 4 cutoffs)
- Updated 0052 to import:
  `from eng.arbitration.confidence_engine import classify_game`
- Removed inline classifier from 0052
- Verified no output differences across:
  - confidence_tier
  - cluster_alignment
  - disagreement_flag
  - primary_model_source

### Validation
- Single-game debug comparison: identical
- Full dataset shape validation: identical
- No change to backtest inputs
- Determinism preserved

### Result
Confidence logic now has a single source of truth.
Structural cleanup complete.
Phase 4.6 Confidence Logic Centralization complete.

### Phase 4.6 Gate — Confidence Policy Freeze

Confidence classification logic is now frozen.

Location:
eng/arbitration/confidence_engine.py

Policy includes:
- Hybrid magnitude logic
- CLUSTER_A / BASELINE_ONLY alignment states
- Refined disagreement_flag logic
- Tier thresholds: 2 / 4
- Primary model source determination

No further modifications allowed without advancing to a new Phase.

## 2026-02-23 — games_master.json Retirement & Artifact Repoint

**Component:** Pipeline artifact routing  
**Type:** Structural cleanup (behavior-preserving)  
**Scope Rule:** No model math changes. No confidence logic changes.

### Background
Earlier architecture temporarily introduced `games_master.json` as an output
from the standalone confidence layer. Downstream consumers (backtest_runner,
daily view) were repointed to use that artifact.

Confidence logic has now been:
- Extracted into `eng/arbitration/confidence_engine.py`
- Re-embedded into `model_0052_add_model.py`
- Behavior verified as identical

The standalone confidence artifact writer is fully retired.

### Action Taken
- Confirmed `model_0052_add_model.py` produces:
  `data/view/final_game_view.json`
- Repointed downstream consumers from:
  `data/view/games_master.json`
  back to:
  `data/view/final_game_view.json`

Files updated:
- eng/backtest_runner.py
- eng/daily/build_daily_view.py

### Retired
- games_master.json (artifact)
- zzz_0223-01-RETIRED-build_confidence_layer.py
- Any residual references to games_master.json

### Validation
- Full pipeline run completed with no errors
- final_game_view.json regenerated successfully
- Backtest executed successfully
- Daily view built successfully
- No field drift observed

### Result
Single artifact architecture restored:

0051 → multi_model.json  
0052 → final_game_view.json (includes confidence)  
Backtest + Daily → consume final_game_view.json  

Artifact duplication eliminated.
Pipeline simplified.
Structural integrity restored.


---

## 2026-02-24 — Daily View Exposure + Temporal Integrity Layer

### Scope

Enhancement to `eng/daily/build_daily_view.py` and debugging tooling.
No deterministic core changes.
No model logic changes.
Read-only augmentation only.

---

## 1️⃣ Daily View — Full Model Exposure CSV

### Added

* `flatten_for_csv()` updated to:

  * Produce **one row per model per game**
  * Include:

    * Identity
    * Market state
    * Model-level outputs
    * Arbitration
    * Edge metrics
    * Context flags
    * Calibration tags
    * Agent overrides

### Added

* Timestamped CSV output:

  ```
  daily_view_{date}_v1_{YYYYMMDD_HHMMSS}.csv
  ```

### Result

* No hidden model data
* Fully auditable multi-model visibility
* Deterministic export
* No schema break to JSON artifact

---

## 2️⃣ Temporal Integrity Layer (Non-Destructive Enhancement)

### Added to Daily View JSON:

```json
"temporal_integrity": {
    "schedule_date_utc": "...",
    "tipoff_time_utc": "...",
    "tipoff_time_cst": "...",
    "tipoff_local_day": "...",
    "schedule_matches_local_day": true/false,
    "utc_rollover_flag": true/false
}
```

### Purpose

Clarify distinction between:

* `game_date` (schedule anchor)
* `nba_game_day_local`
* `odds_commence_time_utc`
* `odds_commence_time_cst`

### Verified

* CST ↔ UTC rollover behavior correctly identified
* Evening games properly flag `utc_rollover_flag = true`
* No temporal mismatches found

### Impact

Improves:

* Debug transparency
* Human explainability
* Future audit readiness
* Agent layer safety

No pipeline refactor required.

---

## 3️⃣ Debug Tool Enhancement

Updated `zzz_debug_shape_specific.py` to:

* Support both:

  * Flat legacy schema
  * Structured Daily View schema
* Properly locate:

  ```
  identity.game_id
  ```

Result:

* Daily artifacts now inspectable
* No more "TARGET GAME NOT FOUND" false negatives

---

## 4️⃣ Structural Clarification Identified (No Change Applied)

Observation:

* Top-level artifact surfaces:

  * Projected margin
  * Projected total
* Does not surface:

  * Explicit projected home/away scores

Decision:

* No refactor at this time.
* Item intentionally paused.

---

# 📊 System State After This Session

| Component          | Status         |
| ------------------ | -------------- |
| Deterministic Core | LOCKED         |
| Multi-Model Layer  | Stable         |
| Arbitration        | Stable         |
| Daily View JSON    | Enhanced       |
| CSV Exposure       | Fully Expanded |
| Temporal Integrity | Added          |
| Debug Tooling      | Updated        |
| Schema Integrity   | Preserved      |

---

No refactors.
No recalibration.
No model changes.
Pure visibility + clarity upgrade.

---
## 2026-02-24 — UI Structural Refactor (Tier + Actionability Separation)

### Summary
Refactored BookieX Dashboard to cleanly separate:
- Structural Strength (Confidence Tier)
- Execution Decision (Actionability)

Removed semantic overlap between Tier logic and Confidence Gate.

---

### Core Architectural Decision

**Tier = Structural Strength (Consensus + Weighted Score)**
**Actionability = Execution Threshold (Magnitude Gate Only)**

Tier no longer influences actionability.

---

### Changes Made

#### 1️⃣ model_0052_add_model.py

- Removed hybrid Tier → Actionability mapping.
- Actionability now determined exclusively via:
  - `apply_confidence_gate()`
- Tier remains structural and informational.

Before:

Tier influenced actionability (LOW → INFO, IGNORE → NONE).


After:

Actionability is strictly magnitude-driven.
Tier is independent structural metadata.


---

#### 2️⃣ bookiex_dashboard.py

Added:
- Tier radio filter: `["ALL", "HIGH", "MEDIUM", "LOW"]`
- Proper filtering order:
    1. Actionability
    2. Disagreement
    3. Tier
    4. Render

Moved filtering logic above expander block to ensure deterministic behavior.

Added to Model Output display:
- Confidence Tier
- Cluster Alignment

---

### UI Now Supports

Primary Filter:
- ACTION
- INFO
- IGNORE
- DISAGREEMENT
- WHY
- ALL

Secondary Structural Filter:
- HIGH
- MEDIUM
- LOW

These filters stack cleanly.

---

### Resulting System Clarity

| Layer | Meaning |
|--------|---------|
| Tier | Structural model strength |
| Cluster Alignment | Directional agreement |
| Calibration Bucket | Historical performance |
| Actionability | Execution threshold decision |

All layers now independent and visible.

---

### Status

✅ Deterministic  
✅ No semantic overlap  
✅ UI stable  
✅ Filtering consistent  

---

## 📘 CHANGELOG — analysis_017_confidence_backtest_v2 Refactor

**Date:** 2026-02-25
**Scope:** Stability + Schema Alignment
**File:** `eng/analysis/analysis_017_confidence_backtest_v2.py`

---

### ✅ Fixes Applied

#### 1️⃣ Backtest Directory Selection

* Replaced lexicographic sorting with **modification-time selection**.
* Excluded archived folders (`zzz_*`) from candidate directories.
* Prevents accidental selection of `zzz_archived_backtests`.

**Impact:** Correct latest backtest run is always selected.

---

#### 2️⃣ Model Schema Update

* Updated `models` handling:

  * From list iteration → dict `.values()` iteration.
* Replaced deprecated `"edge"` field with `"total_edge"`.

**Impact:** Script now aligned with `nba_games_multi_model_v1.json` schema.

---

#### 3️⃣ Tier Classification Alignment

* Updated classifier to operate on dict-based models.
* Added `"INSUFFICIENT"` tier for low-signal cases.

**Impact:** Confidence logic remains consistent and deterministic.

---

### 🎯 Result

* Script executes without errors.
* Uses correct latest backtest artifact.
* Fully aligned with current multi-model architecture.
* No dependency on retired JSON artifacts.

---

## 📘 CHANGELOG — Full Analysis Suite Schema Alignment

**Date:** 2026-02-25
**Scope:** LIVE Analysis Suite Stabilization
**Mode:** `000_RUN_ALL.py --mode LIVE --analysis-only`
**Result:** 17/17 analysis scripts executing successfully

---

### ✅ 1️⃣ Model Schema Migration (List → Dict)

Refactored all affected analysis scripts to support:

```python
game["models"]  # dict keyed by model_name
```

Instead of legacy:

```python
for m in game["models"]:  # list
```

Updated scripts:

* analysis_004
* analysis_005
* analysis_006
* analysis_007
* analysis_014
* analysis_017

---

### ✅ 2️⃣ Field Name Standardization

Replaced deprecated fields:

| Old                | New                               |
| ------------------ | --------------------------------- |
| `"edge"`           | `"spread_edge"` or `"total_edge"` |
| `"Baseline_v1"`    | `"Joel_Baseline_v1"`              |
| `"FatiguePlus_v2"` | `"FatiguePlus_v3"`                |

All analysis scripts now align to current multi-model artifact.

---

### ✅ 3️⃣ Confidence Artifact Consolidation

Retired:

```
nba_games_multi_model_with_confidence.json
```

Confidence now sourced from:

```
data/view/final_game_view.json
```

Ensures:

* Single source of truth
* No duplicate artifacts
* Deterministic pipeline boundary

---

### ✅ 4️⃣ Backtest Directory Selection Fix

Improved latest backtest resolution:

* Excluded `zzz_archived_backtests`
* Switched from lexicographic sort → modification-time selection
* Prevented archived folder collision

Applied to:

* analysis_017_confidence_backtest_v2.py

---

### ✅ 5️⃣ Execution Validation

Full LIVE analysis run:

* 17 / 17 scripts SUCCESS
* Total execution time: ~3.0 seconds
* No schema errors
* No missing artifacts
* No retired dependencies

---

## 🎯 Status

* Deterministic core stable
* Analysis layer schema-aligned
* Confidence + backtest integration stable
* LIVE pipeline integrity confirmed

---

## 2026-02-25 — Spread Grader Orientation Fix

### ✅ Fixed

Corrected ATS grading logic in `eng/backtest_grader.py`.

### 🔧 Issue

Spread grading previously compared:

```
actual_margin > spread_home
```

This incorrectly graded home underdogs and caused silent ATS mislabeling.

### 🛠 Change Implemented

Replaced comparison logic with proper sportsbook rule:

```
adjusted_margin = actual_margin + spread_home
```

Grading now:

* HOME wins if `adjusted_margin > 0`
* AWAY wins if `adjusted_margin < 0`
* PUSH if `adjusted_margin == 0`

### 📊 Validation

* Example game 0022500664 corrected from LOSS → WIN
* Flip test now produces worse results (expected)
* Spread orientation probe confirms correct sign usage
* Updated true performance:

  * 178 bets
  * 95-80-3
  * 54.3% Win Rate
  * +3.6% ROI

### 🎯 Impact

Backtest results now reflect correct ATS evaluation.
Spread grading logic is aligned with sportsbook conventions.

---

# 📜 CHANGELOG — Backtest Model-Level Grading (2026-02-26)

## ✅ Enhancement: Per-Model Outcome Evaluation Added

### What Changed

Previously:

* `model_results` duplicated `models`
* No per-model grading existed
* Backtest only graded final selected bets

Now:

* `model_results` contains deterministic per-model outcomes
* Each model is graded for:

  * `spread_result`
  * `total_result`
  * `parlay_result`
* Uses existing `grade_spread_bet`, `grade_total_bet`, and `grade_parlay`
* No duplicate grading logic introduced

---

## 🏗 Structural Improvement

Separated responsibilities clearly:

| Field           | Purpose                       |
| --------------- | ----------------------------- |
| `models`        | Model projections + edges     |
| `model_results` | Model performance outcomes    |
| `spread_result` | Final selected spread outcome |
| `total_result`  | Final selected total outcome  |
| `parlay_result` | Final selected parlay outcome |

No schema mutation upstream.
No grading math duplication.
No legacy duplication.

---

## 🎯 Why This Matters

* Enables per-model performance tracking
* Preserves deterministic grading logic
* Converts backtest artifact from descriptive → analytical
* Removes prior structural duplication bug

---

## 🔒 Stability Status

Backtest layer now:

* Deterministic
* Internally consistent
* Architecturally clean
* Ready for summary-level analytics

---

# 📘 CHANGELOG — 2026-02-26

## Authority-Driven Explanation Refactor

### 🔧 Summary

Refactored `build_decision_explanation()` to eliminate schema drift and bind explanation logic to explicit model authority via `selection_authority`.

---

## 🎯 Problem

* Explanation field was empty (0% populated).
* Root cause: explainer referenced legacy top-level fields (`spread_pick`, `total_pick`, etc.) that no longer exist post multi-model refactor.
* Schema drift occurred after flattening changes and model independence transition.

---

## ✅ Solution

### 1️⃣ Authority Binding

Rewrote `build_decision_explanation()` to:

* Read from:

  ```python
  game["selection_authority"]
  game["models"][selection_authority]
  ```
* Pull nested:

  * `spread_pick`
  * `total_pick`
  * `home_line_proj`
  * `total_projection`
  * `spread_edge`
  * `total_edge`

This removes dependency on flattened fields.

---

### 2️⃣ Early Exit Behavior (Preserved)

For games without actionable signal:

```python
return {
    "decision_explanation": None,
    "decision_factors": {}
}
```

Non-betting games remain silent.

---

## 📊 Validation

After rebuild:

* `Explanation` populated for 184 games (14.2%)
* `Decision Factors` correctly populated for actionable games
* Nested values match authoritative model output
* No schema drift
* No impact to arbitration layer
* No impact to backtest layer

Confirmed via:

```
zzz_debug_shape_x.py
zzz_debug_shape_specfic.py
```

---

## 🏗 Architectural Improvement

Explanation is now:

> Authority-driven, not field-driven.

This supports future evolution toward:

* Arbitration-based authority
* Multi-model selection logic
* Agentic decision narrative layers

No further refactor required when authority becomes dynamic.

---

## ⚠️ Known Observations

* `primary_model_source` and `selection_authority` currently represent separate concepts.
* Authority is still deterministic (Joel_Baseline_v1).
* Arbitration influences metadata only.

This is intentional for current phase.

---

## 📌 Status

System integrity confirmed.

* Deterministic authority ✔
* Multi-model structure intact ✔
* Explanation layer restored ✔
* Backtest unaffected ✔
* Daily view stable ✔

---

# 📘 CHANGELOG — Arbitration Field Refactor

## 🗓 Date

2026-02-25

---

## 🏷 Refactor: `primary_model_source` → `arbitration_cluster`

### 🎯 Objective

Eliminate conceptual ambiguity between:

* **Decision Authority** → `selection_authority`
* **Signal Group / Alignment Context** → `arbitration_cluster`

The previous field name (`primary_model_source`) implied execution authority, which conflicted with the new deterministic authority model.

---

## 🔧 Changes Implemented

### 1️⃣ Field Rename (No Logic Change)

Renamed:

```python
primary_model_source
```

To:

```python
arbitration_cluster
```

This field now clearly represents:

> The arbitration signal cluster that aligned for this game
> (e.g., CLUSTER_A, CLUSTER_B, NONE)

---

### 2️⃣ Files Updated (Live Only)

* `eng/models/model_0052_add_model.py`
* `eng/daily/build_daily_view.py`
* `eng/ui/bookiex_dashboard.py`

Archived (`zzz_`) files were intentionally not modified.

---

### 3️⃣ UI Update

Dashboard label updated from:

```
Primary Model:
```

To:

```
Arbitration Cluster:
```

This prevents confusion between:

* `selection_authority`
* `arbitration_cluster`
* `confidence_tier`

---

## 🧠 Architectural State After Refactor

Current deterministic execution stack:

```
selection_authority   → Who made the final decision (Joel_Baseline_v1)
arbitration_cluster   → Which signal group aligned
confidence_tier       → Risk classification
cluster_alignment     → Model agreement bucket
disagreement_flag     → Signal dispersion
Explanation           → Authority narrative
Decision Factors      → Authority metrics
```

Execution authority remains deterministic (Joel) until multi-model arbitration drives final selection.

---

## 🔍 Validation

* Full pipeline executed successfully.
* `build_daily_view.py` completed without errors.
* `final_game_view.json` reflects new field.
* Streamlit dashboard renders correctly.
* No downstream breakage observed.

---

## 🚧 Future Intent

When arbitration-driven authority is implemented:

* `selection_authority` will become dynamic.
* `arbitration_cluster` will remain contextual metadata.
* `determine_primary_model_source()` may be renamed to reflect arbitration semantics.

---

## 🏗 Status

✔ Structural rename complete
✔ Semantic clarity improved
✔ Deterministic authority preserved
✔ System stable

---
```markdown
## 2026-02-26 — Goal 1 Complete: Game-Level Roll-Up UI

### Summary
Refactored dashboard layout to support executive-level scanning with collapsible game cards and integrated strength signaling.

---

### 🔹 UI Changes

- Replaced flat game display with **collapsible game-level expanders**
- Implemented **roll-up header format**:

```

Away @ Home: Take Spread / Total — TIER | % Strength

```

- Added normalized **Overall Strength %** to header
- Integrated **Signal Strength bars** inside each game card
- Tightened vertical spacing between games
- Moved **Why section above Model Details** for cleaner evaluation flow

---

### 🔹 Governance Clarity

- Explicitly labeled `MonkeyDarts_v2` as:

```

🚫 (Excluded from Arbitration)

```

- Ensured arbitration structure remains transparent and auditable

---

### 🔹 Result

- Executive-scan friendly
- Structurally coherent
- Arbitration governance clearly communicated
- Production-ready UI for Joel review

**Status: Goal 1 Approved & Complete**
```
