# PHASE 4 — MULTI-MODEL FRAMEWORK CONTRACT

Last Updated: 2026-02-19

---

# 1. Purpose

Allow multiple independent models to evaluate the same game-level data.

Models:
- Joel_Baseline_v1
- FatiguePlus_v2
- InjuryModel_v1
- MonkeyDarts_v1
- MarketPressure_v1

---

# 2. Multi-Model Artifact

Artifact:
data/view/nba_games_multi_model_v1.json

Contains:
One record per game_id
Nested model dictionary under `models`

---

# 3. Duplicate Record Enforcement (2026-02-19)

A defect in model runner logic caused duplicate appends,
producing multiple rows per game_id.

This has been corrected.

Enforcement:
- Exactly one row per game_id
- Duplicate detection must fail fast
- Append operations must be idempotent

---

# 4. Flattening Rule

After multi-model evaluation:

Nested results are flattened into final_game_view.json

Then confidence layer produces:

data/view/games_master.json

Only games_master.json is authoritative downstream.

---

# 5. No Model Cross-Contamination

Models must:
- Read identical base data
- Produce independent projections
- Not modify other model outputs