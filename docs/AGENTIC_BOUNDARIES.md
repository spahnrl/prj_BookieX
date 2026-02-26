# Agentic Boundaries – BookieX

## 1. Agent Mission

Agents may propose bet combinations, narratives, execution timing,
or explicit override recommendations, but may not modify or replace
deterministic model outputs.

---

## 2. Inputs Agents May Read

Agents are permitted to read the following inputs only:

- Final game-level dataset
- actionability
- confidence_reason
- Decision Factors
- Evaluation summary

Agents may not access raw ingestion layers or intermediate feature pipelines
unless explicitly approved.

---

## 3. Outputs Agents May Produce

Agents may produce the following outputs:

- Ranked bet slips
- Natural-language summaries
- Alerts or notifications
- Execution suggestions
- Override recommendations (explicit, explained, and non-destructive)

Override recommendations must:
- Be clearly labeled as agent-generated
- Preserve the original model pick
- Include a clear justification for the override

---

## 4. Prohibited Actions

The following actions are explicitly forbidden:

- Modifying or overwriting deterministic model picks
- Changing edge calculations
- Changing confidence thresholds
- Dropping or filtering games
- Silent substitution of agent judgment for model output

---

## 5. Hard Prohibitions

Agents may not write back to the canonical dataset.

All agent outputs must be additive and external to the deterministic pipeline.

---

## 6. Termination Conditions

Agent execution must terminate under any of the following conditions:

- A maximum number of recommendations has been reached
- No games are labeled as ACTION
- Evaluation metrics fail predefined sanity bounds
- Required inputs are missing or incomplete

## 7. Agent Override Schema (Additive Only)

Agent overrides are additive annotations and must never modify model outputs.

### Fields
- agent_override_pick: string | null
  - Allowed values: HOME | AWAY | OVER | UNDER
- agent_override_reason: string | null
  - Short, human-readable justification
- agent_override_confidence_delta: number | null
  - Signed value indicating strength vs model edge (informational only)

### Rules
- Model picks remain authoritative and immutable
- Overrides must be explicitly labeled as agent-generated
- Overrides are permitted only when model edges are within tight bounds
- Overrides may not change edges, thresholds, or actionability labels