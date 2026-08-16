from __future__ import annotations

from build_football_pocket_roi_seed import build_seed_artifacts


def main() -> None:
    result = build_seed_artifacts("ncaaf")
    print("[ncaaf_pocket_seed] OK")
    print(f"graded_pick_count={result['graded_pick_count']}")
    print(f"ranked_count={result['ranked_count']}")
    print(f"best_game_count={result['best_game_count']}")
    print(f"overall_roi={result['overall_roi']}")
    for key, path in result["outputs"].items():
        print(f"{key}={path}")


if __name__ == "__main__":
    main()
