# BOOKIEX V1 SUMMARY

Last Updated: 2026-02-19

---

# Overview

BookieX is a deterministic NBA analytics engine that:

1. Ingests historical game + odds data
2. Applies multiple projection models
3. Flattens model outputs
4. Applies confidence classification
5. Produces actionable betting signals
6. Enables deterministic backtesting

---

# Canonical Artifact

As of 2026-02-19:

Final authoritative artifact:

data/view/games_master.json

All downstream logic reads from this artifact only.

---

# Edge Derivation

Edges are computed upstream and flattened:

- Spread Edge
- Total Edge
- Parlay Edge Score

These are the contract-level decision drivers.

---

# Confidence Layer

Confidence classification operates on flattened fields only.

Confidence does NOT read nested model dictionaries.

Confidence outputs:

- confidence_tier
- cluster_alignment
- disagreement_flag
- confidence_reason

---

# Deterministic Guarantee

BookieX:
- Does not recalculate during backtest
- Does not allow agent overrides to alter base projections
- Does not modify canonical artifacts downstream

System is kitchen/dining room separated.