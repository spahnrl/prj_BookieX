"""
eng/models/model_0052_add_model_ncaam.py

Purpose
-------
Finalize NCAA multi-model output into a UI-facing final game view artifact.

Design goals
------------
- Read NCAA multi-model JSON output
- Flatten the selected authority model into top-level fields
- Preserve all model outputs under `models`
- Write final JSON and CSV artifacts for downstream UI use
- Keep NCAA structurally closer to NBA while staying MVP-safe

Outputs
-------
data/ncaam/view/final_game_view_ncaam.json
data/ncaam/view/final_game_view_ncaam.csv
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from configs.leagues.league_ncaam import MODEL_DIR, ensure_ncaam_dirs

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUT_PATH = MODEL_DIR / "ncaam_games_multi_model_v1.json"
OUTPUT_JSON = PROJECT_ROOT / "data" / "ncaam" / "view" / "final_game_view_ncaam.json"
OUTPUT_JSON_ACTIVE = PROJECT_ROOT / "data" / "ncaam" / "view" / "final_game_view_ncaam_active.json"
OUTPUT_CSV = PROJECT_ROOT / "data" / "ncaam" / "view" / "final_game_view_ncaam.csv"

SELECTION_AUTHORITY = "ncaam_avg_score_model"


# =====================================================
# READ / WRITE
# =====================================================

def load_payload() -> dict:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"Missing multi-model JSON file: {INPUT_PATH}")

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        raise ValueError("Expected NCAA multi-model payload to be a dict")

    games = payload.get("games", [])
    if not isinstance(games, list):
        raise ValueError("Expected payload['games'] to be a list")

    return payload


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        print("No rows to write to CSV.")
        return

    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# =====================================================
# HELPERS
# =====================================================

def safe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _s(v):
    """Safe string for output: str(val).strip() if not None else \"\". Handles int/float."""
    if v is None:
        return ""
    return str(v).strip()


def make_explanation(game: dict, selected_model: dict) -> str:
    away_team = _s(game.get("away_team_display"))
    home_team = _s(game.get("home_team_display"))

    market_spread_home = _s(game.get("market_spread_home"))
    market_total = _s(game.get("market_total"))

    home_line_proj = _s(selected_model.get("home_line_proj"))
    total_projection = _s(selected_model.get("total_projection"))

    spread_pick = _s(selected_model.get("spread_pick"))
    total_pick = _s(selected_model.get("total_pick"))

    spread_edge = _s(selected_model.get("spread_edge"))
    total_edge = _s(selected_model.get("total_edge"))

    return (
        f"Game: {away_team} @ {home_team}\n"
        f"Authority: {SELECTION_AUTHORITY}\n"
        f"Market: Spread {market_spread_home}, Total {market_total}\n"
        f"Model Projection: Margin {home_line_proj}, Total {total_projection}\n"
        f"Spread Pick: {spread_pick} (edge {spread_edge})\n"
        f"Total Pick: {total_pick} (edge {total_edge})"
    )


def compute_actionability(selected_model: dict) -> str:
    spread_pick = _s(selected_model.get("spread_pick"))
    total_pick = _s(selected_model.get("total_pick"))

    if spread_pick or total_pick:
        return "ACTIVE"
    return "NONE"


def compute_confidence_tier(selected_model: dict) -> str:
    spread_edge = safe_float(selected_model.get("spread_edge"))
    total_edge = safe_float(selected_model.get("total_edge"))

    candidates = []
    if spread_edge is not None:
        candidates.append(abs(spread_edge))
    if total_edge is not None:
        candidates.append(abs(total_edge))

    if not candidates:
        return "IGNORE"

    best = max(candidates)

    if best >= 10:
        return "HIGH"
    if best >= 5:
        return "MEDIUM"
    if best >= 2:
        return "LOW"
    return "IGNORE"


def compute_confidence_reason(selected_model: dict) -> str:
    spread_pick = _s(selected_model.get("spread_pick"))
    total_pick = _s(selected_model.get("total_pick"))

    if not spread_pick and not total_pick:
        return "No model signal"

    return "NCAAM MVP placeholder confidence"

def build_active_rows(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _s(r.get("actionability")) != "NONE"
    ]

# =====================================================
# BUILD
# =====================================================

def build_final_rows(games: list[dict]) -> list[dict]:
    out = []

    for game in games:
        models = game.get("models", {}) or {}
        selected_model = models.get(SELECTION_AUTHORITY, {}) or {}

        row = {
            "game_id": _s(game.get("canonical_game_id")),
            "game_source_id": _s(game.get("game_source_id")),
            "espn_game_id": _s(game.get("espn_game_id")),
            "game_date": _s(game.get("game_date")),

            "away_team": _s(game.get("away_team_display")),
            "home_team": _s(game.get("home_team_display")),
            "away_team_id": _s(game.get("away_team_id")),
            "home_team_id": _s(game.get("home_team_id")),

            "away_score": _s(game.get("away_score")),
            "home_score": _s(game.get("home_score")),

            "spread_home": _s(game.get("market_spread_home")),
            "spread_away": _s(game.get("market_spread_away")),
            "total": _s(game.get("market_total")),
            "moneyline_home": _s(game.get("market_home_moneyline")),
            "moneyline_away": _s(game.get("market_away_moneyline")),

            "selection_authority": SELECTION_AUTHORITY,
            "primary_model_source": SELECTION_AUTHORITY,

            "Home Line Projection": _s(selected_model.get("home_line_proj")),
            "Total Projection": _s(selected_model.get("total_projection")),
            "Spread Edge": _s(selected_model.get("spread_edge")),
            "Total Edge": _s(selected_model.get("total_edge")),
            "Parlay Edge Score": _s(selected_model.get("parlay_edge_score")),

            "Line Bet": _s(selected_model.get("spread_pick")),
            "Total Bet": _s(selected_model.get("total_pick")),

            "Decision Factors": {},
            "Explanation": make_explanation(game, selected_model),

            "confidence_tier": compute_confidence_tier(selected_model),
            "confidence_reason": compute_confidence_reason(selected_model),
            "actionability": compute_actionability(selected_model),

            "arbitration": {"spread": None, "total": None},
            "arbitration_cluster": "NONE",
            "cluster_alignment": "NONE",
            "disagreement_flag": False,

            "models": models,

            "status_name": _s(game.get("status_name")),
            "status_state": _s(game.get("status_state")),
            "completed_flag": _s(game.get("completed_flag")),
            "venue_name": _s(game.get("venue_name")),
            "season": _s(game.get("season")),
            "season_type": _s(game.get("season_type")),

            "line_join_status": _s(game.get("line_join_status")),
            "bookmaker_key": _s(game.get("bookmaker_key")),
            "bookmaker_title": _s(game.get("bookmaker_title")),
        }

        out.append(row)

    out.sort(key=lambda r: (r.get("game_date", ""), r.get("game_id", "")))
    return out


def build_csv_rows(rows: list[dict]) -> list[dict]:
    out = []

    for r in rows:
        out.append({
            "game_id": r.get("game_id", ""),
            "game_source_id": r.get("game_source_id", ""),
            "espn_game_id": r.get("espn_game_id", ""),
            "game_date": r.get("game_date", ""),

            "away_team": r.get("away_team", ""),
            "home_team": r.get("home_team", ""),
            "away_team_id": r.get("away_team_id", ""),
            "home_team_id": r.get("home_team_id", ""),

            "spread_home": r.get("spread_home", ""),
            "spread_away": r.get("spread_away", ""),
            "total": r.get("total", ""),
            "moneyline_home": r.get("moneyline_home", ""),
            "moneyline_away": r.get("moneyline_away", ""),

            "selection_authority": r.get("selection_authority", ""),
            "primary_model_source": r.get("primary_model_source", ""),

            "Home Line Projection": r.get("Home Line Projection", ""),
            "Total Projection": r.get("Total Projection", ""),
            "Spread Edge": r.get("Spread Edge", ""),
            "Total Edge": r.get("Total Edge", ""),
            "Parlay Edge Score": r.get("Parlay Edge Score", ""),

            "Line Bet": r.get("Line Bet", ""),
            "Total Bet": r.get("Total Bet", ""),

            "confidence_tier": r.get("confidence_tier", ""),
            "confidence_reason": r.get("confidence_reason", ""),
            "actionability": r.get("actionability", ""),

            "status_name": r.get("status_name", ""),
            "status_state": r.get("status_state", ""),
            "completed_flag": r.get("completed_flag", ""),
            "line_join_status": r.get("line_join_status", ""),
            "bookmaker_key": r.get("bookmaker_key", ""),
            "bookmaker_title": r.get("bookmaker_title", ""),
        })

    return out


# =====================================================
# MAIN
# =====================================================

def run() -> None:
    ensure_ncaam_dirs()

    payload = load_payload()
    games = payload.get("games", [])

    final_rows = build_final_rows(games)
    active_rows = build_active_rows(final_rows)
    csv_rows = build_csv_rows(final_rows)

    # Write NCAA final view as root lists for closer NBA parity
    write_json(OUTPUT_JSON, final_rows)
    write_json(OUTPUT_JSON_ACTIVE, active_rows)
    write_csv(OUTPUT_CSV, csv_rows)

    actionability_count = sum(1 for r in final_rows if (r.get("actionability") or "") != "NONE")
    signal_count = sum(
        1 for r in final_rows
        if _s(r.get("Line Bet")) != "" or _s(r.get("Total Bet")) != ""
    )

    print(f"Loaded games:                {len(games)}")
    print(f"Selection authority:         {SELECTION_AUTHORITY}")
    print(f"Final JSON written to:       {OUTPUT_JSON}")
    print(f"Active JSON written to:      {OUTPUT_JSON_ACTIVE}")
    print(f"Final CSV written to:        {OUTPUT_CSV}")
    print(f"Final rows:                  {len(final_rows)}")
    print(f"Active rows:                 {len(active_rows)}")
    print(f"Rows with signals:           {signal_count}")
    print(f"Rows actionability != NONE:  {actionability_count}")

if __name__ == "__main__":
    run()