"""
e_ncaam_033_audit_market_names.py

Purpose
-------
Audit unique NCAA market team names from the flattened Odds API file.

Design guarantees:
- Reads flat latest CSV only
- No normalization or inference
- Produces deterministic audit outputs
- Helps prepare team mapping later

Inputs
------
data/ncaam/market/flat/ncaam_odds_flat_latest.csv

Outputs
-------
data/ncaam/market/audit/ncaam_market_team_names_latest.csv
data/ncaam/market/audit/ncaam_market_team_names_YYYYMMDD_HHMMSS.csv
"""

import csv
from collections import Counter
from pathlib import Path

from configs.leagues.league_ncaam import (
    ODDS_FLAT_LATEST_PATH,
    MARKET_AUDIT_DIR,
    ensure_ncaam_dirs,
)


LATEST_AUDIT_PATH = MARKET_AUDIT_DIR / "ncaam_market_team_names_latest.csv"


def timestamped_audit_path(ts_label: str) -> Path:
    return MARKET_AUDIT_DIR / f"ncaam_market_team_names_{ts_label}.csv"


# =====================================================
# READ INPUT
# =====================================================

def load_flat_rows() -> list[dict]:
    if not ODDS_FLAT_LATEST_PATH.exists():
        raise FileNotFoundError(f"Missing flat odds file: {ODDS_FLAT_LATEST_PATH}")

    with open(ODDS_FLAT_LATEST_PATH, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


# =====================================================
# BUILD AUDIT
# =====================================================

def build_team_name_audit(rows: list[dict]) -> tuple[list[dict], str]:
    home_counter = Counter()
    away_counter = Counter()
    captured_at_values = set()

    for row in rows:
        captured_at = (row.get("captured_at_utc") or "").strip()
        if captured_at:
            captured_at_values.add(captured_at)

        home_team = (row.get("home_team") or "").strip()
        away_team = (row.get("away_team") or "").strip()

        if home_team:
            home_counter[home_team] += 1
        if away_team:
            away_counter[away_team] += 1

    all_names = sorted(set(home_counter.keys()) | set(away_counter.keys()))

    audit_rows = []
    for name in all_names:
        audit_rows.append({
            "market_team_name": name,
            "home_times_seen": home_counter.get(name, 0),
            "away_times_seen": away_counter.get(name, 0),
            "times_seen_total": home_counter.get(name, 0) + away_counter.get(name, 0),
            "mapping_status": "",
            "mapped_team_id": "",
            "mapped_team_display": "",
            "notes": "",
        })

    if len(captured_at_values) == 1:
        ts_value = next(iter(captured_at_values))
    else:
        ts_value = ""

    return audit_rows, ts_value


# =====================================================
# WRITE OUTPUTS
# =====================================================

def write_csv(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "market_team_name",
        "home_times_seen",
        "away_times_seen",
        "times_seen_total",
        "mapping_status",
        "mapped_team_id",
        "mapped_team_display",
        "notes",
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        if rows:
            writer.writerows(rows)


# =====================================================
# MAIN
# =====================================================

def run() -> None:
    ensure_ncaam_dirs()

    rows = load_flat_rows()
    audit_rows, captured_at = build_team_name_audit(rows)

    if captured_at:
        ts_label = (
            str(captured_at)
            .replace("-", "")
            .replace(":", "")
            .replace("T", "_")
            .replace("+00:00", "")
            .replace("Z", "")
            .split(".")[0]
        )
    else:
        ts_label = "unknown_capture"

    stamped_path = timestamped_audit_path(ts_label)

    write_csv(audit_rows, LATEST_AUDIT_PATH)
    write_csv(audit_rows, stamped_path)

    print(f"Loaded flat odds:            {ODDS_FLAT_LATEST_PATH}")
    print(f"Latest audit CSV written:    {LATEST_AUDIT_PATH}")
    print(f"Stamped audit CSV written:   {stamped_path}")
    print(f"Unique market team names:    {len(audit_rows)}")


if __name__ == "__main__":
    run()