"""
build_execution_overlay.py — NBA-only.

Invoked by: 000_RUN_ALL_NBA.py (EXECUTION step).

Purpose:
Annotate final_game_view.json with execution overlay flags.

Rules:
- No model recomputation.
- No confidence modification.
- Authority-aligned evaluation only.
- Deterministic.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.io_helpers import get_final_view_json_path

# ------------------------------------------------------------
# CONFIG (NBA final view - domain isolation: data/nba/view)
# ------------------------------------------------------------

MODEL_ARTIFACT_PATH = get_final_view_json_path("nba")


# ------------------------------------------------------------
# UTILITIES
# ------------------------------------------------------------

def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload):
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def determine_band(edge_value):
    abs_edge = abs(edge_value)

    if abs_edge < 1:
        return "0-1"
    elif abs_edge < 2:
        return "1-2"
    elif abs_edge < 4:
        return "2-4"
    elif abs_edge < 6:
        return "4-6"
    elif abs_edge < 8:
        return "6-8"
    else:
        return "8+"


# ------------------------------------------------------------
# CORE OVERLAY LOGIC
# ------------------------------------------------------------

def compute_overlay_for_game(game):

    authority = game.get("selection_authority")
    models = game.get("models") or {}

    if not authority or authority not in models:
        return None  # cannot evaluate

    model_blob = models[authority]

    spread_edge = model_blob.get("spread_edge")
    total_edge = model_blob.get("total_edge")

    if spread_edge is None or total_edge is None:
        return None

    spread_home = game.get("spread_home")
    vegas_total = game.get("total")

    if spread_home is None or vegas_total is None:
        return None

    abs_spread_edge = abs(spread_edge)
    abs_total_edge = abs(total_edge)
    abs_spread = abs(spread_home)

    # ------------------------------------------------------------
    # SWEET SPOT RULES
    # ------------------------------------------------------------

    spread_sweet_spot = (
        1 <= abs_spread_edge <= 4
        and abs_spread < 12
    )

    total_sweet_spot = (
        1 <= abs_total_edge <= 4
        and 225 <= vegas_total <= 242
        and abs_spread < 12
    )

    dual_sweet_spot = (
        spread_sweet_spot
        and total_sweet_spot
        and abs_spread < 10
    )

    # ------------------------------------------------------------
    # AVOID RULES
    # ------------------------------------------------------------

    spread_avoid = (
        abs_spread_edge > 6
        or abs_spread >= 12
    )

    total_avoid = (
        abs_total_edge > 8
        or vegas_total < 225
    )

    return {
        "spread_band": determine_band(spread_edge),
        "total_band": determine_band(total_edge),
        "spread_sweet_spot": spread_sweet_spot,
        "total_sweet_spot": total_sweet_spot,
        "dual_sweet_spot": dual_sweet_spot,
        "spread_avoid": spread_avoid,
        "total_avoid": total_avoid,
    }


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def build_execution_overlay():

    data = load_json(MODEL_ARTIFACT_PATH)

    if isinstance(data, dict) and "games" in data:
        games = data["games"]
    else:
        games = data

    updated_count = 0

    for g in games:

        overlay = compute_overlay_for_game(g)

        if overlay:
            g["execution_overlay"] = overlay
            updated_count += 1
        else:
            g["execution_overlay"] = None

    write_json(MODEL_ARTIFACT_PATH, data)

    print("Execution overlay applied.")
    print(f"Games annotated: {updated_count}")


if __name__ == "__main__":
    build_execution_overlay()