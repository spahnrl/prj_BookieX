"""
tools/merge_and_heal.py

Staged Recovery – Merge: Heal empty records in master with temp pull, then archive temp.

- Safe Merge Rule: Load current master (data/external/odds_api_raw.json) and
  data/temp_historical_odds.json. Optionally load data/temp_ncaam_historical_odds.json.
- NBA: (1) Heal empty records in master with temp pull; do not overwrite populated data.
  (2) Append logic: any game in temp whose id does NOT exist in the master is appended
  (no duplicates). (3) After merge, sort master by commence_time.
  (4) Phase 2: Write merged snapshot to data/nba/raw/odds_master_nba.json so the NBA
  pipeline (f_gen_041) uses 3-season paid history and graded count can exceed 2,000.
- NCAAM: If temp_ncaam exists, add its games to data/ncaam/market/raw/ in a new
  timestamped file, skipping any event already present with non-empty data (no overwrite).
- Cleanup: Archive temp file(s) after merge.

Usage:
  python tools/merge_and_heal.py
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MASTER_ODDS_PATH = PROJECT_ROOT / "data" / "external" / "odds_api_raw.json"
# NBA pipeline (f_gen_041) reads from data/nba/raw/odds_master_nba.json when present
NBA_ODDS_MASTER_PATH = PROJECT_ROOT / "data" / "nba" / "raw" / "odds_master_nba.json"
TEMP_ODDS_PATH = PROJECT_ROOT / "data" / "temp_historical_odds.json"
TEMP_NCAAM_ODDS_PATH = PROJECT_ROOT / "data" / "temp_ncaam_historical_odds.json"
NCAAM_MARKET_RAW_DIR = PROJECT_ROOT / "data" / "ncaam" / "market" / "raw"
ARCHIVE_DIR = PROJECT_ROOT / "data" / "archive"


def is_game_empty(game: dict) -> bool:
    """
    True if the game record is 'Empty': no bookmakers or no spreads/totals outcomes.
    """
    if not game or not isinstance(game, dict):
        return True
    bookmakers = game.get("bookmakers") or []
    if not bookmakers:
        return True
    has_spread_or_total = False
    for b in bookmakers:
        if not isinstance(b, dict):
            continue
        for m in b.get("markets") or []:
            if not isinstance(m, dict):
                continue
            if m.get("key") not in ("spreads", "totals"):
                continue
            outcomes = m.get("outcomes") or []
            if outcomes:
                has_spread_or_total = True
                break
        if has_spread_or_total:
            break
    return not has_spread_or_total


def load_master() -> list[dict]:
    if not MASTER_ODDS_PATH.exists():
        raise SystemExit(f"Master file not found: {MASTER_ODDS_PATH}")
    with open(MASTER_ODDS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("Master file must be a JSON array of snapshots.")
    return data


def load_temp() -> dict:
    if not TEMP_ODDS_PATH.exists():
        raise SystemExit(f"Temp file not found: {TEMP_ODDS_PATH}. Run tools/fetch_missing_raw.py first.")
    with open(TEMP_ODDS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "data" not in data:
        raise SystemExit("Temp file must be a JSON object with a 'data' array.")
    return data


def load_temp_ncaam() -> dict:
    if not TEMP_NCAAM_ODDS_PATH.exists():
        raise SystemExit(f"Temp NCAAM file not found: {TEMP_NCAAM_ODDS_PATH}.")
    with open(TEMP_NCAAM_ODDS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "data" not in data:
        raise SystemExit("Temp NCAAM file must be a JSON object with a 'data' array.")
    return data


def ncaam_existing_non_empty_ids() -> set[str]:
    """Collect event ids that already have non-empty data in NCAAM market folder."""
    non_empty = set()
    if not NCAAM_MARKET_RAW_DIR.exists():
        return non_empty
    for path in NCAAM_MARKET_RAW_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                snap = json.load(f)
        except Exception:
            continue
        if not isinstance(snap, dict):
            continue
        for g in snap.get("data") or []:
            eid = (g.get("id") or "").strip()
            if not eid:
                continue
            if not is_game_empty(g):
                non_empty.add(eid)
    return non_empty


def count_master_games(snapshots: list) -> int:
    return sum(len(s.get("data") or []) for s in snapshots if isinstance(s, dict))


def main() -> None:
    did_nba = False
    did_ncaam = False

    # ----- NBA: heal + append new games, then sort by commence_time -----
    if TEMP_ODDS_PATH.exists():
        master = load_master()
        temp = load_temp()
        temp_games = list(temp.get("data") or [])
        heal_by_id = {str(g.get("id") or "").strip(): g for g in temp_games if (g.get("id") or "").strip()}

        count_before = count_master_games(master)
        healed = 0
        for snap in master:
            if not isinstance(snap, dict):
                continue
            data = snap.get("data") or []
            for i, game in enumerate(data):
                if not isinstance(game, dict):
                    continue
                gid = (game.get("id") or "").strip()
                if not gid:
                    continue
                if not is_game_empty(game):
                    continue
                replacement = heal_by_id.get(gid)
                if replacement is None:
                    continue
                data[i] = dict(replacement)
                healed += 1

        # Append logic: games in temp whose id does NOT exist in master (dedupe by id)
        master_ids = set()
        for snap in master:
            if not isinstance(snap, dict):
                continue
            for g in snap.get("data") or []:
                eid = (g.get("id") or "").strip()
                if eid:
                    master_ids.add(eid)
        seen_temp = set()
        to_append = []
        for g in temp_games:
            if not isinstance(g, dict):
                continue
            eid = (g.get("id") or "").strip()
            if not eid or eid in master_ids or eid in seen_temp:
                continue
            seen_temp.add(eid)
            to_append.append(dict(g))
        appended = len(to_append)
        if to_append:
            master.append({
                "captured_at_utc": temp.get("captured_at_utc", datetime.now(timezone.utc).isoformat()),
                "sport": temp.get("sport", "basketball_nba"),
                "source": temp.get("source", "the_odds_api"),
                "description": temp.get("description", "fetch_missing_raw_historical"),
                "data": to_append,
            })

        count_after = count_master_games(master)
        if count_after < count_before:
            raise SystemExit(
                f"Merge would result in loss of records: before={count_before}, after={count_after}. Aborting."
            )

        # Flatten all games, sort by commence_time, write as single snapshot so file stays organized
        all_games = []
        for snap in master:
            if not isinstance(snap, dict):
                continue
            for g in snap.get("data") or []:
                if isinstance(g, dict):
                    all_games.append(g)
        all_games.sort(key=lambda g: (g.get("commence_time") or ""))

        merged_snapshot = {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "sport": "basketball_nba",
            "source": "the_odds_api",
            "description": "merged",
            "data": all_games,
        }
        master_payload = [merged_snapshot]
        MASTER_ODDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MASTER_ODDS_PATH, "w", encoding="utf-8") as f:
            json.dump(master_payload, f, indent=2)
        # Phase 2: write same merged snapshot to NBA pipeline master so graded count can exceed 2,000
        NBA_ODDS_MASTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(NBA_ODDS_MASTER_PATH, "w", encoding="utf-8") as f:
            json.dump(master_payload, f, indent=2)
        print(f"NBA: Healed {healed} empty records, appended {appended} new games. Master sorted by commence_time.")
        print(f"  Written to {MASTER_ODDS_PATH} and {NBA_ODDS_MASTER_PATH} (pipeline will use latter for >2,000 graded).")
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_path = ARCHIVE_DIR / f"temp_historical_odds_{ts}.json"
        shutil.move(str(TEMP_ODDS_PATH), str(archive_path))
        print(f"Archived NBA temp to {archive_path}")
        did_nba = True

    # ----- NCAAM: patch temp_ncaam into market folder (no overwrite) -----
    if TEMP_NCAAM_ODDS_PATH.exists():
        temp_ncaam = load_temp_ncaam()
        temp_ncaam_games = list(temp_ncaam.get("data") or [])
        existing_non_empty = ncaam_existing_non_empty_ids()
        to_add = [g for g in temp_ncaam_games if (g.get("id") or "").strip() not in existing_non_empty]
        skipped = len(temp_ncaam_games) - len(to_add)

        NCAAM_MARKET_RAW_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = NCAAM_MARKET_RAW_DIR / f"ncaam_odds_raw_{ts}.json"
        payload = {
            "captured_at_utc": temp_ncaam.get("captured_at_utc", datetime.now(timezone.utc).isoformat()),
            "sport": temp_ncaam.get("sport", "basketball_ncaab"),
            "source": temp_ncaam.get("source", "the_odds_api"),
            "description": temp_ncaam.get("description", "fetch_missing_raw"),
            "data": to_add,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"NCAAM: Added {len(to_add)} games to {out_path} (skipped {skipped} already present with data).")
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archive_path = ARCHIVE_DIR / f"temp_ncaam_historical_odds_{ts}.json"
        shutil.move(str(TEMP_NCAAM_ODDS_PATH), str(archive_path))
        print(f"Archived NCAAM temp to {archive_path}")
        did_ncaam = True

    if not did_nba and not did_ncaam:
        raise SystemExit(
            f"No temp files found. Run tools/fetch_missing_raw.py first. "
            f"Expected {TEMP_ODDS_PATH} and/or {TEMP_NCAAM_ODDS_PATH}."
        )


if __name__ == "__main__":
    main()
