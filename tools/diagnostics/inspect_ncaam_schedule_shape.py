# tools/inspect_ncaam_schedule_shape.py

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = PROJECT_ROOT / "data" / "ncaam" / "raw" / "ncaam_schedule_raw.json"


DATE_PATTERNS = [
    ("%Y-%m-%d", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("%Y-%m-%dT%H:%M:%S", re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")),
    ("%Y-%m-%dT%H:%M:%SZ", re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")),
    ("%Y-%m-%d %H:%M:%S", re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")),
    ("%m/%d/%Y", re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")),
    ("%m/%d/%Y %H:%M:%S", re.compile(r"^\d{1,2}/\d{1,2}/\d{4} \d{2}:\d{2}:\d{2}$")),
]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def infer_shape(obj: Any, max_list_examples: int = 3) -> Any:
    """
    Returns a compact structural summary of nested JSON.
    """
    if isinstance(obj, dict):
        return {
            k: infer_shape(v, max_list_examples=max_list_examples)
            for k, v in obj.items()
        }

    if isinstance(obj, list):
        if not obj:
            return ["<empty>"]

        sample_items = obj[:max_list_examples]
        sample_shapes = [infer_shape(x, max_list_examples=max_list_examples) for x in sample_items]

        # If list of dicts, merge keys for a cleaner schema view
        if all(isinstance(x, dict) for x in sample_items):
            merged: Dict[str, Set[str]] = {}
            for item in sample_items:
                for k, v in item.items():
                    merged.setdefault(k, set()).add(type_name(v))

            return [{
                k: sorted(list(v_types)) if len(v_types) > 1 else next(iter(v_types))
                for k, v_types in merged.items()
            }]

        # Otherwise just return sample type shapes
        return sample_shapes

    return type_name(obj)


def try_parse_date(value: str) -> Optional[datetime]:
    text = value.strip()
    if not text:
        return None

    for fmt, pattern in DATE_PATTERNS:
        if pattern.match(text):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                pass

    # last attempt: Python ISO parser with Z fix
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def walk_for_dates(obj: Any, path: str = "") -> Dict[str, List[datetime]]:
    found: Dict[str, List[datetime]] = {}

    if isinstance(obj, dict):
        for k, v in obj.items():
            child_path = f"{path}.{k}" if path else k
            child_found = walk_for_dates(v, child_path)
            for fk, vals in child_found.items():
                found.setdefault(fk, []).extend(vals)

    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            child_path = f"{path}[]"
            child_found = walk_for_dates(item, child_path)
            for fk, vals in child_found.items():
                found.setdefault(fk, []).extend(vals)

    elif isinstance(obj, str):
        dt = try_parse_date(obj)
        if dt is not None:
            found.setdefault(path, []).append(dt)

    return found


def print_shape_summary(data: Any) -> None:
    print("=" * 80)
    print("JSON SHAPE SUMMARY")
    print("=" * 80)

    shape = infer_shape(data)
    print(json.dumps(shape, indent=2, default=str))


def print_date_summary(date_map: Dict[str, List[datetime]]) -> None:
    print()
    print("=" * 80)
    print("DATE FIELD SUMMARY")
    print("=" * 80)

    if not date_map:
        print("No date-like fields detected.")
        return

    for field_path in sorted(date_map.keys()):
        values = date_map[field_path]
        if not values:
            continue

        earliest = min(values)
        latest = max(values)

        print(f"Field: {field_path}")
        print(f"  Count:    {len(values)}")
        print(f"  Earliest: {earliest.isoformat()}")
        print(f"  Latest:   {latest.isoformat()}")
        print("-" * 80)


def main() -> None:
    if not JSON_PATH.exists():
        raise FileNotFoundError(f"JSON file not found: {JSON_PATH.resolve()}")

    data = load_json(JSON_PATH)

    print(f"Loaded: {JSON_PATH.resolve()}")
    print(f"Top-level type: {type_name(data)}")

    if isinstance(data, list):
        print(f"Top-level row count: {len(data)}")
    elif isinstance(data, dict):
        print(f"Top-level key count: {len(data)}")

    print_shape_summary(data)

    date_map = walk_for_dates(data)
    print_date_summary(date_map)


if __name__ == "__main__":
    main()