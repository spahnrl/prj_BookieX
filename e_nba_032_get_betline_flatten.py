"""
e_nba_032_get_betline_flatten.py

PURE ETL
Flatten Odds API snapshots into ONE ROW PER GAME with:
- LAST line (single bookmaker, deterministic)
- CONSENSUS (latest per bookmaker)
- CONSENSUS_ALL_TIME (opening per bookmaker)

Markets supported:
- spreads
- totals

NO h2h
NO joins
NO NBA schedule logic
"""

import json
import csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from statistics import mean

from utils.datetime_bridge import derive_game_day_local


# =============================
# PATHS
# =============================

EXT_DIR = Path("data/external")
OUT_DIR = Path("data/derived")

ODDS_JSON = EXT_DIR / "odds_api_raw.json"
OUT_JSON = OUT_DIR / "nba_betlines_flattened.json"
OUT_CSV  = OUT_DIR / "nba_betlines_flattened.csv"

OUT_DIR.mkdir(parents=True, exist_ok=True)

# =============================
# CONFIG
# =============================

BOOK_PRIORITY = [
    "pinnacle",
    "circa",
    "lowvig",
    "fanduel",
    "draftkings",
    "betmgm",
    "betrivers",
    "bovada",
    "betus",
    "betonlineag",
    "mybookieag",
]

VALID_MARKETS = {"spreads", "totals", "h2h"}

# =============================
# HELPERS
# =============================

def parse_utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))

def avg(vals):
    return round(mean(vals), 3) if vals else None

def latest_per_bookmaker(game_rows):
    latest = {}
    for r in game_rows:
        key = (r["bookmaker_key"], r["market"], r["outcome"])
        ts = parse_utc(r["odds_snapshot_utc"])
        if key not in latest or ts > parse_utc(latest[key]["odds_snapshot_utc"]):
            latest[key] = r
    return list(latest.values())

def earliest_per_bookmaker(game_rows):
    earliest = {}
    for r in game_rows:
        key = (r["bookmaker_key"], r["market"], r["outcome"])
        ts = parse_utc(r["odds_snapshot_utc"])
        if key not in earliest or ts < parse_utc(earliest[key]["odds_snapshot_utc"]):
            earliest[key] = r
    return list(earliest.values())

def pick_last(game_rows, market, outcome):
    candidates = [
        r for r in game_rows
        if r["market"] == market
        and r["outcome"] == outcome
        and (
            (market == "h2h" and r.get("price") is not None)
            or (market != "h2h" and r.get("point") is not None)
        )
    ]
    if not candidates:
        return None

    candidates.sort(
        key=lambda r: (
            parse_utc(r["odds_snapshot_utc"]),
            -BOOK_PRIORITY.index(r["bookmaker_key"])
            if r["bookmaker_key"] in BOOK_PRIORITY else -999
        ),
        reverse=True
    )
    return (
        candidates[0]["price"]
        if market == "h2h"
        else candidates[0]["point"]
    )

def consensus(rows, market, outcome):
    vals = [
        (r["price"] if market == "h2h" else r["point"])
        for r in rows
        if r["market"] == market
        and r["outcome"] == outcome
        and (
            (market == "h2h" and r.get("price") is not None)
            or (market != "h2h" and r.get("point") is not None)
        )
    ]
    return avg(vals)

# =============================
# LOAD RAW SNAPSHOTS
# =============================

with open(ODDS_JSON, "r", encoding="utf-8") as f:
    snapshots = json.load(f)

# =============================
# FLATTEN SNAPSHOTS (NO h2h)
# =============================

rows = []

for snap in snapshots:
    captured = snap.get("captured_at_utc")
    if not captured:
        continue

    for game in snap.get("data", []):
        home = game.get("home_team")
        away = game.get("away_team")
        commence = game.get("commence_time")

        if not (home and away and commence):
            continue

        for book in game.get("bookmakers", []):
            for market in book.get("markets", []):
                if market.get("key") not in VALID_MARKETS:
                    continue

                for o in market.get("outcomes", []):
                    rows.append({
                        "home_team": home,
                        "away_team": away,
                        "odds_commence_time_raw": commence,
                        "odds_snapshot_utc": captured,
                        "bookmaker_key": book.get("key"),
                        "market": market.get("key"),
                        "outcome": o.get("name"),
                        "point": o.get("point"),
                        "price": o.get("price"),  # ← NEW (h2h only)
                    })

# =============================
# GROUP BY TRUE GAME IDENTITY
# =============================

games = defaultdict(list)

for r in rows:
    key = (
        r["home_team"],
        r["away_team"],
        r["odds_commence_time_raw"],
    )
    games[key].append(r)

# =============================
# BUILD FINAL GAME RECORDS
# =============================

final = []

for (home, away, commence), g_rows in games.items():
    g_latest   = latest_per_bookmaker(g_rows)
    g_earliest = earliest_per_bookmaker(g_rows)

    final.append({
        "home_team": home,
        "away_team": away,
        # "odds_commence_time_raw": commence,
        "odds_commence_time_utc": commence,

        # 🔒 BRIDGE FIELD (AUTHORITATIVE)
        "nba_game_day_local": derive_game_day_local(
            commence_time_utc=commence,
            league="NBA"
        ),

        "odds_snapshot_last_utc": max(r["odds_snapshot_utc"] for r in g_rows),
        # SPREAD
        "spread_home_last": pick_last(g_rows, "spreads", home),
        "spread_away_last": pick_last(g_rows, "spreads", away),
        "spread_home_consensus": consensus(g_latest, "spreads", home),
        "spread_away_consensus": consensus(g_latest, "spreads", away),
        "spread_home_consensus_all_time": consensus(g_earliest, "spreads", home),
        "spread_away_consensus_all_time": consensus(g_earliest, "spreads", away),

        # TOTAL
        "total_last": pick_last(g_rows, "totals", "Over"),
        "total_consensus": consensus(g_latest, "totals", "Over"),
        "total_consensus_all_time": consensus(g_earliest, "totals", "Over"),

        # H2H (MONEYLINE)
        "moneyline_home_last": pick_last(g_rows, "h2h", home),
        "moneyline_away_last": pick_last(g_rows, "h2h", away),
        "moneyline_home_consensus": consensus(g_latest, "h2h", home),
        "moneyline_away_consensus": consensus(g_latest, "h2h", away),
        "moneyline_home_consensus_all_time": consensus(g_earliest, "h2h", home),
        "moneyline_away_consensus_all_time": consensus(g_earliest, "h2h", away),

        # TRANSPARENCY
        "consensus_book_count": len({r["bookmaker_key"] for r in g_latest}),
        "all_time_snapshot_count": len({r["odds_snapshot_utc"] for r in g_rows}),
    })

# =============================
# WRITE OUTPUTS
# =============================

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(final, f, indent=2)

with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=final[0].keys())
    writer.writeheader()
    writer.writerows(final)

print("✅ Betlines flattened correctly (SPREADS + TOTALS + ALL_TIME CONSENSUS)")
print(f"📄 JSON → {OUT_JSON}")
print(f"📊 CSV  → {OUT_CSV}")