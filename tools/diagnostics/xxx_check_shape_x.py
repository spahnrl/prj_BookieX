# prj_BookieX/tools/diagnostics/xxx_check_shape_x.py

import json
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Any
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# ============================================================
# CONFIG: defaults used when CLI args are not passed
# ============================================================

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]

JSON_SHAPE_LIST = [
    # Default compare pair if no CLI files are supplied
    "data/nba/view/final_game_view_nba.json",
    "data/ncaam/view/final_game_view_ncaam.json",
]

DEFAULT_SAMPLE_VALUES = 2

SHOW_REPORT_GUIDE = True
SHOW_SINGLE_FILE_REPORT = True
SHOW_COMPARE_REPORT = True
SHOW_FLAGS_ONLY_REPORT = True

CENTRAL_TZ = ZoneInfo("America/Chicago")

# If a file has a known nested path, add it here.
# Example:
#   "data/some_file.json": ["payload", "games"]
FORCED_RECORD_PATHS = {
    # "data/some_file.json": ["payload", "games"],
}

COMMON_RECORD_KEYS = [
    "games", "Games",
    "records", "Records",
    "items", "Items",
    "rows", "Rows",
    "data", "Data",
]

# Empty-ish string values treated as not meaningful
PLACEHOLDER_STRINGS = {
    "none",
    "null",
    "nan",
}

# Runtime-settable sample count
SAMPLE_VALUES = DEFAULT_SAMPLE_VALUES

# ============================================================
# HELPERS: CLI parsing
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Profile JSON record-based contracts and compare two JSON files "
            "for field-level parity, type drift, and meaningful-population gaps."
        )
    )

    parser.add_argument(
        "--files",
        nargs="+",
        help=(
            "One or more JSON files to profile. If two or more successfully load, "
            "the first two will be compared as LEFT and RIGHT."
        ),
    )

    parser.add_argument(
        "--left",
        help="Explicit LEFT JSON file for compare mode.",
    )

    parser.add_argument(
        "--right",
        help="Explicit RIGHT JSON file for compare mode.",
    )

    parser.add_argument(
        "--samples",
        type=int,
        default=DEFAULT_SAMPLE_VALUES,
        help="Number of example values to keep per field (default: 2).",
    )

    parser.add_argument(
        "--flags-only",
        action="store_true",
        help="Show only the flagged issues report plus compare context.",
    )

    parser.add_argument(
        "--no-guide",
        action="store_true",
        help="Suppress the report guide block.",
    )

    parser.add_argument(
        "--no-single",
        action="store_true",
        help="Suppress single-file contract profile reports.",
    )

    parser.add_argument(
        "--no-compare",
        action="store_true",
        help="Suppress parity compare report.",
    )

    return parser.parse_args()


def resolve_runtime_file_list(args: argparse.Namespace) -> list[str]:
    """
    Precedence:
    1. --left + --right => compare those two first
    2. --files => use provided files in listed order
    3. fallback to JSON_SHAPE_LIST defaults
    """
    if args.left and args.right:
        files = [args.left, args.right]
        if args.files:
            files.extend(args.files)
        return files

    if args.files:
        return args.files

    return JSON_SHAPE_LIST.copy()


# ============================================================
# HELPERS: file loading / path handling
# ============================================================

def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def ensure_json_path(path: Path) -> Path:
    if path.exists():
        return path
    if path.suffix.lower() != ".json":
        alt = path.with_suffix(".json")
        if alt.exists():
            return alt
    return path


def resolve_input_path(raw_path: str) -> Path:
    """
    Accept either:
    - repo-relative paths like data/nba/view/file.json
    - absolute paths
    """
    p = Path(raw_path)
    if p.is_absolute():
        return ensure_json_path(p)
    return ensure_json_path(PROJECT_ROOT / raw_path)


def get_nested_value(data: Any, path_parts: list[str]) -> Any:
    cur = data
    for part in path_parts:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(f"Missing nested path segment: {part}")
    return cur


def extract_records(data: Any):
    """
    Supports:
    - flat list
    - dict with games/Games/records/items/rows/data list
    """
    if isinstance(data, list):
        return data, "root[list]"

    if isinstance(data, dict):
        for key in COMMON_RECORD_KEYS:
            if key in data and isinstance(data[key], list):
                return data[key], f"root['{key}']"

    raise ValueError(
        "JSON must be either:\n"
        "- a list at root, or\n"
        "- a dict containing one of these list keys: "
        f"{COMMON_RECORD_KEYS}"
    )


def get_file_modified_central(path: Path) -> str:
    ts = path.stat().st_mtime
    dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
    dt_central = dt_utc.astimezone(CENTRAL_TZ)
    return dt_central.strftime("%Y-%m-%d %H:%M:%S %Z")


def pretty_source_file(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


# ============================================================
# HELPERS: value typing / classification
# ============================================================

def safe_jsonish(v: Any, max_len: int = 120) -> str:
    try:
        text = json.dumps(v, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = repr(v)

    if len(text) > max_len:
        return text[:max_len - 3] + "..."
    return text


def is_blank_string(v: Any) -> bool:
    return isinstance(v, str) and v.strip() == ""


def is_placeholder_string(v: Any) -> bool:
    return isinstance(v, str) and v.strip().lower() in PLACEHOLDER_STRINGS


def is_empty_list(v: Any) -> bool:
    return isinstance(v, list) and len(v) == 0


def is_empty_dict(v: Any) -> bool:
    return isinstance(v, dict) and len(v) == 0


def is_numeric_string(v: Any) -> bool:
    if not isinstance(v, str):
        return False

    s = v.strip()
    if s == "":
        return False

    try:
        float(s)
        return True
    except ValueError:
        return False


def infer_type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int) and not isinstance(v, bool):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        if is_numeric_string(v):
            return "numeric_str"
        return "str"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "dict"
    return type(v).__name__


def is_meaningful(v: Any) -> bool:
    """
    Conservative v1 rule:
    not meaningful if value is:
    - None
    - blank string
    - empty list
    - empty dict
    - placeholder string: NONE / null / nan
    """
    if v is None:
        return False
    if is_blank_string(v):
        return False
    if is_empty_list(v):
        return False
    if is_empty_dict(v):
        return False
    if is_placeholder_string(v):
        return False
    return True


def to_float_if_possible(v: Any):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if is_numeric_string(v):
        try:
            return float(str(v).strip())
        except ValueError:
            return None
    return None


# ============================================================
# HELPERS: stats formatting
# ============================================================

def append_example(bucket: list[str], value: Any, max_items: int = SAMPLE_VALUES):
    text = safe_jsonish(value)
    if text not in bucket and len(bucket) < max_items:
        bucket.append(text)


def pct(n: int, d: int) -> float:
    if d == 0:
        return 0.0
    return round((n / d) * 100, 1)


def detect_range_candidates(type_counts: dict[str, int]) -> bool:
    numeric_types = {"int", "float", "numeric_str"}
    return any(type_counts.get(t, 0) > 0 for t in numeric_types)


def summarize_type_counts(type_counts: dict[str, int]) -> str:
    parts = []
    for k, count in sorted(type_counts.items(), key=lambda x: (-x[1], x[0])):
        parts.append(f"{k}:{count}")
    return ", ".join(parts)


def dominant_type(type_counts: dict[str, int]) -> str:
    meaningful_counts = {k: v for k, v in type_counts.items() if k != "null"}
    if not meaningful_counts:
        return "null"
    return max(meaningful_counts.items(), key=lambda x: (x[1], x[0]))[0]


def build_empty_breakdown(stats: dict[str, Any]) -> str:
    parts = []
    if stats["null"] > 0:
        parts.append(f"null:{stats['null']}")
    if stats["blank_str"] > 0:
        parts.append(f"blank:{stats['blank_str']}")
    if stats["empty_list"] > 0:
        parts.append(f"[]:{stats['empty_list']}")
    if stats["empty_dict"] > 0:
        parts.append(f"{{}}:{stats['empty_dict']}")
    if stats["placeholder_str"] > 0:
        parts.append(f"placeholder:{stats['placeholder_str']}")
    return ", ".join(parts) if parts else "-"


# ============================================================
# HELPERS: duplicate-candidate heuristics
# ============================================================

def normalize_field_name_for_duplicate_check(field: str) -> str:
    """
    Normalize field names for loose duplicate-by-name detection.
    Conservative heuristic only.
    """
    s = field.strip().lower()

    replacements = {
        "projected home score": "projected_home_score",
        "projected away score": "projected_away_score",
        "home line projection": "home_line_projection",
        "total projection": "total_projection",
        "line bet": "line_bet",
        "line result": "line_result",
        "total bet": "total_bet",
        "spread edge": "spread_edge",
        "total edge": "total_edge",
        "parlay edge score": "parlay_edge_score",
        "decision factors": "decision_factors",
    }

    s = replacements.get(s, s)
    s = s.replace(" ", "_").replace("-", "_")

    removable_suffixes = [
        "_last",
        "_consensus",
        "_consensus_all_time",
        "_all_time",
        "_utc",
        "_cst",
    ]

    changed = True
    while changed:
        changed = False
        for suffix in removable_suffixes:
            if s.endswith(suffix):
                s = s[:-len(suffix)]
                changed = True

    return s


def tokenize_field_name(field: str) -> set[str]:
    normalized = normalize_field_name_for_duplicate_check(field)
    parts = [p for p in normalized.split("_") if p]
    return set(parts)


def possible_duplicate_by_name(field_a: str, field_b: str) -> bool:
    """
    Heuristic:
    - exact normalized match, or
    - same token set, or
    - strong token overlap for small field names
    """
    norm_a = normalize_field_name_for_duplicate_check(field_a)
    norm_b = normalize_field_name_for_duplicate_check(field_b)

    if norm_a == norm_b:
        return True

    tokens_a = tokenize_field_name(field_a)
    tokens_b = tokenize_field_name(field_b)

    if not tokens_a or not tokens_b:
        return False

    if tokens_a == tokens_b:
        return True

    overlap = tokens_a & tokens_b
    union = tokens_a | tokens_b

    if union and (len(overlap) / len(union)) >= 0.75:
        return True

    return False


def values_compatible_for_content_compare(a: Any, b: Any) -> bool:
    """
    Loose compatibility gate before equality testing.
    """
    if not is_meaningful(a) or not is_meaningful(b):
        return False

    a_num = to_float_if_possible(a)
    b_num = to_float_if_possible(b)

    if a_num is not None and b_num is not None:
        return True

    if isinstance(a, str) and isinstance(b, str):
        return True

    if isinstance(a, bool) and isinstance(b, bool):
        return True

    return type(a) == type(b)


def values_equal_loose(a: Any, b: Any) -> bool:
    """
    Loose equality for duplicate-by-content detection.
    """
    a_num = to_float_if_possible(a)
    b_num = to_float_if_possible(b)

    if a_num is not None and b_num is not None:
        return a_num == b_num

    return a == b


def compare_field_content_similarity(records: list[Any], field_a: str, field_b: str) -> dict[str, Any]:
    """
    Compare two fields within the SAME file/record set.
    Returns overlap stats for possible duplicate-by-content detection.
    """
    both_meaningful = 0
    equal_count = 0

    for row in records:
        if not isinstance(row, dict):
            continue

        a = row.get(field_a)
        b = row.get(field_b)

        if not values_compatible_for_content_compare(a, b):
            continue

        both_meaningful += 1
        if values_equal_loose(a, b):
            equal_count += 1

    equality_pct = pct(equal_count, both_meaningful) if both_meaningful else 0.0

    return {
        "both_meaningful": both_meaningful,
        "equal_count": equal_count,
        "equality_pct": equality_pct,
    }


def find_right_side_duplicate_candidates(
    left: dict[str, Any],
    right: dict[str, Any],
    compare_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Build possible duplicate candidates inside the RIGHT-side file only.
    This is heuristic and intended for investigation, not proof.

    Also carries forward whether the RIGHT field itself is ONLY_RIGHT,
    and whether any duplicate candidate by name/content is ONLY_RIGHT.
    """
    right_field_stats = right["field_stats"]
    right_fields = sorted(right_field_stats.keys())

    # Map compare rows by field so we can see ONLY_RIGHT state
    compare_map = {row["field"]: row for row in compare_rows}

    data = load_json(right["file_path"])
    pretty_path = right["relative_path"]

    if pretty_path in FORCED_RECORD_PATHS:
        nested = get_nested_value(data, FORCED_RECORD_PATHS[pretty_path])
        records, _ = extract_records(nested)
    else:
        records, _ = extract_records(data)

    rows = []

    for field in right_fields:
        stats = right_field_stats[field]
        r_type = dominant_type(stats["type_counts"])
        r_mean_pct = pct(stats["meaningful"], right["total_records"])

        compare_row = compare_map.get(field)
        field_is_r_only = "Y" if compare_row and "ONLY_RIGHT" in compare_row["flags"] else "N"

        by_name_matches = []
        by_content_matches = []

        by_name_r_only = "N"
        by_content_r_only = "N"

        for other in right_fields:
            if other == field:
                continue

            other_compare_row = compare_map.get(other)
            other_is_r_only = bool(other_compare_row and "ONLY_RIGHT" in other_compare_row["flags"])

            if possible_duplicate_by_name(field, other):
                by_name_matches.append(other)
                if other_is_r_only:
                    by_name_r_only = "Y"

            content_cmp = compare_field_content_similarity(records, field, other)
            if (
                content_cmp["both_meaningful"] >= 25
                and content_cmp["equality_pct"] >= 95.0
            ):
                by_content_matches.append(
                    f"{other} ({content_cmp['equality_pct']:.1f}%/{content_cmp['both_meaningful']})"
                )
                if other_is_r_only:
                    by_content_r_only = "Y"

        by_name_matches = sorted(set(by_name_matches))
        by_content_matches = sorted(set(by_content_matches))

        note_parts = []
        if by_name_matches and by_content_matches:
            note_parts.append("name+content candidate")
        elif by_name_matches:
            note_parts.append("name-only candidate")
        elif by_content_matches:
            note_parts.append("content-only candidate")
        else:
            note_parts.append("-")

        rows.append({
            "field": field,
            "r_only": field_is_r_only,
            "right_type": r_type,
            "right_mean_pct": r_mean_pct,
            "dup_by_name": by_name_matches,
            "r_only_x_name": by_name_r_only,
            "dup_by_content": by_content_matches,
            "r_only_x_content": by_content_r_only,
            "notes": "; ".join(note_parts),
        })

    return rows


# ============================================================
# ANALYSIS: per-file profile building
# ============================================================

def analyze_records(records: list[Any], extracted_from: str, source_label: str) -> dict[str, Any]:
    total = len(records)

    field_stats = defaultdict(lambda: {
        "present": 0,
        "null": 0,
        "blank_str": 0,
        "empty_list": 0,
        "empty_dict": 0,
        "placeholder_str": 0,
        "meaningful": 0,
        "type_counts": defaultdict(int),
        "examples_meaningful": [],
        "examples_empty": [],
        "numeric_min": None,
        "numeric_max": None,
    })

    non_dict_count = 0

    for r in records:
        if not isinstance(r, dict):
            non_dict_count += 1
            continue

        for k, v in r.items():
            stats = field_stats[k]
            stats["present"] += 1

            v_type = infer_type(v)
            stats["type_counts"][v_type] += 1

            if v is None:
                stats["null"] += 1
                append_example(stats["examples_empty"], v)
                continue

            if is_blank_string(v):
                stats["blank_str"] += 1
                append_example(stats["examples_empty"], v)
                continue

            if is_empty_list(v):
                stats["empty_list"] += 1
                append_example(stats["examples_empty"], v)
                continue

            if is_empty_dict(v):
                stats["empty_dict"] += 1
                append_example(stats["examples_empty"], v)
                continue

            if is_placeholder_string(v):
                stats["placeholder_str"] += 1
                append_example(stats["examples_empty"], v)
                continue

            stats["meaningful"] += 1
            append_example(stats["examples_meaningful"], v)

            num = to_float_if_possible(v)
            if num is not None:
                if stats["numeric_min"] is None or num < stats["numeric_min"]:
                    stats["numeric_min"] = num
                if stats["numeric_max"] is None or num > stats["numeric_max"]:
                    stats["numeric_max"] = num

    return {
        "source_label": source_label,
        "extracted_from": extracted_from,
        "total_records": total,
        "non_dict_count": non_dict_count,
        "field_stats": field_stats,
    }


def load_and_profile_file(input_path: str) -> dict[str, Any] | None:
    file_path = resolve_input_path(input_path)

    print("\n" + "=" * 120)
    print(f"TARGET JSON FILE: {file_path}")

    if not file_path.exists():
        print("❌ FILE NOT FOUND")
        return None

    pretty_path = pretty_source_file(file_path)

    try:
        data = load_json(file_path)

        if pretty_path in FORCED_RECORD_PATHS:
            nested = get_nested_value(data, FORCED_RECORD_PATHS[pretty_path])
            records, extracted_from = extract_records(nested)
            extracted_from = f"forced path {FORCED_RECORD_PATHS[pretty_path]} -> {extracted_from}"
        else:
            records, extracted_from = extract_records(data)

    except Exception as e:
        print(f"❌ ERROR LOADING FILE: {e}")
        return None

    if not records:
        print("⚠️ EMPTY RECORD LIST")
        return None

    label = Path(file_path).stem
    return {
        "relative_path": pretty_source_file(file_path),
        "file_path": file_path,
        "file_modified_central": get_file_modified_central(file_path),
        **analyze_records(records, extracted_from, label),
    }


# ============================================================
# REPORTING: guide / definitions for chat tools
# ============================================================

def print_report_guide():
    print("\n" + "=" * 120)
    print("CONTRACT / PARITY REPORT GUIDE")
    print("=" * 120)
    print(
        "Intent:\n"
        "- This report profiles JSON record-based contracts and compares two JSON files side by side.\n"
        "- It is designed to expose schema drift, type drift, fake-filled fields, and meaningful-population gaps.\n"
        "- It is a field-level contract report, not a row-by-row or game-by-game comparison report.\n"
    )
    print(
        "File selection:\n"
        "- Default mode: edit JSON_SHAPE_LIST near the top of this script.\n"
        "- CLI mode: pass files with --files, or pass an explicit pair with --left and --right.\n"
        "- The parity compare report uses the first two successfully loaded JSON files as LEFT and RIGHT.\n"
    )
    print(
        "Meaningful value rules (v1):\n"
        "- A value is NOT meaningful if it is:\n"
        "  * null / None\n"
        "  * blank string: \"\"\n"
        "  * empty list: []\n"
        "  * empty dict: {}\n"
        "  * placeholder string: NONE / null / nan\n"
        "- Otherwise the value is treated as meaningful.\n"
        "- Important: 'meaningful' in this report means structurally populated under these rules.\n"
        "- It does NOT guarantee business correctness, semantic usefulness, or model quality.\n"
    )
    print(
        "Single-file report columns:\n"
        "- FIELD: JSON field/key name.\n"
        "- PRESENT%: percent of records where the key exists.\n"
        "- MEAN%: percent of records where the value is meaningful.\n"
        "- EMPTY BREAKDOWN: why records are not meaningful (null, blank, [], {}, placeholder).\n"
        "- DOM_TYPE: dominant detected type (str, numeric_str, int, float, bool, dict, list, null).\n"
        "- RANGE: min..max for numeric or numeric-like values.\n"
        "- EXAMPLE_NON_EMPTY: representative meaningful values.\n"
        "- EXAMPLE_EMPTY: representative empty-like values.\n"
        "- types=...: raw detected type counts for the field.\n"
    )
    print(
        "Parity compare report columns:\n"
        "- L / R: whether the field exists in LEFT / RIGHT file.\n"
        "- L_MEAN% / R_MEAN%: meaningful-population percent on each side.\n"
        "- L_TYPE / R_TYPE: dominant type on each side.\n"
        "- DIFF%: absolute difference between L_MEAN% and R_MEAN%.\n"
        "- FLAGS: auto-detected contract/parity issues.\n"
    )
    print(
        "Flag meanings:\n"
        "- ONLY_LEFT: field exists only in LEFT file.\n"
        "- ONLY_RIGHT: field exists only in RIGHT file.\n"
        "- TYPE_MISMATCH: field exists in both files but dominant type differs.\n"
        "- LEFT_FAKE_FILLED: field is 100% present but 0% meaningful on LEFT.\n"
        "- RIGHT_FAKE_FILLED: field is 100% present but 0% meaningful on RIGHT.\n"
        "- MEANINGFUL_GAP_25+: meaningful-population gap is at least 25 percentage points.\n"
        "- PRESENT_GAP_25+: presence gap is at least 25 percentage points.\n"
    )
    print(
        "Interpretation guidance:\n"
        "- PRESENT% tells whether the key exists.\n"
        "- MEAN% tells whether the field is actually populated in a useful structural way.\n"
        "- A field can be 100% present and still be effectively empty.\n"
        "- Fields with no flags are better candidates for shared contract alignment.\n"
        "- Use ONLY_LEFT / ONLY_RIGHT to find missing fields.\n"
        "- Use TYPE_MISMATCH to find normalization targets.\n"
        "- Use FAKE_FILLED and MEANINGFUL_GAP flags to find misleading or weakly aligned fields.\n"
    )
    print(
        "Out of scope / not proven by this report:\n"
        "- This report does NOT validate row alignment or game-by-game equivalence.\n"
        "- It does NOT prove that differently named fields are the same business concept.\n"
        "- It does NOT validate correctness of values.\n"
        "- It does NOT deeply compare nested dict/list internals such as models or arbitration subfields.\n"
    )
    print("=" * 120 + "\n")


# ============================================================
# REPORTING: single-file contract report
# ============================================================

def print_single_file_report(profile: dict[str, Any]):
    total = profile["total_records"]
    field_stats = profile["field_stats"]

    print("\n=== CONTRACT PROFILE REPORT ===")
    print(f"Source label: {profile['source_label']}")
    print(f"Source file : {profile['relative_path']}")
    print(f"File type   : .json")
    print(f"Modified CT : {profile['file_modified_central']}")
    print(f"Extracted from: {profile['extracted_from']}")
    print(f"Total records: {total}")
    print(f"Non-dict records skipped: {profile['non_dict_count']}\n")

    header = (
        f"{'FIELD':34} "
        f"{'PRESENT%':>8} "
        f"{'MEAN%':>7} "
        f"{'EMPTY BREAKDOWN':28} "
        f"{'DOM_TYPE':12} "
        f"{'RANGE':20} "
        f"{'EXAMPLE_NON_EMPTY':28} "
        f"{'EXAMPLE_EMPTY'}"
    )
    print(header)
    print("-" * 180)

    for field in sorted(field_stats.keys()):
        stats = field_stats[field]
        present_pct = pct(stats["present"], total)
        meaningful_pct = pct(stats["meaningful"], total)
        empty_breakdown = build_empty_breakdown(stats)
        dom_type = dominant_type(stats["type_counts"])
        type_summary = summarize_type_counts(stats["type_counts"])

        if detect_range_candidates(stats["type_counts"]) and stats["numeric_min"] is not None:
            range_text = f"{stats['numeric_min']}..{stats['numeric_max']}"
        else:
            range_text = "-"

        ex_meaningful = " | ".join(stats["examples_meaningful"]) if stats["examples_meaningful"] else "-"
        ex_empty = " | ".join(stats["examples_empty"]) if stats["examples_empty"] else "-"

        print(
            f"{field:34} "
            f"{present_pct:7.1f}% "
            f"{meaningful_pct:6.1f}% "
            f"{empty_breakdown[:28]:28} "
            f"{dom_type[:12]:12} "
            f"{range_text[:20]:20} "
            f"{ex_meaningful[:28]:28} "
            f"{ex_empty}"
        )

        if len(type_summary) > 80:
            type_summary = type_summary[:77] + "..."
        print(f"{'':34} {'':8} {'':7} {'types=' + type_summary}")

    print("\n=== END SINGLE-FILE REPORT ===\n")


# ============================================================
# REPORTING: parity compare report
# ============================================================

def compare_profiles(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
    left_stats = left["field_stats"]
    right_stats = right["field_stats"]

    left_total = left["total_records"]
    right_total = right["total_records"]

    all_fields = sorted(set(left_stats.keys()) | set(right_stats.keys()))
    rows = []

    for field in all_fields:
        l = left_stats.get(field)
        r = right_stats.get(field)

        l_present = l["present"] if l else 0
        r_present = r["present"] if r else 0

        l_meaningful = l["meaningful"] if l else 0
        r_meaningful = r["meaningful"] if r else 0

        l_present_pct = pct(l_present, left_total)
        r_present_pct = pct(r_present, right_total)

        l_mean_pct = pct(l_meaningful, left_total)
        r_mean_pct = pct(r_meaningful, right_total)

        l_type = dominant_type(l["type_counts"]) if l else "-"
        r_type = dominant_type(r["type_counts"]) if r else "-"

        flags = []

        if l and not r:
            flags.append("ONLY_LEFT")
        elif r and not l:
            flags.append("ONLY_RIGHT")

        if l and r and l_type != r_type:
            flags.append("TYPE_MISMATCH")

        if l and l_present_pct == 100.0 and l_mean_pct == 0.0:
            flags.append("LEFT_FAKE_FILLED")
        if r and r_present_pct == 100.0 and r_mean_pct == 0.0:
            flags.append("RIGHT_FAKE_FILLED")

        if l and r and abs(l_mean_pct - r_mean_pct) >= 25.0:
            flags.append("MEANINGFUL_GAP_25+")

        if l and r and abs(l_present_pct - r_present_pct) >= 25.0:
            flags.append("PRESENT_GAP_25+")

        rows.append({
            "field": field,
            "left_in": "Y" if l else "N",
            "right_in": "Y" if r else "N",
            "left_mean_pct": l_mean_pct,
            "right_mean_pct": r_mean_pct,
            "left_type": l_type,
            "right_type": r_type,
            "mean_diff_pct": round(abs(l_mean_pct - r_mean_pct), 1),
            "flags": flags,
        })

    return rows


def print_compare_report(left: dict[str, Any], right: dict[str, Any], rows: list[dict[str, Any]]):
    print("\n=== PARITY COMPARE REPORT ===")
    print(
        f"LEFT : {left['source_label']} "
        f"({left['relative_path']}, .json, modified {left['file_modified_central']})"
    )
    print(
        f"RIGHT: {right['source_label']} "
        f"({right['relative_path']}, .json, modified {right['file_modified_central']})\n"
    )

    header = (
        f"{'FIELD':34} "
        f"{'L':>2} {'R':>2} "
        f"{'L_MEAN%':>8} {'R_MEAN%':>8} "
        f"{'L_TYPE':12} {'R_TYPE':12} "
        f"{'DIFF%':>7}  FLAGS"
    )
    print(header)
    print("-" * 140)

    for row in rows:
        flags_text = ",".join(row["flags"]) if row["flags"] else "-"
        print(
            f"{row['field']:34} "
            f"{row['left_in']:>2} {row['right_in']:>2} "
            f"{row['left_mean_pct']:7.1f}% {row['right_mean_pct']:7.1f}% "
            f"{row['left_type'][:12]:12} {row['right_type'][:12]:12} "
            f"{row['mean_diff_pct']:6.1f}%  {flags_text}"
        )

    print("\n=== END PARITY COMPARE REPORT ===\n")


# ============================================================
# REPORTING: flagged issues only
# ============================================================

def print_flags_only_report(left: dict[str, Any], right: dict[str, Any], rows: list[dict[str, Any]]):
    flagged = [r for r in rows if r["flags"]]

    print("\n=== FLAGGED ISSUES ONLY ===")
    print(
        f"LEFT : {left['source_label']} "
        f"({left['relative_path']}, .json, modified {left['file_modified_central']})"
    )
    print(
        f"RIGHT: {right['source_label']} "
        f"({right['relative_path']}, .json, modified {right['file_modified_central']})\n"
    )

    if not flagged:
        print("No flagged issues found.\n")
        return

    header = (
        f"{'FIELD':34} "
        f"{'L_MEAN%':>8} {'R_MEAN%':>8} "
        f"{'L_TYPE':12} {'R_TYPE':12}  FLAGS"
    )
    print(header)
    print("-" * 120)

    for row in flagged:
        print(
            f"{row['field']:34} "
            f"{row['left_mean_pct']:7.1f}% {row['right_mean_pct']:7.1f}% "
            f"{row['left_type'][:12]:12} {row['right_type'][:12]:12}  "
            f"{','.join(row['flags'])}"
        )

    print("\n=== END FLAGGED ISSUES ONLY ===\n")


# ============================================================
# REPORTING: right-side possible duplicates
# ============================================================

def print_right_side_duplicate_report(
    left: dict[str, Any],
    right: dict[str, Any],
    compare_rows: list[dict[str, Any]],
):
    rows = find_right_side_duplicate_candidates(left, right, compare_rows)

    print("\n=== RIGHT-SIDE POSSIBLE DUPLICATE CANDIDATES ===")
    print(
        f"RIGHT: {right['source_label']} "
        f"({right['relative_path']}, .json, modified {right['file_modified_central']})\n"
    )

    header = (
        f"{'RIGHT_FIELD':22} "
        f"{'R_ONLY':6} "
        f"{'R_TYPE':12} "
        f"{'R_MEAN%':>8} "
        f"{'POSSIBLE_DUP_BY_NAME':28} "
        f"{'R_ONLYxN':8} "
        f"{'POSSIBLE_DUP_BY_CONTENT':32} "
        f"{'R_ONLYxC':8}"
    )
    print(header)
    print("-" * 150)

    for row in rows:
        dup_name = ", ".join(row["dup_by_name"]) if row["dup_by_name"] else "-"
        dup_content = ", ".join(row["dup_by_content"]) if row["dup_by_content"] else "-"

        print(
            f"{row['field'][:22]:22} "
            f"{row['r_only']:6} "
            f"{row['right_type'][:12]:12} "
            f"{row['right_mean_pct']:7.1f}% "
            f"{dup_name[:28]:28} "
            f"{row['r_only_x_name']:8} "
            f"{dup_content[:32]:32} "
            f"{row['r_only_x_content']:8}"
        )

        if row["notes"] != "-":
            print(f"{'':22} {'':6} {'':12} {'':8} NOTES: {row['notes']}")

    print("\n=== END RIGHT-SIDE POSSIBLE DUPLICATE CANDIDATES ===\n")


# ============================================================
# MAIN RUN
# ============================================================

def main():
    global SAMPLE_VALUES

    args = parse_args()
    SAMPLE_VALUES = max(1, args.samples)

    runtime_files = resolve_runtime_file_list(args)

    show_guide = SHOW_REPORT_GUIDE and not args.no_guide
    show_single = SHOW_SINGLE_FILE_REPORT and not args.no_single
    show_compare = SHOW_COMPARE_REPORT and not args.no_compare
    show_flags_only = SHOW_FLAGS_ONLY_REPORT or args.flags_only

    if args.flags_only:
        show_single = False
        show_compare = False

    if show_guide:
        print_report_guide()

    profiles = []

    for input_path in runtime_files:
        profile = load_and_profile_file(input_path)
        if profile is None:
            continue

        profiles.append(profile)

        if show_single:
            print_single_file_report(profile)

    if len(profiles) >= 2:
        left = profiles[0]
        right = profiles[1]
        rows = compare_profiles(left, right)

        if show_compare:
            print_compare_report(left, right, rows)

        if show_flags_only:
            print_flags_only_report(left, right, rows)

            print_right_side_duplicate_report(left, right, rows)


    elif len(profiles) == 1:
        print("\n⚠️ Only one JSON file loaded successfully; compare report skipped.\n")
    else:
        print("\n❌ No JSON files loaded successfully.\n")


if __name__ == "__main__":
    main()
