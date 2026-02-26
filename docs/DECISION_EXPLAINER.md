The Decision Explainer Layer provides a deterministic, human-readable explanation
for every betting decision produced by the BookieX pipeline.

**Inputs**
- Canonical game-level dataset
- Market lines (spread, total)
- Baseline model projections
- Derived edge metrics

**Outputs**
- `decision_explanation` (string or structured text)
- `decision_factors` (table or dict)

**Game:** {Away} @ {Home}  
**Market:** Spread {line}, Total {ou}

**Model Projection**
- Projected Margin: {value}
- Projected Total: {value}

**Edges**
- Spread Edge: {value}
- Total Edge: {value}

**Decision**
- Spread: {Home/Away/None}
- Total: {Over/Under/None}

**Why**
- {Factor 1}
- {Factor 2}
- {Factor 3}

**Rules**
- No new logic is introduced in this layer
- No thresholds are invented here
- No filtering or ranking occurs here
- This layer explains decisions; it does not make them