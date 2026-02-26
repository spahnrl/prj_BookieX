# PHASE 2 — ANALYST AGENT READ SCOPE  
Version: v1  
Status: LOCKED  

---

## Purpose

Define and enforce strict read-only boundaries for the BookieX Analyst Agent.

The Analyst Agent is an explainer layer.  
It does not compute, modify, or override model outputs.

This document defines exactly what the agent may read — and what it may never access.

---

# ✅ ALLOWED ARTIFACTS

The Analyst Agent may read only the following artifacts:

---

## 1️⃣ Daily View Artifact

Path pattern:

data/daily/daily_view_YYYY-MM-DD_v1.json

Provides:

- ACTION games
- Edge metrics
- Percentile classifications
- Confidence classification
- Calibration bucket tags
- Context flags
- Market snapshot
- Artifact hash linkage

This is the primary source of truth for daily explanation.

---

## 2️⃣ Calibration Snapshot

Path:

eng/calibration/calibration_snapshot_v1.json

Provides:

- Historical bucket win rates
- Edge percentiles
- Bias baselines
- Backtest metadata

Used strictly for contextual explanation.

---

## 3️⃣ Optional Prior Daily View

Path pattern:

data/daily/daily_view_<prior_date>_v1.json

Used only for delta comparison (WHAT CHANGED).

---

# ❌ FORBIDDEN ACCESS

The Analyst Agent may NOT read:

- data/view/nba_games_game_level_with_odds_model.json
- eng/backtest_*
- eng/outputs/backtests/*
- eng/*_calc_*
- eng/ingest_*
- eng/join_*
- eng/rebuild_*
- data/derived/*
- Any raw ingestion source
- Any API endpoint
- Any external data source

The Analyst Agent must never access upstream computation artifacts.

---

# 🔒 ENFORCEMENT RULE

The Analyst Agent must:

- Restrict file access to:
  - data/daily/
  - eng/calibration/
- Reject any file path outside those directories.
- Never accept arbitrary user-supplied file paths.

All access must be programmatically constrained.

---

# 🧱 ARCHITECTURAL SEPARATION

Pipeline layers:

Compute → Freeze → Explain

The Analyst Agent exists only in the Explain layer.

It cannot reach backward into Compute or Calibration generation layers.

---

# 🚫 NON-NEGOTIABLE RULES

The Analyst Agent:

- Does not recompute projections.
- Does not recalculate edges.
- Does not modify picks.
- Does not change thresholds.
- Does not write to data directories.
- Does not trigger ingestion.
- Does not alter calibration.

It explains results only.

---

END OF READ SCOPE CONTRACT (v1)