import json
import hashlib
from pathlib import Path
from copy import deepcopy

# -----------------------------
# CONFIG
# -----------------------------
LIVE_DIR = Path(__file__).parent.parent / "data"
BASELINE_DIR = Path(__file__).parent / "baseline_snapshot"
MANIFEST_PATH = Path(__file__).parent / "baseline_manifest.json"

IGNORED_FIELDS = {
    "generated_at",
    "created_at",
    "file_generated_at",
    "run_timestamp",
}

# -----------------------------
# HELPERS
# -----------------------------

def normalize_float(value):
    if isinstance(value, float):
        return round(value, 8)
    return value


def normalize_structure(data):
    if isinstance(data, dict):
        return {
            k: normalize_structure(normalize_float(v))
            for k, v in sorted(data.items())
            if k not in IGNORED_FIELDS
        }

    elif isinstance(data, list):
        normalized_list = [normalize_structure(item) for item in data]

        if normalized_list and isinstance(normalized_list[0], dict):
            if "game_id" in normalized_list[0]:
                normalized_list.sort(key=lambda x: x.get("game_id"))
            else:
                normalized_list.sort(key=lambda x: json.dumps(x, sort_keys=True))

        return normalized_list

    else:
        return normalize_float(data)


def compute_sha256(data):
    normalized_json = json.dumps(data, sort_keys=True).encode("utf-8")
    return hashlib.sha256(normalized_json).hexdigest()


def extract_schema_keys(data):
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return sorted(data[0].keys())
    elif isinstance(data, dict):
        return sorted(data.keys())
    return []


# -----------------------------
# VERIFY
# -----------------------------

def main():
    if not MANIFEST_PATH.exists():
        print("ERROR: baseline_manifest.json not found.")
        return

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    all_passed = True

    for entry in manifest["files"]:
        filename = entry["file"]
        baseline_file = BASELINE_DIR / filename
        live_file = None

        # Attempt to locate matching live file anywhere under /data
        for path in LIVE_DIR.rglob(filename):
            live_file = path
            break

        print(f"\nChecking: {filename}")

        if not live_file or not live_file.exists():
            print("  FAIL: Live file not found.")
            all_passed = False
            continue

        with open(live_file, "r", encoding="utf-8") as f:
            live_data = json.load(f)

        normalized_live = normalize_structure(deepcopy(live_data))
        live_sha = compute_sha256(normalized_live)
        live_schema = extract_schema_keys(normalized_live)
        live_row_count = (
            len(normalized_live)
            if isinstance(normalized_live, list)
            else 1
        )

        # Compare
        checks = {
            "Row Count": live_row_count == entry["row_count"],
            "Hash": live_sha == entry["sha256"],
            "Schema": live_schema == entry["schema_keys"],
        }

        for check_name, passed in checks.items():
            print(f"  {check_name}: {'PASS' if passed else 'FAIL'}")
            if not passed:
                all_passed = False

    print("\n===================================")
    print("DETERMINISM RESULT:", "PASS" if all_passed else "FAIL")
    print("===================================")


if __name__ == "__main__":
    main()