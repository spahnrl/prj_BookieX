# CHANGELOG_NCAAM_ALIGNMENT

## Milestone
NCAAM MVP architecture aligned closer to NBA core patterns.

## What Changed

### 1. Model Layer Alignment
- Added independent NCAA model file:
  - `eng/models/ncaam_avg_score_model.py`
- Revised NCAA runner to use a registry-driven model architecture:
  - `eng/models/model_0051_runner_ncaam.py`
- NCAA runner now:
  - uses `MODEL_REGISTRY`
  - validates a shared model contract
  - writes multi-model JSON
  - writes flat CSV summary

### 2. Daily View Alignment
- Revised:
  - `eng/daily/build_daily_view_ncaam.py`
- Standardized naming from `AUTHORITATIVE_MODEL` to `selection_authority`
- Daily output now writes:
  - dated JSON
  - timestamped CSV
- JSON now uses a metadata wrapper and grouped sections more similar to NBA

### 3. Backtest Alignment
- Revised:
  - `eng/backtest_runner_ncaam.py`
- NCAA backtest now:
  - reads multi-model JSON
  - uses `selection_authority`
  - writes timestamped output directories
  - writes detail JSON
  - writes detail CSV
  - writes summary JSON
  - grades all models independently

## Current NCAA MVP Status
Working:
- odds ingestion
- odds flattening
- market team map
- alias table
- schedule ingestion
- schedule/team join
- matched-only boxscore ingestion
- canonical games
- line join
- multi-model runner
- daily view
- backtest

## Current Observed Coverage
- model input games: 52
- graded backtest games: 39
- skipped games: 13
- spread graded rows: 3
- total graded rows: 4

## Known Limitations
- team identity mapping incomplete
- line-join coverage incomplete
- boxscore coverage partial
- baseline model is still simple
- no calibration layer
- no execution overlay
- no NCAA analysis suite yet

## Next Planned Feature Work
Selective reuse from NBA:
- next: `c_ncaam_015_build_last5_momentum.py`

Deferred for now:
- rest-day logic
- fatigue logic
- injuries
- confidence/arbitration
- execution overlay