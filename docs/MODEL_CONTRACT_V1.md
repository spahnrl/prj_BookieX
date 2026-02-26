# 🔒 MODEL_CONTRACT_V1.md (Corrected Formal Freeze)

# MODEL CONTRACT V1

**Project:** prj_BookieX
**Status:** Frozen
**Effective Date:** 2026-02-20
**Revision:** v1.1 (Distance + Signed Edge Clarification)

---

## 🎯 Purpose

Defines the required return schema for all predictive models executed by `model_0051_runner.py`.

All models must return this exact structure.

No missing keys.
No additional required keys.
Optional fields must still be present with `None` if unused.

This contract enables:

* Deterministic multi-model execution
* Arbitration
* Confidence modeling
* Agent read-only integrity
* NCAA portability
* Stable JSON artifacts

---

## 📦 Required Return Schema

Every model must return:

```python
{
    "model_name": str,

    # -------- TOTAL DOMAIN --------
    "total_projection": float | None,
    "total_distance": float | None,
    "total_edge": float | None,
    "total_pick": str | None,

    # -------- SPREAD DOMAIN (HOME-RELATIVE) --------
    "home_line_proj": float | None,
    "spread_distance": float | None,
    "spread_edge": float | None,
    "spread_pick": str | None,

    # -------- AGGREGATE --------
    "parlay_edge_score": float | None,

    # -------- REQUIRED --------
    "context_flags": dict
}
```

---

# 🧠 Definitions (Precise + Non-Ambiguous)

## TOTAL DOMAIN

### total_projection

Model-projected total points.

---

### total_distance

Magnitude-only difference between model total and market total.

```
abs(total_projection - market_total)
```

Risk-neutral disagreement size.

Always ≥ 0.

---

### total_edge

Signed directional difference between model total and market total.

```
total_projection - market_total
```

Positive → Model leans OVER
Negative → Model leans UNDER

Directional truth.

---

### total_pick

"OVER", "UNDER", or None.

---

# SPREAD DOMAIN (HOME-RELATIVE ONLY)

All spread calculations are HOME-relative.

---

### home_line_proj

Model-projected home margin.

This is the model's expected:

```
(home points - away points)
```

Compared directly to market `spread_home_last`.

---

### spread_distance

Magnitude-only disagreement size.

```
abs(home_line_proj - spread_home)
```

Always ≥ 0.

Used for:

* Confidence
* Parlay strength
* Model comparison magnitude

---

### spread_edge

Signed directional edge.

```
home_line_proj - spread_home
```

Positive → Model favors HOME
Negative → Model favors AWAY

Directional truth.

---

### spread_pick

"HOME", "AWAY", or None.

---

# AGGREGATE

### parlay_edge_score

Composite magnitude metric.

Currently defined as:

```
spread_distance + total_distance
```

This is intentionally magnitude-based (risk-neutral confidence scoring).

It is NOT directional.

---

# context_flags

Dictionary for model-specific diagnostics.

Used for:

* Calibration
* Debugging
* Analyst explanations

Must always be a dictionary (empty allowed).

---

# 🚫 Prohibited

Models may NOT:

* Omit required fields
* Rename fields
* Flatten fields into game root
* Modify other model outputs
* Depend on downstream mapping
* Return partial schema

---

# 🔁 Execution Signature

All models must support:

```python
def run(self, game: dict, model_results: dict) -> dict
```

`model_results` must not be mutated.

---

# 🧪 Validation Rule

Enforced by `model_0051_runner.py`:

* Missing keys → hard failure
* Extra keys → hard failure
* context_flags not dict → hard failure

No silent drift allowed.

---

# 🏗 Versioning Policy

If schema changes:

* Create `MODEL_CONTRACT_V2.md`
* Do NOT modify V1
* Update runner explicitly

No silent edits.

---

# 🔒 Contract Freeze Confirmed

ModelContract_v1 is now:

* Signed edge explicit
* Distance explicit
* Deterministic
* Clean
* Agent-safe
* Arbitration-ready

---
