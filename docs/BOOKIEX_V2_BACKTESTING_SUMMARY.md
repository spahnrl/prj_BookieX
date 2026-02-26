# BOOKIEX V2 — BACKTESTING SUMMARY

Last Updated: 2026-02-19

---

# Backtest Architecture

Backtest reads from:

data/view/games_master.json

No upstream recalculation allowed.

---

# Backtest Rules

- One record per game_id
- Uses flattened Spread Edge / Total Edge
- Uses confidence_tier
- Uses Line Bet / Total Bet
- Uses final actual scores

---

# Deterministic Boundary

Backtest:
- Must not recompute projections
- Must not read nested model dictionary
- Must not alter artifacts

---

# Enforcement

If games_master.json contains:
- Duplicate game_id
- Null critical fields
- Inconsistent structure

Backtest must fail fast.

---

# Output

Backtest produces:
- Win rate
- ROI
- Confidence tier breakdown
- Performance by alignment

All results derived strictly from canonical artifact.