"""
One-time migration: move files to data/nba/ and data/ncaam/ parallel structure.
Run from project root: python scripts/run_migration.py
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA = PROJECT_ROOT / "data"

def main():
    # 1. Create directories
    dirs = [
        DATA / "nba" / "raw",
        DATA / "nba" / "processed",
        DATA / "nba" / "view",
        DATA / "ncaam" / "view",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        print(f"Created (or exists): {d.relative_to(PROJECT_ROOT)}")

    moves = []

    # 2. NBA moves
    if (DATA / "view" / "final_game_view.json").exists():
        moves.append((DATA / "view" / "final_game_view.json", DATA / "nba" / "view" / "final_game_view.json"))
    if (DATA / "view" / "nba_games_canonical.json").exists():
        moves.append((DATA / "view" / "nba_games_canonical.json", DATA / "nba" / "processed" / "nba_games_canonical.json"))
    # boxscores_nba.csv: derived has nba_boxscores_team.csv -> processed/boxscores_nba.csv
    src_box = DATA / "derived" / "nba_boxscores_team.csv"
    if src_box.exists():
        moves.append((src_box, DATA / "nba" / "processed" / "boxscores_nba.csv"))
    elif (DATA / "derived" / "boxscores_nba.csv").exists():
        moves.append((DATA / "derived" / "boxscores_nba.csv", DATA / "nba" / "processed" / "boxscores_nba.csv"))
    if (DATA / "external" / "odds_api_raw.json").exists():
        moves.append((DATA / "external" / "odds_api_raw.json", DATA / "nba" / "raw" / "odds_master_nba.json"))

    # 3. NCAAM moves
    if (DATA / "ncaam" / "processed" / "final_game_view_ncaam.json").exists():
        moves.append((DATA / "ncaam" / "processed" / "final_game_view_ncaam.json", DATA / "ncaam" / "view" / "final_game_view_ncaam.json"))

    for src, dst in moves:
        if src.resolve() == dst.resolve():
            continue
        if not src.exists():
            print(f"Skip (missing): {src}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst.unlink()
        src.rename(dst)
        print(f"Moved: {src.relative_to(PROJECT_ROOT)} -> {dst.relative_to(PROJECT_ROOT)}")

    print("Migration done.")

if __name__ == "__main__":
    main()
