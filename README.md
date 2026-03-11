# prj_BookieX 🏀📊

## Deterministic NBA Betting Analytics Engine  
Multi-Model Arbitration • Backtesting • Confidence Gating • Dashboard

---

## 🎯 What This Is

**BookieX** is a deterministic, audit-safe NBA analytics engine designed to:

- Generate structured betting projections
- Compare projections vs market lines
- Arbitrate across multiple models
- Apply confidence gating
- Backtest performance
- Produce explainable outputs

This system is built like production software — not a notebook experiment.

It is:

- Deterministic
- Reproducible
- Modular
- Fully artifact-driven
- Forward-only pipeline architecture

---

## 🧠 System Capabilities

### ✅ Multi-Model Architecture

Current models:

- Joel Baseline Model
- Fatigue Plus Model
- Injury Model
- Market Pressure Model
- Monkey Darts (control baseline)

Each model produces:

- Spread projection
- Total projection
- Edge magnitude
- Pick direction

---

### ✅ Arbitration Layer

All models feed into:
eng/arbitration/confidence_engine.py
eng/arbitration/confidence_gate.py


Responsibilities:

- Cross-model agreement detection
- Edge strength scoring
- Confidence tier assignment
- Final authority pick selection

Confidence tiers:

- HIGH
- MODERATE
- LOW

---

### ✅ Determinism Guarantee

BookieX includes:
TRUTH/build_baseline_manifest.py
TRUTH/verify_determinism.py

These verify:

- Artifact integrity
- No silent schema drift
- No hidden mutation
- Reproducible outputs

This prevents pipeline corruption during refactors.

---

### ✅ Backtesting Engine

Located in:
eng/backtest_runner.py
eng/backtest_grader.py
eng/backtest_summary.py


Capabilities:

- Projection vs Vegas comparison
- Spread sign validation
- Edge magnitude performance curve
- Confidence tier performance testing
- Model disagreement analysis

---

### ✅ Calibration Snapshot
eng/calibration/build_calibration_snapshot.py

Creates a historical reference snapshot to:

- Track projection drift
- Compare model stability
- Evaluate structural bias

---

### ✅ Dashboard UI

Streamlit interface:
eng/ui/bookiex_dashboard.py


Features:

- Game-level rollup view
- Collapsible model detail sections
- Confidence tier display
- Signal strength bars
- Explanation section
- Clear separation of authority vs model-level signals

---

### ✅ CLI Interface

Allows:

- Pipeline execution
- Daily view generation
- Structured artifact control

---

## 🧱 Architecture Overview

BookieX is built as a forward-only artifact pipeline:
Raw Data
↓
Canonical Game Builder
↓
Game-Level Collapse
↓
Betting Line Integration
↓
Model Layer
↓
Arbitration Layer
↓
Confidence Gate
↓
Final Game View
↓
Backtest / Dashboard / CLI

Each step:

- Reads one prior artifact
- Writes one new artifact
- Never mutates historical artifacts

---

## 🏗 System Architecture Diagram

```mermaid
flowchart TD

A[Raw NBA Data<br>Schedule / Boxscores / Injuries] --> B[Canonical Game Builder]
B --> C[Game-Level Collapse]
C --> D[Betting Line Integration]

D --> E[Model Layer]

subgraph Models
E1[Joel Baseline]
E2[Fatigue Plus]
E3[Injury Model]
E4[Market Pressure]
E5[Monkey Darts]
end

E --> E1
E --> E2
E --> E3
E --> E4
E --> E5

E1 --> F[Arbitration Engine]
E2 --> F
E3 --> F
E4 --> F
E5 --> F

F --> G[Confidence Gate]
G --> H[Final Game View]

H --> I[Backtest Engine]
H --> J[Dashboard UI]
H --> K[CLI Interface]

I --> L[Calibration Snapshot]



## 📂 Core Structure
eng/
├── models/
├── arbitration/
├── analysis/
├── calibration/
├── daily/
├── ui/
├── cli/
├── backtest_runner.py
├── backtest_grader.py
└── decision_explainer.py

TRUTH/
data/static/
docs/


---

## 🔬 Engineering Standards

BookieX enforces:

- No circular dependencies
- No hidden joins
- Schema stability
- Explicit contracts (see docs/)
- Artifact flow documentation
- Confidence gating separated from modeling

---

## 🚀 How To Run

### Full Pipeline

```bash
python 000_RUN_ALL_NBA.py

Launch Dashboard
streamlit run eng/ui/bookiex_dashboard.py


📊 Example Use Cases

Detect model agreement zones

Identify high-confidence spread edges

Evaluate projection sign correctness

Compare edge magnitude vs profit curve

Analyze disagreement volatility

Test projection direction integrity

🧩 Design Philosophy

BookieX was intentionally built:

Without hidden ML black boxes

Without notebook coupling

Without fragile joins

Without refactor drift

It is structured as if it were preparing for:

Commercial deployment

Multi-sport extension

Agent-based orchestration

Capital allocation logic

👥 Contributors

Rick Spahn — Architecture & Data Engineering
Joel Petershagen — Domain Strategy & Market Insight

📌 Status

Version: Pre-Release v1.0
Architecture: Stable
Backtesting: Operational
Dashboard: Operational
Confidence Gating: Active
Determinism: Verified

⚠️ Disclaimer

This system generates analytical signals.
It does not place bets and does not constitute financial advice.



