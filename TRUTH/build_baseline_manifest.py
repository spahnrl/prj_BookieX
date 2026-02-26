import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from copy import deepcopy

# -----------------------------
# CONFIG
# -----------------------------
BASELINE_DIR = Path(__file__).parent / "baseline_snapshot"
MANIFEST_PATH = Path(__file__).parent / "baseline_manifest.json"

# Fields to ignore if present (timestamps, run markers, etc.)
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

        # Sort list deterministically if possible
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
# BUILD MANIFEST
# -----------------------------

def main():
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": []
    }

    for file_path in sorted(BASELINE_DIR.glob("*.json")):
        with open(file_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        normalized_data = normalize_structure(deepcopy(raw_data))
        sha = compute_sha256(normalized_data)
        schema_keys = extract_schema_keys(normalized_data)

        row_count = (
            len(normalized_data)
            if isinstance(normalized_data, list)
            else 1
        )

        manifest["files"].append({
            "file": file_path.name,
            "row_count": row_count,
            "sha256": sha,
            "size_bytes": file_path.stat().st_size,
            "schema_keys": schema_keys
        })

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Baseline manifest written to: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()