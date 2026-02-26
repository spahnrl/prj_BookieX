# prj_BookieX 🏀📊

**Deterministic NBA Data Pipeline for Fatigue & Betting Analysis**

---

## 📌 Project Overview

**prj_BookieX** is a deterministic, audit-safe NBA data engineering pipeline designed to support **sports betting analysis**, **fatigue modeling**, and **market comparison**.

The system ingests **free, reliable NBA data** (schedule, teams, boxscores), computes **rest and fatigue signals**, and prepares a clean foundation for **betting line integration** (paid or scraped sources).

**Key principles:**

* Forward-only data flow (no back-references)
* Reproducible outputs
* Clear separation of *facts* vs *market data*
* Observable, debuggable, long-running jobs

---

## 🎯 Core Use Case

Answer questions like:

* Is one team at a **fatigue disadvantage**?
* Are teams on **back-to-back** or **back-to-back-to-back** games?
* Did a game go to **overtime** (and how much)?
* How does **market pricing** (spread / O-U) compare to fatigue-adjusted expectations?

This project **does not place bets** — it generates **decision-ready data**.

---

## 🧱 Architecture Philosophy

* **No ML required to start**
* Signal quality > model complexity
* Every `.py`:

  * Reads exactly **one prior artifact**
  * Writes exactly **one new artifact**
* CSV + JSON always produced
* No silent failures

---

## 📂 Directory Structure

```
prj_BookieX/
│
├── a_data/                  # Raw & ingestion steps
│   ├── a_data_001_ingest_schedule.py
│   ├── a_data_002_team_map.py
│   ├── a_data_003_join_schedule_teams.py
│   ├── a_data_004_ingest_boxscores.py
│
├── calc/                    # Derived metrics & scoring
│   ├── calc_005_compute_team_rest_days.py
│   ├── calc_006_add_b2b_flags.py
│   ├── calc_007_compute_fatigue_score.py
│
├── data/
│   ├── raw/                 # Direct source outputs
│   └── derived/             # Chained outputs (truth source)
│
├── CHANGELOG.md
├── README.md
└── requirements.txt
```

---

## 🔄 Data Pipeline (Authoritative Order)

> **IMPORTANT:**
> Each step reads *only* the immediately previous output.

### 1️⃣ `a_data_001_ingest_schedule.py`

**Purpose:**
Fetch official NBA schedule.

**Outputs:**

* `nba_schedule.json`
* `nba_schedule.csv`

---

### 2️⃣ `a_data_002_team_map.py`

**Purpose:**
Normalize team metadata (IDs, names, conferences, divisions).

**Outputs:**

* `nba_team_map.json`
* `nba_team_map.csv`

---

### 3️⃣ `a_data_003_join_schedule_teams.py`

**Purpose:**
Join schedule + teams into game-level records.

**Outputs:**

* `nba_games_base.json`
* `nba_games_base.csv`

---

### 4️⃣ `a_data_004_ingest_boxscores.py`

**Purpose:**
Detect **overtime** using NBA boxscores.

**Adds (flags only):**

* `went_ot`
* `ot_minutes`
* `home_went_ot`
* `away_went_ot`

**Outputs:**

* `nba_games_with_ot.json`
* `nba_games_with_ot.csv`

> ⚠️ OT is **flagged**, never filtered.

---

### 5️⃣ `calc_005_compute_team_rest_days.py`

**Purpose:**
Compute rest days per team per game.

**Adds:**

* `home_rest_days`
* `away_rest_days`

---

### 6️⃣ `calc_006_add_b2b_flags.py`

**Purpose:**
Detect compressed schedules.

**Adds:**

* `home_back_to_back`
* `away_back_to_back`
* `home_back_to_back_to_back`
* `away_back_to_back_to_back`
* `any_back_to_back`
* `any_back_to_back_to_back`

---

### 7️⃣ `calc_007_compute_fatigue_score.py`

**Purpose:**
Create composite fatigue signals.

**Outputs:**

* `nba_games_with_fatigue.json`
* `nba_games_with_fatigue.csv`

> This is the **final free-data stopping point**.

---

## 📊 Fatigue Model (Current)

Fatigue is derived from:

* Days rest
* B2B / B2B2B flags
* OT minutes

The model is:

* Transparent
* Deterministic
* Easy to re-weight or replace later

---

## 💰 Betting Lines (Planned — Not Implemented)

Betting lines are **external market data**.

Planned ingestion:

* `a_data_008_ingest_betting_lines.py`
* Source: Joel’s paid feed or approved scrape
* Format: CSV or API
* Joined *after* fatigue computation

**Key rule:**

> Betting data is **never inferred**, only ingested.

---

## 🛠️ Reliability & Stability

* Uses NBA CDN endpoints (no API keys)
* Handles:

  * 403s
  * SSL mismatches
  * Partial failures
* Long-running jobs include progress logging
* Safe CSV fallbacks if files are locked

---

## ▶️ How to Run

Run scripts **in order**:

```bash
python a_data_001_ingest_schedule.py
python a_data_002_team_map.py
python a_data_003_join_schedule_teams.py
python a_data_004_ingest_boxscores.py
python calc_005_compute_team_rest_days.py
python calc_006_add_b2b_flags.py
python calc_007_compute_fatigue_score.py
```

---

## 🚦 Current Status

✅ Free data pipeline complete
✅ Fatigue metrics stable
✅ OT detection validated
🛑 Betting data intentionally deferred

---

## 🔮 Next Steps (When Ready)

* Add betting line ingestion
* Compare fatigue vs market pricing
* Track model vs closing line value (CLV)
* Add sport extensions (NCAA, NHL)

---

## 👥 Contributors

* **Rick Spahn** — Architecture, Data Engineering
* **Joel Petershagen** — Domain Model, Betting Strategy

---
