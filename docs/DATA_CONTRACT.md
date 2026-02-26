### 1. Canonical Game Identity

- `game_id` is sourced directly from the NBA API.
- `game_id` is immutable and never regenerated or derived.
- `game_id` uniquely identifies exactly one NBA game.
- No two records may share the same `game_id`.
- `game_id` is the primary key for all game-level data.
- All joins, deduplication, and incremental ingestion are anchored on `game_id`.

### 2. Canonical Time Truth

- Authoritative game start time is defined by the NBA schedule data.
- The NBA-provided game date and local tip time represent the ground truth for when a game is intended to start.
- All canonical game time fields must ultimately be derived from NBA schedule data and normalized to UTC.

#### Current Implementation Exception (Temporary)

- Due to unresolved NBA local-time → UTC conversion issues, the current pipeline uses Odds API `commence_time` as a temporary proxy for UTC tip time.
- Odds time is used **only for time normalization**, not as a source of truth.
- Odds timestamps are volatile and reflect market snapshots; therefore:
  - Odds time must never be used as a join key.
  - Odds time must never define game identity.
  - Odds time must never be treated as canonical long-term truth.

#### Forward Requirement

- NBA schedule time normalization must be corrected.
- Once NBA time is reliably converted to UTC, it will replace Odds time as the canonical game start time source.

### 3. One-Record-Per-Game Rule

- The canonical dataset must contain exactly one row per game.
- Each row represents a single game identified by a unique `game_id`.
- Home and away teams are always flattened into the same record using explicit `home_*` and `away_*` fields.
- No team-level rows, duplicates, or exploded joins are permitted downstream of the canonical layer.
- Any process that produces more than one row per `game_id` is invalid and must fail fast.

### 4. Join Spine (Critical)

The following fields are the only permitted join keys for game-level data:

- `game_id` (primary and preferred join key)
- `canonical_game_day` (secondary, transitional; to be deprecated once NBA UTC normalization is complete)

#### Forbidden Join Patterns

The following join patterns are explicitly forbidden at all stages downstream of the canonical layer:

- Joining on team names or team abbreviations
- Joining on non-canonical or display dates
- Fuzzy or ±N-day date matching
- Implicit joins based on row order, index position, or file ordering

Any pipeline step that relies on a forbidden join pattern is invalid and must fail fast.

### 4.1 Team Identity Contract

- `team_id` is sourced from the NBA API and is immutable.
- `team_id` uniquely identifies an NBA franchise across all seasons.
- `team_id` is the authoritative identifier for teams.
- Team names, abbreviations, city names, and nicknames are display fields only.
- All team-level joins must use `team_id`, never team name or abbreviation.
- The team map (`nba_team_map.json`) is the single source of truth for resolving team metadata.

### 4.2 Player Identity Contract

- `player_id` is sourced from the NBA API and is immutable.
- `player_id` uniquely identifies an individual player.
- Player names are non-authoritative display fields and may change.
- Player-level data is always scoped to a `game_id`.
- Player-level datasets may contain multiple rows per `game_id`.
- Player-level data must never be joined directly to game-level canonical datasets without aggregation.


### 5. Deterministic vs Non-Deterministic Zones

| Layer            | Deterministic | Notes |
|------------------|---------------|-------|
| Ingestion        | ✅            | Raw source truth only; no inference or transformation beyond normalization |
| Fatigue          | ✅            | Pure mathematical transformations |
| Baseline Model   | ✅            | Deterministic Joel formulas only |
| Thresholds       | ⚠️            | Config-driven; must be explicit and versioned |
| Agent Reasoning  | ❌            | Not permitted in the current pipeline phase |

#### Enforcement Rule

- No non-deterministic logic is permitted in deterministic layers.
- Any introduction of agent-based reasoning must occur in a separate, explicitly approved pipeline phase.

### 6. Stop Conditions

- If any rule in this data contract is violated, the pipeline must fail fast.
- Silent recovery, implicit correction, or best-effort continuation is not permitted.
- Contract violations must surface as explicit errors before downstream processing continues.


See `DATA_SOURCES.md` for non-canonical file locations and source references.

## 7. Final Game-Level Schema Freeze (Agent Boundary Contract)

This section defines the frozen contract between the deterministic modeling core and any future Agent layer.

The authoritative artifact covered by this freeze is:

`data/view/nba_games_game_level_with_odds_model.json`

No refactors, renames, or semantic redefinitions are allowed without versioning.

---

### 7.1 Required Fields (Must Exist, Never Null)

These fields represent structural identity and core model truth.

- `game_id`
- `season_year`
- `home_team_id`
- `away_team_id`
- `home_points`
- `away_points`
- `spread_home_last`
- `total_last`
- `model_projected_margin`
- `model_projected_total`
- `spread_edge`
- `total_edge`
- `actionability`
- `confidence_reason`

**Rules:**

- Field must exist in every row.
- Field must never be null.
- Field must be deterministically reproducible in LAB mode.
- If any required field is missing or null → fail fast.

---

### 7.2 Optional Fields (May Be Null, Must Exist)

These fields are allowed to be null due to market availability or external conditions but must remain structurally present.

- `odds_snapshot_last_utc`
- `spread_consensus_all_time`
- `moneyline_consensus_all_time`
- Any odds-related field when market data is unavailable

Optional fields:
- Must retain consistent naming.
- Must not change semantic meaning.
- May only be extended additively.

---

### 7.3 Agent Prohibited Dependencies

Agents must treat the frozen artifact as read-only and must NOT rely on:

- Any ingestion timestamps
- Any raw API payload fragments
- Any intermediate processing artifacts
- Any non-canonical JSON files
- Any player-level or team-level files
- Any mutable backtest directory outputs
- Any LIVE-mode-only fields

Agents may only consume the final frozen game-level artifact.

---

### 7.4 Change Policy

- No required field may become nullable.
- No field may be renamed.
- No field may change meaning.
- New fields must be additive only.
- Breaking changes require versioned contract update.

This freeze establishes the stable boundary required for Agent Phase compatibility.

# DATA CONTRACT — BOOKIEX

Last Updated: 2026-02-19

This document defines the canonical data contracts for BookieX.
All downstream systems (confidence, backtest, CLI, agents) rely on these contracts.

---

# 1. Core Principle

BookieX operates on a deterministic, flattened game-level artifact.

Authoritative Artifact:
data/view/games_master.json

There must be exactly:
- One record per game_id
- No duplicates
- No nested model dependency for final decisions

---

# 2. Artifact Evolution

Historical (Deprecated):
- nba_games_game_level_with_odds_model.json
- final_game_view.json

Canonical (Current):
- games_master.json

All systems must read from games_master.json only.

---

# 3. Row-Level Uniqueness

Each record must represent:

1 game_id
1 game_date
1 home_team
1 away_team

Enforcement Rule:
Duplicate game_id rows must cause failure upstream.

---

# 4. Authoritative Flattened Fields

The following fields are considered contract surface and authoritative:

Core Projections:
- Projected Home Score
- Projected Away score
- Total Projection

Edges:
- Spread Edge
- Total Edge
- Parlay Edge Score

Bet Signals:
- Line Bet
- Total Bet

Confidence Layer:
- confidence_tier
- confidence_reason
- cluster_alignment
- disagreement_flag

Market:
- spread_home
- spread_away
- total
- moneyline_home
- moneyline_away

Context:
- fatigue_diff_home_minus_away
- home_rest_days
- away_rest_days
- home_fatigue_score
- away_fatigue_score

---

# 5. Nested Model Dictionary

Field:
models

Purpose:
Informational only.

Not authoritative.

Confidence logic, backtesting, and CLI must not read nested model dictionaries.

All decisions must use flattened fields.

---

# 6. Confidence Contract

Confidence classification operates strictly on:

- Spread Edge
- Total Edge
- Parlay Edge Score
- Cluster alignment logic

Confidence tiers:
- HIGH
- MODERATE
- LOW
- IGNORE

---

# 7. Artifact Rename (2026-02-19)

Old:
data/view/nba_games_game_level_with_odds_model.json

New:
data/view/games_master.json

Structure is flattened.
Nested models retained for traceability only.

---

# 8. Deterministic Enforcement

The following must hold:

- One row per game_id
- No duplicate appends
- All confidence fields computed once
- No runner-level recalculation of upstream metrics

This contract is frozen unless explicitly versioned.