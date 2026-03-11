"""
tools/check_ncaam_inventory.py

NCAAM 2025 schedule inventory: raw vs canonical vs boxscores.

- Count Raw: data/ncaam/raw/ncaam_schedule_raw.json (unique game_id).
- Count Canonical: data/ncaam/canonical/ncaam_canonical_games.csv (rows).
- Check Range: Earliest and latest game_date in both files.
- Box Score Cross-Check: data/ncaam/boxscores/ unique JSON files; if missing,
  report data/ncaam/interim/ncaam_boxscores_raw.json entry count.

Usage:
  python tools/check_ncaam_inventory.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_SCHEDULE_PATH = PROJECT_ROOT / "data" / "ncaam" / "raw" / "ncaam_schedule_raw.json"
CANONICAL_PATH = PROJECT_ROOT / "data" / "ncaam" / "canonical" / "ncaam_canonical_games.csv"
BOXSCORES_DIR = PROJECT_ROOT / "data" / "ncaam" / "boxscores"
INTERIM_BOXSCORES_JSON = PROJECT_ROOT / "data" / "ncaam" / "interim" / "ncaam_boxscores_raw.json"


def _dates_from_rows(rows: list[dict], date_key: str = "game_date") -> tuple[str | None, str | None]:
    dates = []
    for r in rows:
        d = (r.get(date_key) or "").strip()
        if d:
            dates.append(d[:10])
    if not dates:
        return None, None
    return min(dates), max(dates)


def main() -> None:
    raw_count = 0
    raw_start: str | None = None
    raw_end: str | None = None

    if RAW_SCHEDULE_PATH.exists():
        try:
            with open(RAW_SCHEDULE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error reading raw schedule: {e}")
            data = []
        if isinstance(data, list):
            seen = set()
            for g in data:
                gid = str(g.get("game_id") or g.get("id") or "").strip()
                if gid:
                    seen.add(gid)
            raw_count = len(seen)
            raw_start, raw_end = _dates_from_rows(data)
    else:
        print(f"Raw schedule not found: {RAW_SCHEDULE_PATH}")

    canonical_count = 0
    canon_start: str | None = None
    canon_end: str | None = None

    if CANONICAL_PATH.exists():
        try:
            with open(CANONICAL_PATH, "r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            canonical_count = len(rows)
            canon_start, canon_end = _dates_from_rows(rows)
        except Exception as e:
            print(f"Error reading canonical: {e}")
    else:
        print(f"Canonical not found: {CANONICAL_PATH}")

    boxscore_json_count = 0
    boxscore_records = 0
    if BOXSCORES_DIR.exists():
        boxscore_json_count = len(list(BOXSCORES_DIR.glob("*.json")))
    if INTERIM_BOXSCORES_JSON.exists():
        try:
            with open(INTERIM_BOXSCORES_JSON, "r", encoding="utf-8") as f:
                arr = json.load(f)
            boxscore_records = len(arr) if isinstance(arr, list) else 0
        except Exception:
            pass

    start = raw_start or canon_start or "—"
    end = raw_end or canon_end or "—"

    start_display = start if start else "—"
    end_display = end if end else "—"

    print()
    print("  Raw Schedule:  ", raw_count, "games | Date Range:", raw_start or "—", "to", raw_end or "—")
    print("  Canonical:     ", canonical_count, "games | Date Range:", canon_start or "—", "to", canon_end or "—")
    if BOXSCORES_DIR.exists():
        print("  Boxscores:     ", boxscore_json_count, "unique JSON files (data/ncaam/boxscores/)")
    else:
        print("  Boxscores:     ", "0 JSON files (data/ncaam/boxscores/ not found) | Interim list:", boxscore_records, "records")
    print()
    print("  Summary: Raw Schedule:", raw_count, "games | Canonical:", canonical_count, "games | Date Range: [", start_display, "] to [", end_display, "]")
    print()


if __name__ == "__main__":
    main()
