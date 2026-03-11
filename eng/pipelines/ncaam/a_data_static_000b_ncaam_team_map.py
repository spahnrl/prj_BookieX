"""
a_data_static_000b_ncaam_team_map.py

Load static NCAAM team metadata (authoritative, stable, offline).
NO NETWORK. NO SSL. NO FAILURES.

Reads:
  data/static/ncaam_team_map.json

Writes:
  data/ncaam/raw/ncaam_team_map.json
  data/ncaam/raw/ncaam_team_map.csv
"""

import csv
import json
from pathlib import Path


STATIC_JSON = Path("data/ncaam/static/ncaam_team_map.json")
DEFAULT_OUTPUT_DIR = Path("data/ncaam/raw")


def validate_records(records: list[dict]) -> None:
    if not records:
        raise ValueError("Static NCAAM team map is empty")

    required_fields = [
        "team_id",
        "team_display",
    ]

    missing_rows = []
    seen_team_ids = set()
    duplicate_team_ids = set()

    for i, row in enumerate(records, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Row {i} is not a dict")

        for field in required_fields:
            if str(row.get(field, "")).strip() == "":
                missing_rows.append((i, field))

        team_id = str(row.get("team_id", "")).strip()
        if team_id:
            if team_id in seen_team_ids:
                duplicate_team_ids.add(team_id)
            seen_team_ids.add(team_id)

    if missing_rows:
        preview = ", ".join([f"row {i}:{field}" for i, field in missing_rows[:10]])
        raise ValueError(f"Missing required fields in static team map: {preview}")

    if duplicate_team_ids:
        dupes = ", ".join(sorted(duplicate_team_ids))
        raise ValueError(f"Duplicate team_id values found: {dupes}")


def build_fieldnames(records: list[dict]) -> list[str]:
    preferred_order = [
        "team_id",
        "team_display",
        "schedule_name",
        "market_name",
        "espn_name",
        "aliases",
    ]

    discovered = []
    seen = set()

    for field in preferred_order:
        for row in records:
            if field in row and field not in seen:
                discovered.append(field)
                seen.add(field)
                break

    for row in records:
        for field in row.keys():
            if field not in seen:
                discovered.append(field)
                seen.add(field)

    return discovered


def normalize_for_json(records: list[dict], fieldnames: list[str]) -> list[dict]:
    out = []

    for row in records:
        clean = {}
        for field in fieldnames:
            value = row.get(field, "")

            if value is None:
                clean[field] = ""
            elif isinstance(value, list):
                clean[field] = value
            else:
                clean[field] = str(value).strip()

        out.append(clean)

    return out


def normalize_for_csv(records: list[dict], fieldnames: list[str]) -> list[dict]:
    out = []

    for row in records:
        clean = {}
        for field in fieldnames:
            value = row.get(field, "")

            if value is None:
                clean[field] = ""
            elif isinstance(value, list):
                clean[field] = " | ".join(str(x).strip() for x in value if str(x).strip())
            else:
                clean[field] = str(value).strip()

        out.append(clean)

    return out


def run(output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> None:
    if not STATIC_JSON.exists():
        raise FileNotFoundError(f"Missing static team map: {STATIC_JSON}")

    with STATIC_JSON.open("r", encoding="utf-8") as f:
        records = json.load(f)

    if not isinstance(records, list):
        raise ValueError("Static NCAAM team map must be a list of dict rows")

    validate_records(records)
    fieldnames = build_fieldnames(records)

    json_ready = normalize_for_json(records, fieldnames)
    csv_ready = normalize_for_csv(records, fieldnames)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "ncaam_team_map.json"
    csv_path = out_dir / "ncaam_team_map.csv"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(json_ready, f, indent=2, ensure_ascii=False)

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_ready)

    print("NCAAM team map loaded from static reference data")
    print(f"Rows: {len(json_ready)}")
    print(f"JSON: {json_path}")
    print(f"CSV : {csv_path}")


if __name__ == "__main__":
    run()
