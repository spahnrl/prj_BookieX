# PHASE 3 — CLI INTERACTION CONTRACT

Version: v1
Status: LOCKED
Scope: Deterministic Presentation Layer

---

## Purpose

Define the minimal, deterministic interaction layer that operationalizes Phase 2 daily questions.

The CLI exists solely to present structured summaries derived from `DAILY_VIEW_V1`.

It does not compute, modify, recalculate, or expand model outputs.

Phase 3 introduces usability — not intelligence.

---

## Architectural Position

Pipeline Layers:

```
Compute → Freeze → Explain → Present
```

* Phase 1.5 froze Compute.
* Phase 2 defined Explain.
* Phase 3 defines Present.

The CLI operates strictly in the Present layer.

---

## Allowed Inputs

The CLI may read only:

```
data/daily/daily_view_YYYY-MM-DD_v1.json
```

No other artifacts are permitted.

Specifically, the CLI may NOT read:

* `data/view/*`
* `data/derived/*`
* `eng/backtest_*`
* `eng/outputs/*`
* `eng/ingest_*`
* `eng/*_calc_*`
* Any raw ingestion source
* Any API endpoint
* Any external data source

The CLI must not accept arbitrary user-supplied file paths.

All file resolution must be programmatically constrained to `data/daily/`.

---

## Supported Commands (Locked)

The CLI supports the following commands only:

* `action`
* `ignore`
* `why`
* `disagreement`
* `changes`

Each command maps directly to the Phase 2 Question Contract.

No additional commands may be introduced without a new contract version.

---

## Command Mapping to Phase 2

| CLI Command  | Phase 2 Question |
| ------------ | ---------------- |
| action       | ACTION           |
| ignore       | IGNORE           |
| why          | WHY              |
| disagreement | DISAGREEMENT     |
| changes      | WHAT CHANGED     |

The CLI does not redefine questions.
It presents them.

---

## Non-Negotiable Constraints

The CLI must:

* Read only DAILY_VIEW artifacts.
* Perform no model recomputation.
* Perform no edge recalculation.
* Perform no threshold evaluation.
* Perform no calibration recalculation.
* Write no files.
* Cache no state.
* Trigger no ingestion.
* Mutate no artifacts.

It is a pure read → filter → format layer.

---

## Determinism Rules

The CLI must:

* Produce stable, repeatable output for identical DAILY_VIEW input.
* Sort output deterministically:

  * Primary: edge magnitude (descending where applicable)
  * Secondary: `game_id`
* Round numeric display values explicitly (1 decimal).
* Avoid dynamic timestamps in output.
* Avoid random ordering.

Same input → identical output.

---

## Output Philosophy

CLI output must be:

* Clean
* Skimmable
* Structured
* Human-readable
* Free of raw JSON dumps

The CLI may not expose:

* Internal model artifacts
* Calibration internals
* Hash logic (except within `changes`)
* Upstream computation details

It presents final decisions only.

---

## Error Handling Rules

If no DAILY_VIEW file exists:

* Fail fast.
* Display clear error.
* Do not attempt fallback to other directories.

If DAILY_VIEW contains zero games:

* Display empty classification cleanly.
* Do not fabricate output.

If date specified does not exist:

* Fail clearly.
* Do not guess nearest date.

---

## Governance Boundary

Phase 3 does NOT:

* Expand Analyst read scope.
* Expand model authority.
* Introduce agentic behavior.
* Introduce dashboards.
* Introduce web frameworks.
* Introduce database layers.

Phase 3 remains a thin CLI layer only.

---

## Versioning

Any of the following require a new contract version:

* New commands
* Expanded read scope
* Additional artifact dependencies
* State persistence
* Output schema changes
* Interaction mode changes (interactive prompts, streaming, etc.)

---

## Freeze Declaration

PHASE 3 CLI CONTRACT v1 is locked.

The CLI:

* Reads DAILY_VIEW only.
* Presents deterministic summaries.
* Maintains strict architectural separation.
* Introduces no computational authority.

This preserves the integrity of the frozen deterministic core.

---

Status: LOCKED
End of Contract.
