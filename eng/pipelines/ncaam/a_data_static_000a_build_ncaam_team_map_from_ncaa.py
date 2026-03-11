"""
a_data_static_000a_build_ncaam_team_map_from_ncaa.py

Build a draft authoritative NCAAM team map from NCAA-owned stats pages.

Purpose
-------
- Pull team names from NCAA.com men's DI basketball team-stat pages
- Deduplicate teams
- Build a clean static team map draft
- Write:
    data/static/ncaam_team_map.json
    data/static/ncaam_team_map.csv

Notes
-----
- NCAA is the source of truth here
- No legacy alias/map chain required
- This builds the STATIC source file
- a_data_static_000b_ncaam_team_map.py remains the loader/publisher
"""

import csv
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


OUTPUT_JSON = Path("data/ncaam/static/ncaam_team_map.json")
OUTPUT_CSV = Path("data/ncaam/static/ncaam_team_map.csv")

# NCAA-owned stats pages that expose DI men's basketball team tables
# We use multiple stat pages to reduce the risk of missing teams due to page quirks.
BASE_URLS = [
    "https://www.ncaa.com/stats/basketball-men/d1/current/team/145",   # Scoring Offense
    "https://www.ncaa.com/stats/basketball-men/d1/current/team/1288",  # Effective FG%
    "https://www.ncaa.com/stats/basketball-men/d1/current/team/859",   # Defensive Rebounds/Game
    "https://www.ncaa.com/stats/basketball-men/d1/current/team/152",   # 3PT%
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())

def build_team_name_norm_key(name: str) -> str:
    text = (name or "").strip().lower()

    text = text.replace("&", " and ")
    text = text.replace("'", "")
    text = text.replace(".", " ")
    text = text.replace("-", " ")
    text = text.replace("/", " ")
    text = text.replace(",", " ")
    text = text.replace("(", " ")
    text = text.replace(")", " ")

    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text.replace(" ", "")


def slugify_team_id(name: str) -> str:
    text = (name or "").strip().lower()

    text = text.replace("&", " and ")
    text = text.replace("'", "")
    text = text.replace(".", "")
    text = text.replace("/", " ")
    text = text.replace("-", " ")
    text = text.replace(",", " ")
    text = text.replace("(", " ")
    text = text.replace(")", " ")

    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text.replace(" ", "_")


def clean_team_name(name: str) -> str:
    text = normalize_space(name)

    # NCAA table extraction can sometimes carry leading "Image"
    if text.startswith("Image"):
        text = text[5:].strip()

    return text


def is_valid_team_name(name: str) -> bool:
    if not name:
        return False

    bad_values = {
        "team",
        "rank",
        "view all scores",
        "mens basketball",
        "team statistics",
        "individual statistics",
    }

    lowered = name.lower().strip()
    if lowered in bad_values:
        return False

    # Must contain at least one letter
    if not re.search(r"[a-zA-Z]", name):
        return False

    # Avoid obvious stat/header junk
    if len(name) < 2:
        return False

    return True


def fetch_html(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def extract_team_names_from_table(html: str) -> list[str]:
    """
    Parse NCAA stats HTML and try to extract the Team column from tables.
    """
    soup = BeautifulSoup(html, "html.parser")
    found = []

    tables = soup.find_all("table")
    for table in tables:
        headers = [normalize_space(th.get_text(" ", strip=True)).lower() for th in table.find_all("th")]
        if "team" not in headers:
            continue

        team_idx = headers.index("team")

        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue

            if len(cells) <= team_idx:
                continue

            raw = cells[team_idx].get_text(" ", strip=True)
            team_name = clean_team_name(raw)

            if is_valid_team_name(team_name):
                found.append(team_name)

    return found


def extract_team_names_fallback(html: str) -> list[str]:
    """
    Fallback parser for cases where NCAA page structure changes.
    Looks for table-like text rows around 'Team'.
    """
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    lines = [normalize_space(x) for x in text.splitlines() if normalize_space(x)]

    found = []
    capture = False

    for line in lines:
        lower = line.lower()

        if lower == "team":
            capture = True
            continue

        if not capture:
            continue

        # stop on obvious section changes
        if lower in {"g", "gm", "pts", "ppg", "fga", "pct", "rpg"}:
            continue

        # lines from fallback text often still include "ImageTeamName"
        if line.startswith("Image"):
            candidate = clean_team_name(line)
            if is_valid_team_name(candidate):
                found.append(candidate)

    return found


def extract_team_names_from_url(url: str) -> list[str]:
    html = fetch_html(url)

    names = extract_team_names_from_table(html)
    if names:
        return names

    return extract_team_names_fallback(html)


def gather_team_names() -> list[str]:
    all_names = []

    for base_url in BASE_URLS:
        empty_pages_in_a_row = 0

        # NCAA stats pagination usually uses /p2, /p3, etc.
        # p1 is the base URL with no suffix.
        for page_num in range(1, 15):
            if page_num == 1:
                url = base_url
            else:
                url = f"{base_url}/p{page_num}"

            try:
                page_names = extract_team_names_from_url(url)
            except requests.HTTPError as e:
                # Stop paging if the page doesn't exist
                status = getattr(e.response, "status_code", None)
                if status == 404:
                    break
                print(f"WARNING: HTTP error on {url}: {e}")
                empty_pages_in_a_row += 1
                if empty_pages_in_a_row >= 2:
                    break
                continue
            except Exception as e:
                print(f"WARNING: Failed parsing {url}: {e}")
                empty_pages_in_a_row += 1
                if empty_pages_in_a_row >= 2:
                    break
                continue

            page_names = [clean_team_name(x) for x in page_names if is_valid_team_name(x)]

            unique_page_names = []
            seen = set()
            for name in page_names:
                key = name.lower()
                if key not in seen:
                    seen.add(key)
                    unique_page_names.append(name)

            print(f"Fetched {url} -> {len(unique_page_names)} team names")

            if unique_page_names:
                all_names.extend(unique_page_names)
                empty_pages_in_a_row = 0
            else:
                empty_pages_in_a_row += 1
                if empty_pages_in_a_row >= 2:
                    break

            time.sleep(0.4)

    # global dedupe preserving order
    out = []
    seen = set()
    for name in all_names:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            out.append(name)

    return out


def build_records(team_names: list[str]) -> list[dict]:
    records = []

    for team_name in sorted(team_names, key=lambda x: x.lower()):
        records.append({
            "team_id": slugify_team_id(team_name),
            "team_display": team_name,
            "schedule_name": team_name,
            "market_name": team_name,
            "espn_name": team_name,
            "team_name_normalized": normalize_space(team_name).lower(),
            "team_name_norm_key": build_team_name_norm_key(team_name),
            "aliases": [],
        })

    return records


def validate_records(records: list[dict]) -> None:
    if not records:
        raise ValueError("No NCAAM teams were extracted from NCAA source")

    seen_ids = set()
    dupes = set()

    for row in records:
        team_id = (row.get("team_id") or "").strip()
        team_display = (row.get("team_display") or "").strip()

        if not team_id or not team_display:
            raise ValueError(f"Invalid record found: {row}")

        if team_id in seen_ids:
            dupes.add(team_id)
        seen_ids.add(team_id)

    if dupes:
        dupes_text = ", ".join(sorted(dupes))
        raise ValueError(f"Duplicate generated team_id values found: {dupes_text}")


def write_json(records: list[dict]) -> None:
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def write_csv(records: list[dict]) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "team_id",
        "team_display",
        "schedule_name",
        "market_name",
        "espn_name",
        "team_name_normalized",
        "team_name_norm_key",
        "aliases",
    ]

    csv_rows = []
    for row in records:
        csv_rows.append({
            "team_id": row["team_id"],
            "team_display": row["team_display"],
            "schedule_name": row["schedule_name"],
            "market_name": row["market_name"],
            "espn_name": row["espn_name"],
            "team_name_normalized": row["team_name_normalized"],
            "team_name_norm_key": row["team_name_norm_key"],
            "aliases": " | ".join(row.get("aliases", [])),
        })

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)


def run() -> None:
    team_names = gather_team_names()
    records = build_records(team_names)
    validate_records(records)

    write_json(records)
    write_csv(records)

    print("Built NCAAM static team map from NCAA source")
    print(f"Teams found: {len(records)}")
    print(f"JSON: {OUTPUT_JSON}")
    print(f"CSV : {OUTPUT_CSV}")


if __name__ == "__main__":
    run()
