"""
a_data_static_000_nba_team_map.py

Load static NBA team metadata (authoritative, stable, offline).
NO NETWORK. NO SSL. NO FAILURES.

Writes:
  data/raw/nba_team_map.json
  data/raw/nba_team_map.csv
"""

import json
import csv
from pathlib import Path


STATIC_JSON = Path("data/static/nba_team_map.json")


def run(output_dir: str = "data/raw") -> None:
    if not STATIC_JSON.exists():
        raise FileNotFoundError(f"Missing static team map: {STATIC_JSON}")

    with STATIC_JSON.open("r", encoding="utf-8") as f:
        records = json.load(f)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "nba_team_map.json"
    csv_path = out_dir / "nba_team_map.csv"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)

    print("Team map loaded from static reference data")
    print(f"JSON: {json_path}")
    print(f"CSV : {csv_path}")


if __name__ == "__main__":
    run()
