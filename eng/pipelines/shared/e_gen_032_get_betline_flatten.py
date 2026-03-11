"""
e_gen_032_get_betline_flatten.py

Unified flattening of raw odds into downstream format.

- NBA: reads data/external/odds_api_raw.json (list of snapshots), groups by game,
  builds one row per game with last/consensus spreads, totals, moneylines; writes
  data/nba/derived/nba_betlines_flattened.json and .csv.
- NCAAM: reads latest raw snapshot from config path, flattens to one row per
  game x bookmaker x market x outcome; writes flat CSV(s) from config.

Usage:
  python e_gen_032_get_betline_flatten.py --league nba
  python e_gen_032_get_betline_flatten.py --league ncaam
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from configs.leagues.league_nba import DERIVED_DIR
from utils.run_log import set_silent, log_info

# =====================================================
# NBA: multi-snapshot -> one row per game (last + consensus)
# =====================================================

NBA_ODDS_JSON = _PROJECT_ROOT / "data/external/odds_api_raw.json"
NBA_OUT_JSON = DERIVED_DIR / "nba_betlines_flattened.json"
NBA_OUT_CSV = DERIVED_DIR / "nba_betlines_flattened.csv"

NBA_BOOK_PRIORITY = [
    "pinnacle", "circa", "lowvig", "fanduel", "draftkings",
    "betmgm", "betrivers", "bovada", "betus", "betonlineag", "mybookieag",
]
NBA_VALID_MARKETS = {"spreads", "totals", "h2h"}


def _nba_parse_utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _nba_avg(vals) -> float | None:
    return round(mean(vals), 3) if vals else None


def _nba_latest_per_bookmaker(game_rows: list) -> list:
    latest = {}
    for r in game_rows:
        key = (r["bookmaker_key"], r["market"], r["outcome"])
        ts = _nba_parse_utc(r["odds_snapshot_utc"])
        if key not in latest or ts > _nba_parse_utc(latest[key]["odds_snapshot_utc"]):
            latest[key] = r
    return list(latest.values())


def _nba_earliest_per_bookmaker(game_rows: list) -> list:
    earliest = {}
    for r in game_rows:
        key = (r["bookmaker_key"], r["market"], r["outcome"])
        ts = _nba_parse_utc(r["odds_snapshot_utc"])
        if key not in earliest or ts < _nba_parse_utc(earliest[key]["odds_snapshot_utc"]):
            earliest[key] = r
    return list(earliest.values())


def _nba_pick_last(game_rows: list, market: str, outcome: str) -> float | None:
    candidates = [
        r for r in game_rows
        if r["market"] == market and r["outcome"] == outcome
        and (
            (market == "h2h" and r.get("price") is not None)
            or (market != "h2h" and r.get("point") is not None)
        )
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda r: (
            _nba_parse_utc(r["odds_snapshot_utc"]),
            -NBA_BOOK_PRIORITY.index(r["bookmaker_key"])
            if r["bookmaker_key"] in NBA_BOOK_PRIORITY else -999,
        ),
        reverse=True,
    )
    return candidates[0]["price"] if market == "h2h" else candidates[0]["point"]


def _nba_consensus(rows: list, market: str, outcome: str) -> float | None:
    vals = [
        (r["price"] if market == "h2h" else r["point"])
        for r in rows
        if r["market"] == market and r["outcome"] == outcome
        and (
            (market == "h2h" and r.get("price") is not None)
            or (market != "h2h" and r.get("point") is not None)
        )
    ]
    return _nba_avg(vals)


def run_nba() -> None:
    from utils.datetime_bridge import derive_game_day_local

    if not NBA_ODDS_JSON.exists():
        raise FileNotFoundError(f"Missing raw odds: {NBA_ODDS_JSON}")

    with open(NBA_ODDS_JSON, "r", encoding="utf-8") as f:
        snapshots = json.load(f)

    rows = []
    for snap in snapshots:
        captured = snap.get("captured_at_utc")
        if not captured:
            continue
        for game in snap.get("data", []):
            home = game.get("home_team")
            away = game.get("away_team")
            commence = game.get("commence_time")
            odds_id = (game.get("id") or "")
            if isinstance(odds_id, str):
                odds_id = odds_id.strip()
            else:
                odds_id = str(odds_id).strip() if odds_id is not None else ""
            if not (home and away and commence):
                continue
            for book in game.get("bookmakers", []):
                for market in book.get("markets", []):
                    if market.get("key") not in NBA_VALID_MARKETS:
                        continue
                    for o in market.get("outcomes", []):
                        rows.append({
                            "home_team": home,
                            "away_team": away,
                            "odds_commence_time_raw": commence,
                            "odds_snapshot_utc": captured,
                            "odds_id": odds_id,
                            "bookmaker_key": book.get("key"),
                            "market": market.get("key"),
                            "outcome": o.get("name"),
                            "point": o.get("point"),
                            "price": o.get("price"),
                        })

    games = defaultdict(list)
    for r in rows:
        key = (r["home_team"], r["away_team"], r["odds_commence_time_raw"])
        games[key].append(r)

    final = []
    for (home, away, commence), g_rows in games.items():
        g_latest = _nba_latest_per_bookmaker(g_rows)
        g_earliest = _nba_earliest_per_bookmaker(g_rows)
        odds_id = (g_rows[0].get("odds_id") or "") if g_rows else ""
        final.append({
            "home_team": home,
            "away_team": away,
            "odds_commence_time_utc": commence,
            "nba_game_day_local": derive_game_day_local(commence_time_utc=commence, league="NBA"),
            "odds_id": odds_id,
            "odds_snapshot_last_utc": max(r["odds_snapshot_utc"] for r in g_rows),
            "spread_home_last": _nba_pick_last(g_rows, "spreads", home),
            "spread_away_last": _nba_pick_last(g_rows, "spreads", away),
            "spread_home_consensus": _nba_consensus(g_latest, "spreads", home),
            "spread_away_consensus": _nba_consensus(g_latest, "spreads", away),
            "spread_home_consensus_all_time": _nba_consensus(g_earliest, "spreads", home),
            "spread_away_consensus_all_time": _nba_consensus(g_earliest, "spreads", away),
            "total_last": _nba_pick_last(g_rows, "totals", "Over"),
            "total_consensus": _nba_consensus(g_latest, "totals", "Over"),
            "total_consensus_all_time": _nba_consensus(g_earliest, "totals", "Over"),
            "moneyline_home_last": _nba_pick_last(g_rows, "h2h", home),
            "moneyline_away_last": _nba_pick_last(g_rows, "h2h", away),
            "moneyline_home_consensus": _nba_consensus(g_latest, "h2h", home),
            "moneyline_away_consensus": _nba_consensus(g_latest, "h2h", away),
            "moneyline_home_consensus_all_time": _nba_consensus(g_earliest, "h2h", home),
            "moneyline_away_consensus_all_time": _nba_consensus(g_earliest, "h2h", away),
            "consensus_book_count": len({r["bookmaker_key"] for r in g_latest}),
            "all_time_snapshot_count": len({r["odds_snapshot_utc"] for r in g_rows}),
        })

    NBA_OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(NBA_OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2)
    if final:
        with open(NBA_OUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=final[0].keys())
            writer.writeheader()
            writer.writerows(final)

    log_info("Betlines flattened (NBA: spreads + totals + moneylines)")
    log_info(f"JSON -> {NBA_OUT_JSON}")
    log_info(f"CSV  -> {NBA_OUT_CSV}")


# =====================================================
# NCAAM: single snapshot -> flat rows (game x bookmaker x market x outcome)
# =====================================================

def _ncaam_flatten_snapshot(snapshot: dict) -> list[dict]:
    raw_data = snapshot.get("data", [])
    if not isinstance(raw_data, list):
        raise ValueError("Expected snapshot['data'] to be a list")
    captured_at = snapshot.get("captured_at_utc")
    sport = snapshot.get("sport")
    source = snapshot.get("source")
    rows = []
    for game in raw_data:
        game_id = game.get("id")
        commence_time = game.get("commence_time")
        home_team = game.get("home_team")
        away_team = game.get("away_team")
        last_update_game = game.get("last_update")
        for bookmaker in game.get("bookmakers", []):
            bookmaker_key = bookmaker.get("key")
            bookmaker_title = bookmaker.get("title")
            bookmaker_last_update = bookmaker.get("last_update")
            for market in bookmaker.get("markets", []):
                market_key = market.get("key")
                market_last_update = market.get("last_update")
                for outcome in market.get("outcomes", []):
                    rows.append({
                        "captured_at_utc": captured_at,
                        "source": source,
                        "sport": sport,
                        "game_id": game_id,
                        "commence_time": commence_time,
                        "game_last_update": last_update_game,
                        "home_team": home_team,
                        "away_team": away_team,
                        "bookmaker_key": bookmaker_key,
                        "bookmaker_title": bookmaker_title,
                        "bookmaker_last_update": bookmaker_last_update,
                        "market_key": market_key,
                        "market_last_update": market_last_update,
                        "outcome_name": outcome.get("name"),
                        "price": outcome.get("price"),
                        "point": outcome.get("point"),
                    })
    return rows


NCAAM_FLAT_FIELDS = [
    "captured_at_utc", "source", "sport", "game_id", "commence_time", "game_last_update",
    "home_team", "away_team", "bookmaker_key", "bookmaker_title", "bookmaker_last_update",
    "market_key", "market_last_update", "outcome_name", "price", "point",
]


def run_ncaam() -> None:
    from configs.leagues.league_ncaam import (
        ODDS_RAW_LATEST_PATH,
        ODDS_FLAT_LATEST_PATH,
        ensure_ncaam_dirs,
        timestamped_odds_flat_path,
    )
    ensure_ncaam_dirs()

    if not ODDS_RAW_LATEST_PATH.exists():
        raise FileNotFoundError(f"Missing raw odds: {ODDS_RAW_LATEST_PATH}")

    with open(ODDS_RAW_LATEST_PATH, "r", encoding="utf-8") as f:
        snapshot = json.load(f)
    if not isinstance(snapshot, dict):
        raise ValueError("Expected latest raw odds snapshot to be a JSON object")

    rows = _ncaam_flatten_snapshot(snapshot)
    captured_at = snapshot.get("captured_at_utc")
    if not captured_at:
        raise ValueError("Missing captured_at_utc in raw snapshot")

    ts_label = (
        str(captured_at)
        .replace("-", "").replace(":", "").replace("T", "_")
        .replace("+00:00", "").replace("Z", "").split(".")[0]
    )
    ts_path = timestamped_odds_flat_path(ts_label)

    ODDS_FLAT_LATEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ODDS_FLAT_LATEST_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=NCAAM_FLAT_FIELDS)
        w.writeheader()
        if rows:
            w.writerows(rows)

    ts_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ts_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=NCAAM_FLAT_FIELDS)
        w.writeheader()
        if rows:
            w.writerows(rows)

    log_info(f"Loaded raw snapshot: {ODDS_RAW_LATEST_PATH}")
    log_info(f"Flat latest CSV -> {ODDS_FLAT_LATEST_PATH}")
    log_info(f"Flat stamped CSV -> {ts_path}")
    log_info(f"Rows: {len(rows)}")


# =====================================================
# ENTRYPOINT
# =====================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Flatten raw odds (NBA or NCAAM)")
    parser.add_argument("--league", required=True, choices=["nba", "ncaam"])
    parser.add_argument("--silent", action="store_true", help="Only print critical errors")
    args = parser.parse_args()
    set_silent(args.silent)
    if args.league == "nba":
        run_nba()
    else:
        run_ncaam()


if __name__ == "__main__":
    main()
