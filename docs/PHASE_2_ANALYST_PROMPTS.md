# PHASE_2_ANALYST_PROMPTS.md

## Version: V1

## Status: LOCKED

## Scope: DAILY_VIEW_V1 only

The Analyst Agent reads only `DAILY_VIEW_V1` and produces structured human-readable summaries.
It may not modify picks, thresholds, models, or calibration.

---

# Prompt 1 — Today’s ACTION Games

> From DAILY_VIEW_V1, list all games classified as ACTION.
> For each game, summarize:
>
> * Spread or Total pick
> * Edge size
> * Edge percentile
> * Historical bucket win rate
> * Confidence classification
> * One-sentence explanation of why this qualifies as ACTION
>
> Sort by largest edge first.

---

# Prompt 2 — Ignored Games

> From DAILY_VIEW_V1, list all games classified as IGNORE.
> For each game, explain:
>
> * Why the edge is insufficient
> * Whether percentile rank is weak
> * Whether confidence classification is low
>
> Do not criticize the model. Only describe observable thresholds.

---

# Prompt 3 — WHY Explanation (Deep Dive)

> For a selected game_id in DAILY_VIEW_V1, explain:
>
> * Projected margin vs market spread
> * Edge calculation (qualitative explanation only)
> * Context flags (rest, B2B, fatigue, 3PT differential)
> * Historical calibration bucket performance
>
> Produce a structured explanation suitable for a human decision-maker.

---

# Prompt 4 — Model vs Market Disagreement

> Identify games where the model pick direction conflicts strongly with market consensus direction.
> For each case:
>
> * State model pick
> * State consensus movement
> * Edge percentile
> * Confidence classification
>
> Summarize whether the disagreement is statistically meaningful or marginal.

---

# Prompt 5 — What Changed vs Last Run

> Compare today’s DAILY_VIEW_V1 with the previous DAILY_VIEW_V1 file.
> Report:
>
> * New ACTION games
> * Removed ACTION games
> * Edge size changes > 1.0
> * Confidence classification changes
>
> Do not recompute anything. Only compare values present in both files.

---

# 🔒 Constraints

* The Analyst may read:

  * `data/daily/daily_view_*.json`
* The Analyst may not read:

  * Raw model artifacts
  * Backtest outputs
  * Ingestion data
* The Analyst may not:

  * Modify thresholds
  * Recalculate edges
  * Re-score games

---
