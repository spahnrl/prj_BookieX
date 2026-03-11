"""Verify domain isolation: scripts find data in data/nba/ and data/ncaam/ parallel layout."""
import os
import sys
from pathlib import Path

# Project root
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from configs.leagues import league_nba, league_ncaam
from utils.io_helpers import (
    get_final_view_json_path,
    get_canonical_games_json_path,
    get_odds_master_path,
    get_boxscore_path,
)


def check_isolation():
    print("--- Domain Isolation Audit ---")
    ok = True

    # NBA dirs
    for name, path in [
        ("NBA root", league_nba.DATA_ROOT),
        ("NBA raw", league_nba.RAW_DIR),
        ("NBA processed", league_nba.PROCESSED_DIR),
        ("NBA view", league_nba.VIEW_DIR),
    ]:
        exists = path.exists()
        if not exists:
            ok = False
        print(f"  {name}: {path.relative_to(ROOT)} - {'OK' if exists else 'MISSING'}")

    # Key NBA files (new locations)
    for label, get_path in [
        ("NBA final view JSON", lambda: get_final_view_json_path("nba")),
        ("NBA canonical JSON", lambda: get_canonical_games_json_path("nba")),
        ("NBA odds master", lambda: get_odds_master_path("nba")),
        ("NBA boxscores", lambda: get_boxscore_path("nba")),
    ]:
        try:
            p = get_path()
            exists = p and p.exists()
            if not exists:
                ok = False
            print(f"  {label}: {p.relative_to(ROOT) if p else p} - {'OK' if exists else 'MISSING'}")
        except Exception as e:
            ok = False
            print(f"  {label}: ERROR - {e}")

    # NCAAM view dir and final view
    view_dir = league_ncaam.VIEW_DIR
    print(f"  NCAAM view dir: {view_dir.relative_to(ROOT)} - {'OK' if view_dir.exists() else 'MISSING'}")
    if not view_dir.exists():
        ok = False
    try:
        p = get_final_view_json_path("ncaam")
        exists = p and p.exists()
        if not exists:
            ok = False
        print(f"  NCAAM final view JSON: {p.relative_to(ROOT) if p else p} - {'OK' if exists else 'MISSING'}")
    except Exception as e:
        ok = False
        print(f"  NCAAM final view JSON: ERROR - {e}")

    # No cross-contamination
    if league_nba.DATA_ROOT.exists():
        ncaam_in_nba = [f for f in os.listdir(league_nba.DATA_ROOT) if "ncaam" in f.lower()]
        if ncaam_in_nba:
            print(f"  WARNING: NCAAM-named items under NBA: {ncaam_in_nba}")
        else:
            print("  Cross-check: no NCAAM-named files under data/nba/ - OK")

    print("--- End Audit ---")
    return ok


if __name__ == "__main__":
    success = check_isolation()
    sys.exit(0 if success else 1)