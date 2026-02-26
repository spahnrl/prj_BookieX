# PHASE 2 QUESTION CONTRACT  
Version: v1  
Status: LOCKED  

---

## Phase 2 Objective

Define a stable, non-agentic question framework that BookieX must answer daily using final artifacts only.  

The system explains outputs.  
It does not modify picks, thresholds, data, or model behavior.  

Phase 2 defines **what questions matter**.  
It does not define UI or interaction mechanics.

---

## Locked Daily Questions (Non-Agentic)

BookieX must be able to answer the following 6 questions every day:

### 1. ACTION  
Which games require action today?

- List games classified as actionable.
- Include edge size, percentile, and confidence classification.

---

### 2. IGNORE  
Which games should be ignored?

- List games classified as INFO or NONE.
- Briefly state why they are not actionable (low edge, no signal, threshold not met).

---

### 3. WHY  
Why is each ACTION game considered actionable?

- Explain edge source (spread/total).
- Include key context flags (rest, fatigue, 3PT differential, etc.).
- Reference calibration bucket and historical win rate.

---

### 4. DISAGREEMENT  
Where does the model disagree with market or historical expectation?

- Highlight large edge percentiles.
- Identify bias flags or override flags if present.
- Note unusual calibration bucket behavior.

---

### 5. WHAT CHANGED  
What changed versus the last run?

- Edge magnitude shifts
- Confidence classification changes
- Market movement (spread/total changes)
- Model regime flag changes

---

### 6. RISK SUMMARY  
What is the overall daily exposure profile?

- Count of ACTION games
- Edge distribution across buckets
- Concentration risk (same team, same edge type, same bias cluster)

---

## Non-Agentic Constraint

The Analyst Agent:

- Reads final artifacts only.
- Does not alter picks.
- Does not alter thresholds.
- Does not recompute model outputs.
- Does not change calibration logic.
- Does not write to data directories.

It explains results only.

---

## Scope Boundary

Phase 2 covers:

- Question definition
- Daily View schema
- Analyst read-only role
- Analyst prompt design

Phase 3 will cover:

- Interaction layer
- Output formatting
- Usability gate

---

END OF PHASE 2 CONTRACT (v1)