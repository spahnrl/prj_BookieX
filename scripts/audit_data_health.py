"""
scripts/audit_data_health.py

Audit NBA and NCAAM data pipeline for "State of Truth" backtest readiness.

- Count validation: raw schedule counts vs final view counts
- Odds coverage: % of games with non-null/non-empty betting lines
- Join failure analysis: raw schedule game IDs missing from final view

Authority files:
  data/nba/view/final_game_view.json
  data/ncaam/view/final_game_view_ncaam.json
  f_gen_041_add_betting_lines.py (join logic)
"""

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Authority paths
NBA_RAW_SCHEDULE = PROJECT_ROOT / "data" / "nba" / "raw" / "nba_schedule.json"
NBA_FINAL_VIEW = PROJECT_ROOT / "data" / "nba" / "view" / "final_game_view.json"
NCAAM_RAW_SCHEDULE_CSV = PROJECT_ROOT / "data" / "ncaam" / "raw" / "ncaam_schedule_raw.csv"
NCAAM_RAW_SCHEDULE_JSON = PROJECT_ROOT / "data" / "ncaam" / "raw" / "ncaam_schedule_raw_latest.json"
NCAAM_FINAL_VIEW = PROJECT_ROOT / "data" / "ncaam" / "view" / "final_game_view_ncaam.json"


def _has_odds_nba(game: dict) -> bool:
    """True if game has at least one usable spread or total from market."""
    sh = game.get("spread_home")
    t = game.get("total")
    if sh is not None and str(sh).strip() != "":
        return True
    if t is not None and str(t).strip() != "":
        return True
    # Also treat odds_history as having had odds
    hist = game.get("odds_history") or []
    if hist and isinstance(hist, list):
        for h in hist:
            if h.get("market_spread_home") is not None or h.get("market_total") is not None:
                return True
    return False


def _has_odds_ncaam(game: dict) -> bool:
    """True if game has at least one non-empty spread/total/moneyline."""
    for key in ("spread_home", "spread_away", "total", "moneyline_home", "moneyline_away"):
        v = game.get(key)
        if v is not None and str(v).strip() != "":
            return True
    return False


def load_nba_raw_schedule() -> list[dict]:
    if not NBA_RAW_SCHEDULE.exists():
        return []
    with open(NBA_RAW_SCHEDULE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def load_nba_final_view() -> list[dict]:
    if not NBA_FINAL_VIEW.exists():
        return []
    with open(NBA_FINAL_VIEW, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "games" in data:
        return data["games"]
    return data if isinstance(data, list) else []


def load_ncaam_raw_schedule() -> list[dict]:
    """Load NCAAM raw schedule; prefer CSV, fallback to JSON."""
    rows = []
    if NCAAM_RAW_SCHEDULE_CSV.exists():
        with open(NCAAM_RAW_SCHEDULE_CSV, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    elif NCAAM_RAW_SCHEDULE_JSON.exists():
        with open(NCAAM_RAW_SCHEDULE_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict) and "events" in data:
            rows = data["events"]
        else:
            rows = []
    return rows


def load_ncaam_final_view() -> list[dict]:
    if not NCAAM_FINAL_VIEW.exists():
        return []
    with open(NCAAM_FINAL_VIEW, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def run_audit() -> dict:
    results = {"nba": {}, "ncaam": {}}

    # --- NBA ---
    nba_raw = load_nba_raw_schedule()
    nba_final = load_nba_final_view()
    nba_raw_ids = {str(g.get("game_id") or "").strip() for g in nba_raw if g.get("game_id")}
    nba_final_ids = {str(g.get("game_id") or "").strip() for g in nba_final if g.get("game_id")}
    nba_with_odds = sum(1 for g in nba_final if _has_odds_nba(g))
    nba_join_missing = sorted(nba_raw_ids - nba_final_ids)
    nba_in_final_not_raw = sorted(nba_final_ids - nba_raw_ids)

    results["nba"] = {
        "raw_schedule_count": len(nba_raw),
        "final_view_count": len(nba_final),
        "games_with_odds": nba_with_odds,
        "pct_coverage": round(100.0 * nba_with_odds / len(nba_final), 1) if nba_final else 0.0,
        "raw_ids": nba_raw_ids,
        "final_ids": nba_final_ids,
        "join_failure_ids": nba_join_missing,
        "in_final_not_raw": nba_in_final_not_raw,
    }

    # --- NCAAM ---
    ncaam_raw = load_ncaam_raw_schedule()
    ncaam_final = load_ncaam_final_view()
    # Raw CSV/JSON may use 'game_id' as numeric or string (e.g. 401822969)
    ncaam_raw_ids = set()
    for g in ncaam_raw:
        gid = g.get("game_id") or g.get("id") or g.get("event_id")
        if gid is not None:
            ncaam_raw_ids.add(str(gid).strip())
    # Final view game_id is "ncaam_401822969"; strip prefix for comparison
    ncaam_final_ids = set()
    for g in ncaam_final:
        gid = (g.get("game_id") or "").strip()
        if gid.startswith("ncaam_"):
            ncaam_final_ids.add(gid[6:])
        elif gid:
            ncaam_final_ids.add(gid)
    ncaam_with_odds = sum(1 for g in ncaam_final if _has_odds_ncaam(g))
    ncaam_join_missing = sorted(ncaam_raw_ids - ncaam_final_ids)
    ncaam_in_final_not_raw = sorted(ncaam_final_ids - ncaam_raw_ids)

    results["ncaam"] = {
        "raw_schedule_count": len(ncaam_raw),
        "final_view_count": len(ncaam_final),
        "games_with_odds": ncaam_with_odds,
        "pct_coverage": round(100.0 * ncaam_with_odds / len(ncaam_final), 1) if ncaam_final else 0.0,
        "raw_ids": ncaam_raw_ids,
        "final_ids": ncaam_final_ids,
        "join_failure_ids": ncaam_join_missing,
        "in_final_not_raw": ncaam_in_final_not_raw,
    }

    return results


def print_report(results: dict) -> None:
    nba = results["nba"]
    ncaam = results["ncaam"]

    print("\n" + "=" * 70)
    print("DATA HEALTH TABLE (State of Truth - Backtest Readiness)")
    print("=" * 70)
    print()
    print("  League | Total Games (Final) | Raw Schedule | Games w/ Odds | % Coverage")
    print("  -------+--------------------+--------------+---------------+------------")
    print(f"  NBA    | {nba['final_view_count']:>18} | {nba['raw_schedule_count']:>12} | {nba['games_with_odds']:>13} | {nba['pct_coverage']:>10}%")
    print(f"  NCAAM  | {ncaam['final_view_count']:>18} | {ncaam['raw_schedule_count']:>12} | {ncaam['games_with_odds']:>13} | {ncaam['pct_coverage']:>10}%")
    print("  -------+--------------------+--------------+---------------+------------")
    print()
    print("  Notes:")
    print("  - Total Games (Final) = rows in final_game_view JSON (authority for backtest).")
    print("  - Raw Schedule = count from data/{league}/raw/ schedule file(s).")
    print("  - Games w/ Odds = games with non-null/non-empty spread or total (f_gen_041 join).")
    print("  - %% Coverage = Games w/ Odds / Total Games (Final).")
    print()
    print("  ODDS COVERAGE AUDIT (games with null/missing betting lines)")
    print("  -------+----------------------------------------------------------------")
    nba_missing = nba["final_view_count"] - nba["games_with_odds"]
    ncaam_missing = ncaam["final_view_count"] - ncaam["games_with_odds"]
    print(f"  NBA    | {nba_missing} games ({100 - nba['pct_coverage']:.1f}%) with no odds (spread/total null or empty)")
    print(f"  NCAAM  | {ncaam_missing} games ({100 - ncaam['pct_coverage']:.1f}%) with no odds")
    print("  -------+----------------------------------------------------------------")
    print()

    # Join failure summary
    print("  JOIN FAILURE ANALYSIS (raw schedule game IDs not in final view)")
    print("  -------+----------------------------------------------------------------")
    nba_miss = nba["join_failure_ids"]
    ncaam_miss = ncaam["join_failure_ids"]
    print(f"  NBA    | {len(nba_miss)} raw games missing from final view")
    if nba_miss:
        sample = nba_miss[:15]
        print(f"         Sample IDs: {sample}")
        if len(nba_miss) > 15:
            print(f"         ... and {len(nba_miss) - 15} more")
    print(f"  NCAAM  | {len(ncaam_miss)} raw games missing from final view")
    if ncaam_miss:
        sample = ncaam_miss[:15]
        print(f"         Sample IDs: {sample}")
        if len(ncaam_miss) > 15:
            print(f"         ... and {len(ncaam_miss) - 15} more")
    print("  -------+----------------------------------------------------------------")
    print()

    # Count validation
    print("  COUNT VALIDATION (raw vs final)")
    print("  - NBA:   raw=%s  final=%s  delta=%s (positive = fewer in final, e.g. 003 team map or 022 collapse)" % (
        nba["raw_schedule_count"], nba["final_view_count"],
        nba["raw_schedule_count"] - nba["final_view_count"]))
    print("  - NCAAM: raw=%s  final=%s  delta=%s" % (
        ncaam["raw_schedule_count"], ncaam["final_view_count"],
        ncaam["raw_schedule_count"] - ncaam["final_view_count"]))
    print()
    print("=" * 70 + "\n")


if __name__ == "__main__":
    r = run_audit()
    print_report(r)
