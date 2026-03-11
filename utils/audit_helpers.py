"""
utils/audit_helpers.py

Verification log for the pipeline: compare JSON vs CSV row counts.

Uses only standard library (json, csv, pathlib, logging). No new dependencies.
"""

import csv
import json
import logging
from pathlib import Path
from typing import Any


def _count_json_objects(data: Any) -> int:
    """Count objects: length of a list, or length of 'games' array if dict."""
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict) and "games" in data:
        games = data["games"]
        return len(games) if isinstance(games, list) else 0
    return 0


def audit_file_consistency(
    json_path: Path | str,
    csv_path: Path | str,
    label: str,
) -> dict[str, Any]:
    """
    Compare number of objects in a JSON file with number of data rows in a CSV.

    - JSON: if the root is a list, counts its length; if a dict with a "games"
      key, counts len(games). Otherwise 0.
    - CSV: counts data rows (excluding header).

    If counts differ, logs a CRITICAL warning. Returns a result dict for
    callers to record or assert on.

    Raises FileNotFoundError if either path is missing.

    Returns:
        {
            "label": label,
            "json_count": int,
            "csv_count": int,
            "match_status": "match" | "mismatch",
        }
    """
    json_path = Path(json_path)
    csv_path = Path(csv_path)
    if not json_path.exists():
        raise FileNotFoundError(f"JSON file not found: {json_path}")
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        json_data = json.load(f)
    json_count = _count_json_objects(json_data)

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        csv_count = sum(1 for _ in reader)

    match_status = "match" if json_count == csv_count else "mismatch"
    if match_status == "mismatch":
        logging.critical(
            "CRITICAL: Data Mismatch [%s] JSON count=%s CSV count=%s (paths: %s, %s)",
            label,
            json_count,
            csv_count,
            json_path,
            csv_path,
        )

    return {
        "label": label,
        "json_count": json_count,
        "csv_count": csv_count,
        "match_status": match_status,
    }


def audit_csv_consistency(
    csv_primary_path: Path | str,
    csv_derived_path: Path | str,
    label: str,
    expected_derived_per_primary: float = 1.0,
) -> dict[str, Any]:
    """
    Compare row counts of two CSVs with an expected ratio.

    Expects: derived_count == primary_count * expected_derived_per_primary
    (i.e. expected_derived = primary_count * ratio). E.g. 0.5 when collapsing
    2 rows per game -> 1 row per game; 1.0 when 1:1.
    If not, logs CRITICAL and returns match_status "mismatch".

    Raises FileNotFoundError if either path is missing.

    Returns:
        {
            "label": label,
            "primary_count": int,
            "derived_count": int,
            "match_status": "match" | "mismatch",
        }
    """
    csv_primary_path = Path(csv_primary_path)
    csv_derived_path = Path(csv_derived_path)
    if not csv_primary_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_primary_path}")
    if not csv_derived_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_derived_path}")

    def count_rows(path: Path) -> int:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            next(reader, None)
            return sum(1 for _ in reader)

    primary_count = count_rows(csv_primary_path)
    derived_count = count_rows(csv_derived_path)
    expected_derived = primary_count * expected_derived_per_primary
    match_status = "match" if derived_count == expected_derived else "mismatch"
    if match_status == "mismatch":
        logging.critical(
            "CRITICAL: Data Mismatch [%s] primary count=%s derived count=%s (expected derived=%.0f) (paths: %s, %s)",
            label,
            primary_count,
            derived_count,
            expected_derived,
            csv_primary_path,
            csv_derived_path,
        )

    return {
        "label": label,
        "primary_count": primary_count,
        "derived_count": derived_count,
        "match_status": match_status,
    }
