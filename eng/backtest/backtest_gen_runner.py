"""
eng/backtest/backtest_gen_runner.py

Unified, league-agnostic backtest runner. Single entry point for NBA and NCAAM:
- Argument-driven: --league (nba | ncaam), default nba.
- Domain isolation: input from league config (NBA: data/nba/view, NCAAM: data/ncaam/model),
  output data/{league}/backtests/backtest_{timestamp}/.
- Uses robust grading from eng.backtest.backtest_grader (NBA); output structure follows
  NCAAM-style metadata wrapper + detail list.
- Preserves @agent_reasoning (and other agent metadata) in backtest output.

Authority: eng/backtest_runner.py (NBA), eng/backtest_runner_ncaam.py (NCAAM).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eng.backtest.backtest_grader import (
    grade_parlay,
    grade_spread_bet,
    grade_total_bet,
)

# -----------------------------------------------------------------------------
# Config: paths and selection authority
# -----------------------------------------------------------------------------

SELECTION_AUTHORITY_BY_LEAGUE = {
    "nba": "Joel_Baseline_v1",
    "ncaam": "ncaam_avg_score_model",
}

KELLY_PAYOUT_RATIO = 100 / 110


def get_input_path(league: str) -> Path:
    """Multi-model JSON path from league config (NBA: view/; NCAAM: model/)."""
    from utils.io_helpers import get_model_runner_output_json_path
    league = (league or "").strip().lower()
    if league not in ("nba", "ncaam"):
        raise ValueError("league must be 'nba' or 'ncaam'")
    return get_model_runner_output_json_path(league)


def get_output_root(league: str) -> Path:
    """Output root: data/{league}/backtests/."""
    league = (league or "").strip().lower()
    if league not in ("nba", "ncaam"):
        raise ValueError("league must be 'nba' or 'ncaam'")
    return PROJECT_ROOT / "data" / league / "backtests"


# -----------------------------------------------------------------------------
# IO: load multi-model payload
# -----------------------------------------------------------------------------


def load_games(league: str) -> list[dict]:
    """
    Load games from league multi-model JSON (source: io_helpers.get_model_runner_output_json_path).
    Payload must be a dict with "games" key (multi-model schema).
    """
    path = get_input_path(league)
    if not path.exists():
        raise FileNotFoundError(f"Multi-model input not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "games" in data:
        games = data.get("games", [])
    elif isinstance(data, list):
        games = data
    else:
        raise ValueError("Input JSON must be a dict with 'games' key or a list of games")

    if not isinstance(games, list):
        raise ValueError("payload['games'] must be a list")
    return games


# -----------------------------------------------------------------------------
# Helpers: normalize scores/lines and final-game check
# -----------------------------------------------------------------------------


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_scores(game: dict) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Return (home_score, away_score, spread_home, market_total)."""
    home = _safe_float(
        game.get("home_score") or game.get("home_points")
        or game.get("box_home_score") or game.get("schedule_home_score")
    )
    away = _safe_float(
        game.get("away_score") or game.get("away_points")
        or game.get("box_away_score") or game.get("schedule_away_score")
    )
    spread = _safe_float(
        game.get("market_spread_home") or game.get("spread_home") or game.get("spread_home_last")
    )
    total = _safe_float(game.get("market_total") or game.get("total") or game.get("total_last"))
    return home, away, spread, total


def _is_final_game(game: dict) -> bool:
    completed = str(game.get("completed_flag", "")).strip()
    status_state = str(game.get("status_state", "")).strip().lower()
    status_name = str(game.get("status_name", "")).strip().upper()
    status = str(game.get("status", "")).strip().lower()
    if completed == "1" or status_state == "post" or "FINAL" in status_name:
        return True
    if status in ("final", "completed", "finalized", "post"):
        return True
    home, away, _, _ = _normalize_scores(game)
    return home is not None and away is not None


def _spread_pick_to_line_bet(
    spread_pick: str,
    home_team_display: str,
    away_team_display: str,
) -> str:
    """
    Normalize spread pick to HOME | AWAY for backtest_grader.
    NBA uses HOME/AWAY; NCAAM uses team display name.
    """
    if not spread_pick:
        return ""
    pick = (spread_pick or "").strip().upper()
    if pick in ("HOME", "AWAY"):
        return pick
    home_upper = (home_team_display or "").strip().upper()
    away_upper = (away_team_display or "").strip().upper()
    if home_upper and pick == home_upper:
        return "HOME"
    if away_upper and pick == away_upper:
        return "AWAY"
    return pick  # grader will reject invalid; caller can pass through


# -----------------------------------------------------------------------------
# BacktestEngine: generic grading regardless of sport (DRY)
# -----------------------------------------------------------------------------


class BacktestEngine:
    """
    Generic backtest engine: grades spread/total/parlay using eng.backtest.backtest_grader
    (NBA robust logic). Works with both NBA (HOME/AWAY) and NCAAM (team name)
    by normalizing spread pick to line_bet before grading.
    """

    def __init__(self, league: str):
        self.league = (league or "").strip().lower()
        if self.league not in ("nba", "ncaam"):
            raise ValueError("league must be 'nba' or 'ncaam'")
        self.selection_authority = SELECTION_AUTHORITY_BY_LEAGUE[self.league]

    def grade_game(
        self,
        game: dict,
        home_score: Optional[float],
        away_score: Optional[float],
        spread_home: Optional[float],
        market_total: Optional[float],
    ) -> dict[str, Any]:
        """
        Grade a single game's models. Returns dict with model_results keyed by
        model name; each value has spread_result, total_result, parlay_result, etc.
        Uses backtest_grader (NBA logic) with spread pick normalized to HOME/AWAY.
        """
        home_team = (game.get("home_team_display") or game.get("home_team") or "").strip()
        away_team = (game.get("away_team_display") or game.get("away_team") or "").strip()
        models = game.get("models") or {}
        model_outcomes = {}

        for model_name, model in models.items():
            spread_pick_raw = (model.get("spread_pick") or model.get("Line Bet") or "").strip()
            total_pick = (model.get("total_pick") or model.get("Total Bet") or "").strip()
            line_bet = _spread_pick_to_line_bet(spread_pick_raw, home_team, away_team)

            line_bet_for_grader = (line_bet if line_bet in ("HOME", "AWAY") else None) or None
            spread_result = grade_spread_bet(
                line_bet_for_grader,
                spread_home,
                int(home_score) if home_score is not None else None,
                int(away_score) if away_score is not None else None,
            )
            total_result = grade_total_bet(
                total_pick or None,
                market_total,
                int(home_score) if home_score is not None else None,
                int(away_score) if away_score is not None else None,
            )
            parlay_result = grade_parlay(spread_result, total_result)

            model_outcomes[model_name] = {
                "spread_pick": spread_pick_raw,
                "spread_result": spread_result or "",
                "total_pick": total_pick,
                "total_result": total_result or "",
                "parlay_result": parlay_result or "",
                "spread_edge": model.get("spread_edge") or model.get("Spread Edge"),
                "total_edge": model.get("total_edge") or model.get("Total Edge"),
                "parlay_edge_score": model.get("parlay_edge_score") or model.get("Parlay Edge Score"),
                "home_line_proj": model.get("home_line_proj") or model.get("Home Line Projection"),
                "total_projection": model.get("total_projection") or model.get("Total Projection"),
            }

        return {"model_results": model_outcomes}


# -----------------------------------------------------------------------------
# Build backtest rows and summary (NCAAM-style metadata + detail list)
# -----------------------------------------------------------------------------


def build_backtest_rows(
    games: list[dict],
    league: str,
    engine: BacktestEngine,
) -> tuple[list[dict], list[dict]]:
    """Produce list of graded game rows and list of skipped entries."""
    backtest_rows = []
    skipped = []
    authority = engine.selection_authority

    for game in games:
        gid = (game.get("canonical_game_id") or game.get("game_id") or "").strip()
        home_score, away_score, spread_home, market_total = _normalize_scores(game)

        if not _is_final_game(game):
            skipped.append({"game_id": gid, "reason": "Game not final"})
            continue
        if home_score is None or away_score is None:
            skipped.append({"game_id": gid, "reason": "Final scores missing"})
            continue
        if home_score == 0 and away_score == 0:
            skipped.append({"game_id": gid, "reason": "Zero-zero placeholder"})
            continue
        if spread_home is None and market_total is None:
            skipped.append({"game_id": gid, "reason": "Market lines missing"})
            continue

        grading = engine.grade_game(game, home_score, away_score, spread_home, market_total)
        model_outcomes = grading["model_results"]

        actual_margin_home = home_score - away_score
        actual_total = home_score + away_score
        authority_result = model_outcomes.get(authority, {})

        row = dict(game)
        row["selection_authority"] = authority
        row["actual_margin_home"] = round(actual_margin_home, 4)
        row["actual_total"] = round(actual_total, 4)
        row["model_results"] = model_outcomes
        row["selected_spread_pick"] = authority_result.get("spread_pick", "")
        row["selected_total_pick"] = authority_result.get("total_pick", "")
        row["selected_spread_result"] = authority_result.get("spread_result", "")
        row["selected_total_result"] = authority_result.get("total_result", "")
        row["selected_parlay_result"] = authority_result.get("parlay_result", "")
        row["selected_spread_edge"] = authority_result.get("spread_edge")
        row["selected_total_edge"] = authority_result.get("total_edge")
        row["selected_home_line_proj"] = authority_result.get("home_line_proj", "")
        row["selected_total_projection"] = authority_result.get("total_projection", "")

        # Preserve agentic metadata for analysis (why models won or lost).
        if "agent_reasoning" in game:
            row["agent_reasoning"] = game["agent_reasoning"]
        if "@agent_reasoning" in game:
            row["@agent_reasoning"] = game["@agent_reasoning"]

        backtest_rows.append(row)

    return backtest_rows, skipped


def build_summary(
    backtest_rows: list[dict],
    skipped: list[dict],
    league: str,
    selection_authority: str,
) -> dict:
    """
    NCAAM-style metadata: schema_version, generated_at_utc, graded_game_count,
    skipped_game_count, authority_summary, model_summary, skipped_games.
    Plus overall ROI-style metrics for dashboard alignment.
    """
    model_summary = defaultdict(lambda: {
        "spread_win": 0, "spread_loss": 0, "spread_push": 0,
        "total_win": 0, "total_loss": 0, "total_push": 0,
        "parlay_win": 0, "parlay_loss": 0, "parlay_push": 0,
    })

    for row in backtest_rows:
        for model_name, result in (row.get("model_results") or {}).items():
            bucket = model_summary[model_name]
            for key, res_key in (
                ("spread", "spread_result"),
                ("total", "total_result"),
                ("parlay", "parlay_result"),
            ):
                res = result.get(res_key, "")
                if res == "WIN":
                    bucket[f"{key}_win"] += 1
                elif res == "LOSS":
                    bucket[f"{key}_loss"] += 1
                elif res == "PUSH":
                    bucket[f"{key}_push"] += 1

    for bucket in model_summary.values():
        sd = bucket["spread_win"] + bucket["spread_loss"]
        td = bucket["total_win"] + bucket["total_loss"]
        pd = bucket["parlay_win"] + bucket["parlay_loss"]
        bucket["spread_win_rate_ex_push"] = round(bucket["spread_win"] / sd, 4) if sd else None
        bucket["total_win_rate_ex_push"] = round(bucket["total_win"] / td, 4) if td else None
        bucket["parlay_win_rate_ex_push"] = round(bucket["parlay_win"] / pd, 4) if pd else None

    authority_subset = dict(model_summary.get(selection_authority, {}))

    return {
        "schema_version": "BACKTEST_GEN_V1",
        "league": league,
        "selection_authority": selection_authority,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "graded_game_count": len(backtest_rows),
        "skipped_game_count": len(skipped),
        "authority_summary": authority_subset,
        "model_summary": dict(model_summary),
        "skipped_games": skipped,
    }


# Keys we explicitly map in CSV (game- or result-derived). Nested keys excluded from passthrough.
_CSV_SKIP_KEYS = frozenset({"model_results", "models"})


def _scalar_value_for_csv(v: Any) -> Any:
    """Use value as-is for CSV; None -> empty string for consistent columns."""
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return None  # caller should skip
    return v


def build_csv_rows(
    backtest_rows: list[dict],
    selection_authority: str,
    *,
    league: str = "",
    build_timestamp: str = "",
) -> list[dict]:
    """
    Flatten to one row per game per model for CSV. Includes league and build_timestamp.
    All top-level scalar/string/number/bool fields from backtest JSON rows are included
    via passthrough; nested dict/list (e.g. model_results, models) are excluded.
    """
    # Fixed column order (identity/audit then game/result fields)
    fixed_order = [
        "selection_authority", "league", "build_timestamp",
        "canonical_game_id", "game_source_id", "espn_game_id", "game_date",
        "away_team_display", "home_team_display", "away_team", "home_team",
        "home_score", "away_score", "actual_margin_home", "actual_total",
        "market_spread_home", "market_total",
        "model_name", "home_line_proj", "total_projection",
        "spread_edge", "total_edge", "parlay_edge_score",
        "spread_pick", "spread_result", "total_pick", "total_result", "parlay_result",
    ]
    fixed_set = set(fixed_order)

    # Collect any extra top-level scalar keys from backtest rows (passthrough for human review)
    extra_keys: set[str] = set()
    for game in backtest_rows:
        for k, v in game.items():
            if k in _CSV_SKIP_KEYS or k in fixed_set:
                continue
            if isinstance(v, (dict, list)):
                continue
            extra_keys.add(k)
    extra_order = sorted(extra_keys)

    rows = []
    for game in backtest_rows:
        for model_name, result in (game.get("model_results") or {}).items():
            row = {
                "selection_authority": game.get("selection_authority", ""),
                "league": league,
                "build_timestamp": build_timestamp,
                "canonical_game_id": game.get("canonical_game_id") or game.get("game_id", ""),
                "game_source_id": game.get("game_source_id", ""),
                "espn_game_id": game.get("espn_game_id", ""),
                "game_date": game.get("game_date", ""),
                "away_team_display": game.get("away_team_display", ""),
                "home_team_display": game.get("home_team_display", ""),
                "away_team": game.get("away_team", ""),
                "home_team": game.get("home_team", ""),
                "home_score": game.get("home_score") or game.get("home_points", ""),
                "away_score": game.get("away_score") or game.get("away_points", ""),
                "actual_margin_home": game.get("actual_margin_home", ""),
                "actual_total": game.get("actual_total", ""),
                "market_spread_home": game.get("market_spread_home", ""),
                "market_total": game.get("market_total", ""),
                "model_name": model_name,
                "home_line_proj": result.get("home_line_proj", ""),
                "total_projection": result.get("total_projection", ""),
                "spread_edge": result.get("spread_edge", ""),
                "total_edge": result.get("total_edge", ""),
                "parlay_edge_score": result.get("parlay_edge_score", ""),
                "spread_pick": result.get("spread_pick", ""),
                "spread_result": result.get("spread_result", ""),
                "total_pick": result.get("total_pick", ""),
                "total_result": result.get("total_result", ""),
                "parlay_result": result.get("parlay_result", ""),
            }
            for k in extra_order:
                v = game.get(k)
                row[k] = _scalar_value_for_csv(v) if not isinstance(v, (dict, list)) else ""
            rows.append(row)
    rows.sort(key=lambda r: (r["game_date"], r["canonical_game_id"], r["model_name"]))
    return rows


# -----------------------------------------------------------------------------
# Write outputs (domain-isolated path)
# -----------------------------------------------------------------------------


def write_outputs(
    out_dir: Path,
    backtest_rows: list[dict],
    summary: dict,
    csv_rows: list[dict],
    *,
    league: str = "",
    run_ts: str = "",
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "backtest_games.json", "w", encoding="utf-8") as f:
        json.dump(backtest_rows, f, indent=2)
    with open(out_dir / "backtest_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    if csv_rows:
        fieldnames = list(csv_rows[0].keys())
        csv_name = f"backtest_games_{league}_{run_ts}.csv" if (league and run_ts) else "backtest_games.csv"
        with open(out_dir / csv_name, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)


# -----------------------------------------------------------------------------
# Main CLI and run
# -----------------------------------------------------------------------------


def run(league: str) -> Path:
    """
    Load multi-model JSON, grade with BacktestEngine, write to
    data/{league}/backtests/backtest_{timestamp}/. Returns output directory.
    """
    league = (league or "nba").strip().lower()
    if league not in ("nba", "ncaam"):
        raise ValueError("--league must be nba or ncaam")

    engine = BacktestEngine(league)
    games = load_games(league)
    backtest_rows, skipped = build_backtest_rows(games, league, engine)
    summary = build_summary(backtest_rows, skipped, league, engine.selection_authority)
    csv_rows = build_csv_rows(
        backtest_rows,
        engine.selection_authority,
        league=league,
        build_timestamp=summary["generated_at_utc"],
    )

    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_root = get_output_root(league)
    out_dir = out_root / f"backtest_{run_ts}"
    csv_filename = f"backtest_games_{league}_{run_ts}.csv"
    write_outputs(out_dir, backtest_rows, summary, csv_rows, league=league, run_ts=run_ts)

    print(f"League:              {league}")
    print(f"Selection authority: {engine.selection_authority}")
    print(f"Input:               {get_input_path(league)}")
    print(f"Output dir:          {out_dir}")
    print(f"Graded games:        {len(backtest_rows)}")
    print(f"Skipped games:       {len(skipped)}")
    print(f"Detail JSON:         {out_dir / 'backtest_games.json'}")
    print(f"Summary JSON:        {out_dir / 'backtest_summary.json'}")
    print(f"Detail CSV:          {out_dir / csv_filename}")
    print(f"Detail CSV rows:     {len(csv_rows)}")

    return out_dir


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Unified backtest runner (NBA / NCAAM). Input: data/{league}/model multi-model JSON; output: data/{league}/backtests/backtest_{timestamp}/.",
    )
    p.add_argument(
        "--league",
        choices=["nba", "ncaam"],
        default="nba",
        help="League to backtest (default: nba)",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    run(args.league)


if __name__ == "__main__":
    main()
