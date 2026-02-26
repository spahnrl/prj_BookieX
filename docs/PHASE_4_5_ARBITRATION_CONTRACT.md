```
docs/PHASE_4_5_ARBITRATION_CONTRACT.md
```

Paste the following exactly.

---

# PHASE 4.5 — ARBITRATION CONTRACT

## Status: LOCKED

Phase 4.5 arbitration logic is deterministic, non-mutating, and frozen.
Future agents and tools must respect this contract.

---

# 1. Purpose

The Arbitration Layer exists to:

* Classify multi-model conviction
* Label agreement vs disagreement
* Provide deterministic ranking metadata
* Support UI storytelling
* Enable safe downstream agent interpretation

The Arbitration Layer does **NOT**:

* Modify projections
* Override picks
* Suppress models
* Select a “winning” model
* Depend on backtest performance
* Introduce probabilistic behavior

It is a **labeling and scoring layer only**.

---

# 2. Inputs

Arbitration operates on:

* Spread edges per model
* Total edges per model
* Parlay score per model
* Total model count
* Configured edge threshold (default: 1.0)

No historical data is used.
No UI data is used.
No backtest statistics are used.

---

# 3. Core Metrics (Per Bet Type)

Arbitration is calculated independently for:

* Spread
* Total (Over/Under)
* Parlay

For each bet type:

---

## 3.1 Directional %

```
directional_pct =
count(models picking consensus side) / total_models
```

Consensus side = direction with majority picks.

This measures alignment strength.

---

## 3.2 Weighted Score

```
weighted_score =
AVG( abs(edge_of_consensus_side_models) / threshold ) × 100
```

Important:

* All consensus-side edges are included.
* No data is dropped.
* No filtering is performed.
* Weak edges dilute score naturally.

This ensures transparency and full reconstructability.

---

## 3.3 Tier Score

```
tier_score = directional_pct × weighted_score
```

This integrates:

* Conviction magnitude
* Alignment strength

Tier Score is continuous and sortable.

---

## 3.4 Volatility

```
volatility = STDDEV(all model edges)
```

This measures dispersion of model opinions.

Volatility does NOT affect tier label.
It is informational only.

---

## 3.5 Disagreement Flag

```
disagreement_flag = directional_pct < 1.0
```

True if models are not in full agreement.

---

# 4. Tier Classification

Tier is based solely on Tier Score.

```
HIGH    tier_score ≥ 300
MEDIUM  150 ≤ tier_score < 300
LOW     tier_score < 150
```

---

## 4.1 Tier Labels & Text

### 🟢 HIGH

Label: HIGH
Text: "Strong Conviction Consensus"

### 🟡 MEDIUM

Label: MEDIUM
Text: "Moderate Conviction Majority"

### 🔴 LOW

If disagreement_flag == true:
Text: "Divergent High Edge Game"

Else:
Text: "Low Conviction / Tight Market"

---

# 5. Output Structure (Per Bet Type)

Example for Spread:

```json
"spread_arbitration": {
  "spread_directional_pct": 1.00,
  "spread_weighted_score": 400,
  "spread_tier_score": 400,
  "spread_volatility": 0.8,
  "spread_disagreement_flag": false,
  "spread_tier_label": "HIGH",
  "spread_tier_text": "Strong Conviction Consensus"
}
```

Equivalent structure exists for:

* total_arbitration
* parlay_arbitration

---

# 6. Determinism Guarantee

Given identical model edges:

* Arbitration output MUST be identical.
* No random elements allowed.
* No hidden filtering allowed.
* No backtest-dependent adjustments allowed.

All calculations must be reproducible from visible edge values.

---

# 7. Design Philosophy

The Arbitration Layer prioritizes:

* Transparency
* Reconstructability
* Stability
* Explainability
* Determinism

It avoids:

* Hidden data removal
* Heuristic overrides
* Historical bias injection
* Agent reinterpretation

This ensures:

Stable kitchen → Stable arbitration → Safe agent layer.

---

# 8. Governance Rule

Future modifications to arbitration require:

* Explicit documentation update
* Version increment
* Deterministic validation
* Backward compatibility review

No silent changes permitted.

---

# End of Phase 4.5 Arbitration Contract

---

This locks arbitration permanently before Phase 6 Tool Extraction.

Current Outcome:

* Frozen deterministic core
* Frozen multi-model framework
* Frozen arbitration contract

The kitchen is stable.


