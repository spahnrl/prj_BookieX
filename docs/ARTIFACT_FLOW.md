# ARTIFACT FLOW — BOOKIEX

Last Updated: 2026-02-19  
Status: Canonical

This document defines the deterministic artifact pipeline for BookieX.

BookieX is a layered system.
Each layer produces exactly one artifact.
Each downstream layer reads from only one upstream artifact.

No layer may recompute upstream logic.

---

# 🔵 High-Level Flow

INGESTION  
→ canonical_game_level.json  

MODEL EXPANSION  
→ nba_games_multi_model_v1.json  

FLATTENING  
→ final_game_view.json  

CONFIDENCE LAYER  
→ games_master.json  

BACKTEST  
→ backtest_runner.py outputs  

CLI / ANALYST  
→ Daily View  

---

# 🧱 Detailed Layer-by-Layer Breakdown

---

## 1️⃣ Ingestion Layer

Purpose:
Create canonical game-level dataset with market odds merged.

Produces:
data/view/nba_games_game_level_with_odds.json

Characteristics:
- One row per game_id
- Market spreads / totals included
- Rest, fatigue, ratings included
- No model projections

This is raw structured game data.

---

## 2️⃣ Multi-Model Layer (Phase 4)

Purpose:
Run independent models against identical base data.

Models:
- Joel_Baseline_v1
- FatiguePlus_v2
- InjuryModel_v1
- MonkeyDarts_v1
- MarketPressure_v1

Produces:
data/view/nba_games_multi_model_v1.json

Structure:
- One row per game_id
- Nested `models` dictionary
- Each model contains projection + edge

Enforcement:
- Duplicate game_id rows are forbidden
- Model runner must be idempotent

This artifact is NOT authoritative downstream.

---

## 3️⃣ Flattening Layer

Purpose:
Extract authoritative projection + edge values.

Produces:
data/view/final_game_view.json

Characteristics:
- One row per game_id
- Flattened fields:
  - Spread Edge
  - Total Edge
  - Parlay Edge Score
  - Line Bet
  - Total Bet
- Nested `models` retained for traceability only

This becomes the pre-confidence artifact.

---

## 4️⃣ Confidence Layer

Purpose:
Classify games using deterministic cluster logic.

Reads:
final_game_view.json

Produces:
data/view/games_master.json

Adds:
- confidence_tier
- confidence_reason
- cluster_alignment
- disagreement_flag

Contract:
Confidence operates only on flattened fields.
Nested model dictionaries are informational only.

games_master.json is the canonical final artifact.

---

## 5️⃣ Backtest Layer

Reads:
games_master.json

Strict Rules:
- No recomputation
- No reading nested models
- No upstream mutation

Outputs:
- Win rate
- ROI
- Tier breakdown
- Alignment breakdown

Backtest must fail fast if:
- Duplicate game_id exists
- Required fields missing
- Structure malformed

---

## 6️⃣ CLI / Analyst Layer

Reads:
games_master.json

Produces:
- Daily View
- Explanations
- Why / Ignore / Action responses

Agents:
- May read only
- May not modify artifacts
- May not alter edges or projections

Kitchen (deterministic) vs Dining Room (agentic) boundary enforced.

---

# 🔒 Deterministic Boundary

The following are immutable once written:

- nba_games_multi_model_v1.json
- final_game_view.json
- games_master.json

Only upstream scripts may regenerate them.

No downstream layer may modify them.

---

# 📦 Canonical Artifact Summary

| Layer | Artifact | Authoritative? |
|-------|----------|----------------|
| Ingestion | nba_games_game_level_with_odds.json | Yes (raw base) |
| Multi-Model | nba_games_multi_model_v1.json | No |
| Flattened | final_game_view.json | Yes (pre-confidence) |
| Confidence | games_master.json | YES (final canonical) |
| Backtest | Derived metrics | No (analysis only) |

---

# 🧠 Mental Model

Think of BookieX as:

Kitchen:
- Ingest
- Model
- Flatten
- Classify

Dining Room:
- Backtest
- CLI
- Analyst Agent

No food goes backward into the kitchen.

---

# 🚨 Structural Guarantees

System must always enforce:

- Exactly one row per game_id
- No duplicate append behavior
- Flattened fields are authoritative
- Nested model dictionary never used downstream
- Backtest reads only canonical artifact

If any of the above fail, system integrity is compromised.

---

# 📌 Current Canonical Artifact

data/view/games_master.json

This is the single source of truth for:

- Decision logic
- Confidence
- Backtesting
- UI
- Agent explanation

All future phases build on this artifact.