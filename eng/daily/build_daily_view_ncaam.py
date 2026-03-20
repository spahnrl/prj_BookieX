"""
eng/daily/build_daily_view_ncaam.py

Purpose
-------
Build the NCAA daily view from NCAA multi-model JSON output.

Behavior
--------
- Supports optional CLI date argument:
    python eng/daily/build_daily_view_ncaam.py 2026-03-08
- If no date is passed, selects the earliest upcoming available date
- Includes all games for the selected date, even if no picks exist yet
- Writes dashboard-safe JSON/CSV artifacts
- Preserves NBA dashboard compatibility patterns without changing NBA format
"""

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from configs.leagues.league_ncaam import DAILY_DIR, MODEL_DIR, ensure_ncaam_dirs

from eng.backtest.backtest_grader import grade_spread_bet, grade_total_bet

INPUT_PATH = MODEL_DIR / "ncaam_games_multi_model_v1.json"

SELECTION_AUTHORITY = "ncaam_avg_score_model"
SCHEMA_VERSION = "NCAAM_DAILY_VIEW_V4"
MODEL_VERSION = "ncaam_games_multi_model_v1"


# =====================================================
# READ
# =====================================================

def load_payload() -> dict:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"Missing multi-model JSON file: {INPUT_PATH}")

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)

    # final_game_view_ncaam.json is sometimes emitted as a list of rows.
    if isinstance(payload, list):
        return {"games": payload}

    if not isinstance(payload, dict):
        raise ValueError("Expected JSON payload to be a dict or a list of rows")

    games = payload.get("games", [])
    if not isinstance(games, list):
        raise ValueError("Expected payload['games'] to be a list")

    return payload


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


def safe_num(value, default=0.0):
    parsed = safe_float(value)
    return default if parsed is None else parsed


def safe_text(value, default=""):
    if value is None:
        return default
    return str(value)


def identity_team_name(display_val, base_name_val, team_id_val) -> str:
    for candidate in (
        safe_text(display_val).strip(),
        safe_text(base_name_val).strip(),
    ):
        if candidate:
            return candidate
    tid = safe_text(team_id_val).strip()
    if not tid:
        return ""
    return " ".join(
        part.capitalize() for part in tid.replace("-", "_").split("_") if part
    )


def abs_edge_sort_value(game_row: dict) -> float:
    edge_metrics = game_row.get("edge_metrics", {}) or {}
    spread_edge = safe_float(edge_metrics.get("spread_edge"))
    total_edge = safe_float(edge_metrics.get("total_edge"))

    values = []
    if spread_edge is not None:
        values.append(abs(spread_edge))
    if total_edge is not None:
        values.append(abs(total_edge))

    return max(values) if values else -1.0


def has_usable_signal(model_row: dict) -> bool:
    return any([
        safe_text(model_row.get("spread_pick")).strip() != "",
        safe_text(model_row.get("total_pick")).strip() != "",
        safe_text(model_row.get("home_line_proj")).strip() != "",
        safe_text(model_row.get("total_projection")).strip() != "",
    ])


def get_output_paths(target_date: str):
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    csv_path = DAILY_DIR / f"daily_view_ncaam_{target_date}_v1_{timestamp}.csv"
    # Same path each run: 5 AM and 5 PM runs overwrite this file (fresh content + build_timestamp).
    json_path = DAILY_DIR / f"daily_view_ncaam_{target_date}_v1.json"
    return csv_path, json_path


def compute_confidence_tier(model: dict) -> str:
    spread_edge = safe_float(model.get("spread_edge"))
    total_edge = safe_float(model.get("total_edge"))

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


def compute_confidence_reason(model: dict) -> str:
    spread_pick = safe_text(model.get("spread_pick")).strip()
    total_pick = safe_text(model.get("total_pick")).strip()
    home_line_proj = safe_text(model.get("home_line_proj")).strip()
    total_projection = safe_text(model.get("total_projection")).strip()

    if not spread_pick and not total_pick and not home_line_proj and not total_projection:
        return "No model signal yet"

    return "NCAAM MVP placeholder confidence"


def compute_actionability(model: dict) -> str:
    spread_pick = safe_text(model.get("spread_pick")).strip()
    total_pick = safe_text(model.get("total_pick")).strip()

    if spread_pick or total_pick:
        return "ACTIVE"
    return "NONE"


def build_explanation(game: dict, model: dict) -> str:
    away_team = safe_text(game.get("away_team_display")).strip()
    home_team = safe_text(game.get("home_team_display")).strip()

    spread_home = safe_text(game.get("market_spread_home")).strip()
    spread_away = safe_text(game.get("market_spread_away")).strip()
    total = safe_text(game.get("market_total")).strip()

    proj_margin = safe_text(model.get("home_line_proj")).strip()
    proj_total = safe_text(model.get("total_projection")).strip()
    spread_pick = safe_text(model.get("spread_pick")).strip()
    total_pick = safe_text(model.get("total_pick")).strip()
    spread_edge = safe_text(model.get("spread_edge")).strip()
    total_edge = safe_text(model.get("total_edge")).strip()

    return (
        f"Game: {away_team} @ {home_team}\n"
        f"Authority: {SELECTION_AUTHORITY}\n"
        f"Market: Spread {spread_home} / {spread_away}, Total {total}\n"
        f"Model Projection: Margin {proj_margin}, Total {proj_total}\n"
        f"Spread Pick: {spread_pick} (edge {spread_edge})\n"
        f"Total Pick: {total_pick} (edge {total_edge})"
    )


# =====================================================
# BUILD
# =====================================================

def build_daily_rows(games: list[dict]) -> list[dict]:
    out = []

    for game in games:
        models = game.get("models", {}) or {}
        if SELECTION_AUTHORITY not in models:
            continue

        selected_model = models[SELECTION_AUTHORITY]

        # NCAAM dev rule:
        # include all games for the selected date, even if there is no signal yet.
        confidence_tier = compute_confidence_tier(selected_model)
        confidence_reason = compute_confidence_reason(selected_model)
        actionability = compute_actionability(selected_model)

        # Completed-game S/T results for UI title-line suffix.
        selected_spread_result = ""
        selected_total_result = ""
        selected_spread_margin_abs = None
        selected_total_margin_abs = None

        completed_flag = safe_text(game.get("completed_flag")).strip()
        status_state_raw = safe_text(game.get("status_state")).strip()
        status_state = status_state_raw.lower()
        status_name = safe_text(game.get("status_name")).strip().upper()
        is_final = completed_flag == "1" or status_state == "post" or "FINAL" in status_name
        home_points_passthrough = safe_float(game.get("home_points"))
        away_points_passthrough = safe_float(game.get("away_points"))
        actual_total_passthrough = (
            home_points_passthrough + away_points_passthrough
            if home_points_passthrough is not None and away_points_passthrough is not None
            else None
        )

        if is_final:
            home_points = safe_float(game.get("home_points"))
            away_points = safe_float(game.get("away_points"))

            if home_points is not None and away_points is not None:
                spread_home_line = safe_float(game.get("market_spread_home"))
                if spread_home_line is None:
                    spread_home_line = safe_float(game.get("spread_home_last"))
                if spread_home_line is None:
                    spread_home_line = safe_float(game.get("spread_home"))

                total_line = safe_float(game.get("market_total"))
                if total_line is None:
                    total_line = safe_float(game.get("total_last"))
                if total_line is None:
                    total_line = safe_float(game.get("total"))

                spread_pick = safe_text(selected_model.get("spread_pick")).strip().upper()
                total_pick = safe_text(selected_model.get("total_pick")).strip().upper()

                # NCAAM pick may be a team name while the grading contract expects HOME/AWAY.
                # Final view uses `home_team`/`away_team` (not always *_display), so fall back safely.
                home_team = safe_text(game.get("home_team_display") or game.get("home_team")).strip().upper()
                away_team = safe_text(game.get("away_team_display") or game.get("away_team")).strip().upper()

                if spread_pick in ("HOME", "AWAY"):
                    line_bet = spread_pick
                elif spread_pick == home_team:
                    line_bet = "HOME"
                elif spread_pick == away_team:
                    line_bet = "AWAY"
                else:
                    line_bet = None

                total_bet = total_pick if total_pick in ("OVER", "UNDER", "PUSH") else None

                spread_res = grade_spread_bet(
                    line_bet,
                    spread_home_line,
                    home_points,
                    away_points,
                )
                total_res = grade_total_bet(
                    total_bet,
                    total_line,
                    home_points,
                    away_points,
                )

                selected_spread_result = spread_res or ""
                selected_total_result = total_res or ""

                # Point distance vs. line (mirrors grade_spread_bet / grade_total_bet arithmetic).
                if spread_res is not None and line_bet in ("HOME", "AWAY") and spread_home_line is not None:
                    hi = int(home_points)
                    ai = int(away_points)
                    adjusted = float(hi - ai) + float(spread_home_line)
                    selected_spread_margin_abs = abs(adjusted)
                if total_res is not None and total_bet in ("OVER", "UNDER", "PUSH") and total_line is not None:
                    # Use the same numeric inputs (no truncation) as total grading.
                    actual_total = float(home_points) + float(away_points)
                    selected_total_margin_abs = abs(actual_total - float(total_line))

        projected_margin_home = safe_num(selected_model.get("home_line_proj"), default=0.0)
        projected_total = safe_num(selected_model.get("total_projection"), default=0.0)

        spread_edge = safe_num(selected_model.get("spread_edge"), default=0.0)
        total_edge = safe_num(selected_model.get("total_edge"), default=0.0)
        parlay_edge_score = safe_num(selected_model.get("parlay_edge_score"), default=0.0)

        row = {
            "selection_authority": SELECTION_AUTHORITY,
            "primary_model_source": SELECTION_AUTHORITY,
            "selected_spread_result": selected_spread_result,
            "selected_total_result": selected_total_result,
            "status_state": status_state_raw,
            "home_points": home_points_passthrough,
            "away_points": away_points_passthrough,
            "actual_total": actual_total_passthrough,

            "identity": {
                "game_id": safe_text(game.get("canonical_game_id")).strip(),
                "game_date_local": safe_text(game.get("game_date")).strip(),
                "away_team": identity_team_name(
                    game.get("away_team_display"),
                    game.get("away_team"),
                    game.get("away_team_id"),
                ),
                "home_team": identity_team_name(
                    game.get("home_team_display"),
                    game.get("home_team"),
                    game.get("home_team_id"),
                ),
                "away_team_id": safe_text(game.get("away_team_id")).strip(),
                "home_team_id": safe_text(game.get("home_team_id")).strip(),
                "tip_time_cst": safe_text(game.get("odds_commence_time_cst") or game.get("tip_time_cst") or "").strip(),
                "season_type": safe_text(game.get("season_type")).strip(),
            },

            "market_state": {
                "spread_home_last": safe_num(game.get("market_spread_home") or game.get("spread_home"), default=0.0),
                "spread_away_last": safe_num(game.get("market_spread_away") or game.get("spread_away"), default=0.0),
                "total_last": safe_num(game.get("market_total") or game.get("total"), default=0.0),
                "moneyline_home_last": safe_num(game.get("market_home_moneyline") or game.get("moneyline_home"), default=0.0),
                "moneyline_away_last": safe_num(game.get("market_away_moneyline") or game.get("moneyline_away"), default=0.0),

                "spread_home_consensus": 0.0,
                "spread_away_consensus": 0.0,
                "total_consensus": 0.0,
                "moneyline_home_consensus": 0.0,
                "moneyline_away_consensus": 0.0,

                "spread_home_consensus_all_time": 0.0,
                "spread_away_consensus_all_time": 0.0,
                "total_consensus_all_time": 0.0,
                "moneyline_home_consensus_all_time": 0.0,
                "moneyline_away_consensus_all_time": 0.0,

                "consensus_book_count": 0,
                "all_time_snapshot_count": 0,
                "odds_snapshot_last_utc": safe_text(
                    game.get("odds_snapshot_last_utc") or game.get("odds_snapshot_utc") or ""
                ).strip(),
            },

            "model_output": {
                "projected_margin_home": projected_margin_home,
                "projected_total": projected_total,
                "spread_pick": safe_text(selected_model.get("spread_pick")).strip(),
                "total_pick": safe_text(selected_model.get("total_pick")).strip(),
                "confidence_tier": confidence_tier,
                "cluster_alignment": "NONE",
                "arbitration_cluster": "NONE",
                "confidence_reason": confidence_reason,
                "actionability": actionability,
            },

            "edge_metrics": {
                "spread_edge": spread_edge,
                "total_edge": total_edge,
                "parlay_edge_score": parlay_edge_score,
                "spread_edge_percentile": 0.0,
                "total_edge_percentile": 0.0,
            },

            "arbitration": {
                "spread": {"disagreement_flag": False},
                "total": {"disagreement_flag": False},
            },

            "agent_overrides": {
                "override_pick": None,
                "override_reason": None,
                "override_confidence_delta": None,
            },

            "execution_overlay": {
                "spread_band": "N/A",
                "total_band": "N/A",
                "spread_sweet_spot": False,
                "total_sweet_spot": False,
                "dual_sweet_spot": False,
                "spread_avoid": False,
                "total_avoid": False,
            },

            "calibration_tags": {
                "edge_bucket": "N/A",
                "historical_bucket_win_rate": 0.0,
                "over_under_bias_flag": False,
                "favorite_dog_bias_flag": False,
                "model_regime_normal": True,
            },

            "context_flags": selected_model.get("context_flags", {}) or {},
            "models": models,

            "temporal_integrity": {
                "source_model_artifact": INPUT_PATH.name,
                "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            },

            "game_source_id": safe_text(game.get("game_source_id")).strip(),
            "espn_game_id": safe_text(game.get("espn_game_id")).strip(),
            "game_date": safe_text(game.get("game_date")).strip(),
            "Explanation": build_explanation(game, selected_model),
            "Decision Factors": {},
        }

        if selected_spread_margin_abs is not None:
            row["selected_spread_margin_abs"] = selected_spread_margin_abs
        if selected_total_margin_abs is not None:
            row["selected_total_margin_abs"] = selected_total_margin_abs

        out.append(row)

    out.sort(
        key=lambda r: (
            r.get("identity", {}).get("game_date_local", ""),
            -abs_edge_sort_value(r),
            r.get("identity", {}).get("away_team", ""),
            r.get("identity", {}).get("home_team", ""),
        )
    )
    return out


def build_csv_rows(json_rows: list[dict]) -> list[dict]:
    out = []

    for row in json_rows:
        identity = row.get("identity", {}) or {}
        market = row.get("market_state", {}) or {}
        model_output = row.get("model_output", {}) or {}
        edge = row.get("edge_metrics", {}) or {}

        out.append({
            "selection_authority": row.get("selection_authority", ""),
            "primary_model_source": row.get("primary_model_source", ""),

            "game_id": identity.get("game_id", ""),
            "game_date_local": identity.get("game_date_local", ""),
            "away_team": identity.get("away_team", ""),
            "home_team": identity.get("home_team", ""),
            "away_team_id": identity.get("away_team_id", ""),
            "home_team_id": identity.get("home_team_id", ""),
            "tip_time_cst": identity.get("tip_time_cst", ""),
            "season_type": identity.get("season_type", ""),

            "spread_home_last": market.get("spread_home_last", 0.0),
            "spread_away_last": market.get("spread_away_last", 0.0),
            "total_last": market.get("total_last", 0.0),
            "moneyline_home_last": market.get("moneyline_home_last", 0.0),
            "moneyline_away_last": market.get("moneyline_away_last", 0.0),

            "projected_margin_home": model_output.get("projected_margin_home", 0.0),
            "projected_total": model_output.get("projected_total", 0.0),
            "spread_pick": model_output.get("spread_pick", ""),
            "total_pick": model_output.get("total_pick", ""),
            "confidence_tier": model_output.get("confidence_tier", "IGNORE"),
            "cluster_alignment": model_output.get("cluster_alignment", "NONE"),
            "arbitration_cluster": model_output.get("arbitration_cluster", "NONE"),
            "confidence_reason": model_output.get("confidence_reason", "No model signal yet"),
            "actionability": model_output.get("actionability", "NONE"),

            "spread_edge": edge.get("spread_edge", 0.0),
            "total_edge": edge.get("total_edge", 0.0),
            "parlay_edge_score": edge.get("parlay_edge_score", 0.0),
        })

    return out


# =====================================================
# WRITE
# =====================================================

def write_csv(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "selection_authority",
        "primary_model_source",
        "game_id",
        "game_date_local",
        "away_team",
        "home_team",
        "away_team_id",
        "home_team_id",
        "tip_time_cst",
        "season_type",
        "spread_home_last",
        "spread_away_last",
        "total_last",
        "moneyline_home_last",
        "moneyline_away_last",
        "projected_margin_home",
        "projected_total",
        "spread_pick",
        "total_pick",
        "confidence_tier",
        "cluster_alignment",
        "arbitration_cluster",
        "confidence_reason",
        "actionability",
        "spread_edge",
        "total_edge",
        "parlay_edge_score",
    ]

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        if rows:
            writer.writerows(rows)


def write_json(payload: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


# =====================================================
# MAIN
# =====================================================

def run() -> None:
    ensure_ncaam_dirs()

    input_payload = load_payload()
    games = input_payload.get("games", [])

    # --------------------------------------------------------
    # Determine target date
    # --------------------------------------------------------
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    else:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        available_dates = sorted({
            safe_text(g.get("game_date")).strip()
            for g in games
            if safe_text(g.get("game_date")).strip()
            and safe_text(g.get("game_date")).strip() >= today_str
        })

        if not available_dates:
            print("No upcoming games available.")
            return

        target_date = available_dates[0]

    csv_path, json_path = get_output_paths(target_date)

    target_games = [
        g for g in games
        if safe_text(g.get("game_date")).strip() == target_date
    ]

    json_rows = build_daily_rows(target_games)
    csv_rows = build_csv_rows(json_rows)

    build_ts = datetime.now(timezone.utc).isoformat()
    for row in json_rows:
        ms = row.get("market_state") or {}
        if not (ms.get("odds_snapshot_last_utc") or "").strip():
            row.setdefault("market_state", {})["odds_snapshot_last_utc"] = build_ts

    json_payload = {
        "schema_version": SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "selection_authority": SELECTION_AUTHORITY,
        "date": target_date,
        "build_timestamp_utc": build_ts,
        "games": json_rows,
    }

    if not json_rows:
        print(f"No daily rows found for target date: {target_date}")

    write_csv(csv_rows, csv_path)
    write_json(json_payload, json_path)

    spread_pick_count = sum(
        1 for r in csv_rows if safe_text(r.get("spread_pick")).strip() != ""
    )
    total_pick_count = sum(
        1 for r in csv_rows if safe_text(r.get("total_pick")).strip() != ""
    )
    signal_row_count = sum(
        1 for r in json_rows
        if (
            safe_text((r.get("model_output") or {}).get("spread_pick")).strip() != ""
            or safe_text((r.get("model_output") or {}).get("total_pick")).strip() != ""
        )
    )

    print(f"Loaded games:                {len(games)}")
    print(f"Target date:                 {target_date}")
    print(f"Target-date games:           {len(target_games)}")
    print(f"Selection authority:         {SELECTION_AUTHORITY}")
    print(f"Daily CSV written to:        {csv_path}")
    print(f"Daily JSON written to:       {json_path}")
    print(f"Daily rows:                  {len(csv_rows)}")
    print(f"Rows with spread picks:      {spread_pick_count}")
    print(f"Rows with total picks:       {total_pick_count}")
    print(f"Rows with any picks:         {signal_row_count}")


if __name__ == "__main__":
    run()