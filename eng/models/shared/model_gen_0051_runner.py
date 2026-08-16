"""
eng/models/model_gen_0051_runner.py

Unified model runner: load game-level data (with lines), run league-specific
model registry, write multi-model projection JSON and CSV.

Uses utils.io_helpers:
- load_game_state(league) for input (game-level with odds)
- get_model_runner_output_json_path(league), get_model_runner_output_csv_path(league)

Usage:
  python eng/models/model_gen_0051_runner.py --league nba
  python eng/models/model_gen_0051_runner.py --league ncaam
  python eng/models/model_gen_0051_runner.py --league nfl
  python eng/models/model_gen_0051_runner.py --league ncaaf

Output schema: { "version": "...", "generated_at": "...", "games": [...] }
Matches Streamlit UI expectation for both leagues. NCAAM: each game shell gets
NBA-parallel keys (game_id, home_team/away_team, spread_*_last, total_last,
moneyline_*_last) via utils.ncaam_multimodel_nba_aliases before models run.
Forward-only: reads only game state; writes only runner output. Does not modify model math.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.run_log import set_silent, log_info


# =============================================================================
# SHARED: Model contract and validate
# =============================================================================

REQUIRED_MODEL_KEYS = {
    "model_name",
    "total_projection",
    "total_distance",
    "total_edge",
    "total_pick",
    "home_line_proj",
    "spread_distance",
    "spread_edge",
    "spread_pick",
    "parlay_edge_score",
    "context_flags",
}


def validate_model_contract(result: dict, game_id: str) -> None:
    if not isinstance(result, dict):
        raise ValueError(f"[ModelContractError] Game {game_id}: Model returned non-dict result")
    missing = REQUIRED_MODEL_KEYS - result.keys()
    extra = result.keys() - REQUIRED_MODEL_KEYS
    if missing:
        raise ValueError(f"[ModelContractError] Game {game_id}: Missing keys: {missing}")
    if extra:
        raise ValueError(f"[ModelContractError] Game {game_id}: Unexpected keys: {extra}")
    if not isinstance(result.get("context_flags"), dict):
        raise ValueError(f"[ModelContractError] Game {game_id}: context_flags must be dict")


# =============================================================================
# SHARED: Run models over games (registry and sort key are league-specific)
# =============================================================================

def run_models(games: list[dict], model_registry: list, sort_key) -> list[dict]:
    models = [cls() for cls in model_registry]
    multi_output = []

    for game in sorted(games, key=sort_key):
        model_results = {}
        for model in models:
            try:
                result = model.run(game, model_results)
            except TypeError:
                result = model.run(game)
            game_id = game.get("game_id") or game.get("canonical_game_id") or ""
            validate_model_contract(result, str(game_id))
            model_results[result["model_name"]] = result

        container = dict(game)
        container["models"] = model_results
        multi_output.append(container)

    return multi_output


# =============================================================================
# SHARED: Write output (JSON payload + CSV) via io_helpers paths
# =============================================================================

def write_output(league: str, games_output: list[dict], version: str) -> None:
    from utils.io_helpers import get_model_runner_output_json_path

    path = get_model_runner_output_json_path(league)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "games": games_output,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def write_csv(
    league: str,
    games_output: list[dict],
    game_id_key: str,
    csv_extra_keys: list[str],
    *,
    extra_base_keys: list[str] | None = None,
) -> None:
    """
    Flatten multi-model games to CSV rows. ``extra_base_keys``: additional game keys
    copied into each row (e.g. ``canonical_game_id`` alongside ``game_id`` for NCAAM parity
    with spreadsheets that expect the legacy column name).
    """
    from utils.io_helpers import get_model_runner_output_csv_path

    path = get_model_runner_output_csv_path(league)
    path.parent.mkdir(parents=True, exist_ok=True)
    extra_base_keys = extra_base_keys or []
    rows = []
    for game in games_output:
        row_base = {game_id_key: game.get(game_id_key, "")}
        for ek in extra_base_keys:
            row_base[ek] = game.get(ek, "")
        if "game_date" in csv_extra_keys:
            row_base["game_date"] = game.get("game_date", "")
        for model_name, model in game["models"].items():
            row = dict(row_base)
            row["model_name"] = model_name
            row["total_projection"] = model.get("total_projection")
            row["home_line_proj"] = model.get("home_line_proj")
            row["spread_pick"] = model.get("spread_pick")
            row["total_pick"] = model.get("total_pick")
            row["spread_edge"] = model.get("spread_edge")
            row["total_edge"] = model.get("total_edge")
            row["parlay_edge_score"] = model.get("parlay_edge_score")
            rows.append(row)

    sort_keys = [game_id_key] + (["game_date"] if "game_date" in csv_extra_keys else []) + ["model_name"]
    rows.sort(key=lambda r: tuple(r.get(k, "") for k in sort_keys))

    fieldnames = list(rows[0].keys()) if rows else []
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# =============================================================================
# NBA: Registry, sort key, load from io_helpers
# =============================================================================

def run_nba() -> None:
    from utils.io_helpers import load_game_state, get_model_runner_output_json_path, get_model_runner_output_csv_path

    from eng.models.nba.joel_baseline_model import JoelBaselineModel
    from eng.models.nba.fatigue_plus_model import FatiguePlusModel
    from eng.models.shared.monkey_darts_model import MonkeyDartsModel
    from eng.models.nba.market_pressure_model import MarketPressureModel
    from eng.models.nba.injury_model import InjuryModel
    from eng.models.nba.market_blend_model import MarketBlendModel
    from eng.models.nba.momentum_5game_model import Momentum5GameModel

    MODEL_REGISTRY = [
        JoelBaselineModel,
        FatiguePlusModel,
        InjuryModel,
        MarketPressureModel,
        MarketBlendModel,
        Momentum5GameModel,
        MonkeyDartsModel,
    ]

    games = load_game_state("nba")
    results = run_models(games, MODEL_REGISTRY, sort_key=lambda g: g.get("game_id", ""))
    write_output("nba", results, "MULTI_MODEL_V1")
    write_csv("nba", results, game_id_key="game_id", csv_extra_keys=[])

    json_path = get_model_runner_output_json_path("nba")
    csv_path = get_model_runner_output_csv_path("nba")
    log_info(f"Loaded games:        {len(games)}")
    log_info(f"JSON output:        {json_path}")
    log_info(f"CSV output:         {csv_path}")
    log_info(f"Model registry:     {len(MODEL_REGISTRY)}")


# =============================================================================
# NCAAM: Registry, sort key, load from io_helpers
# =============================================================================

def run_ncaam() -> None:
    from utils.io_helpers import load_game_state, get_model_runner_output_json_path, get_model_runner_output_csv_path

    from configs.leagues.league_ncaam import MODEL_DIR
    from eng.models.ncaam.ncaam_avg_score_model import NCAAMAvgScoreModel
    from eng.models.ncaam.ncaam_momentum5_model import NCAAMMomentum5Model
    from eng.models.ncaam.ncaam_market_pressure_model import NCAAMMarketPressureModel

    MODEL_REGISTRY = [
        NCAAMAvgScoreModel,
        NCAAMMomentum5Model,
        NCAAMMarketPressureModel,
    ]

    games = load_game_state("ncaam")
    total_games = len(games)
    ncaam_dates = [(g.get("game_date") or "").strip()[:10] for g in games if (g.get("game_date") or "").strip()[:10]]
    log_info(f"NCAAM 0051 diagnostic: loaded games={len(games)}, game_date range={min(ncaam_dates) if ncaam_dates else 'N/A'} .. {max(ncaam_dates) if ncaam_dates else 'N/A'}")

    # Merge avg_score features from ncaam_model_input_v1.csv (001/099 output) when present.
    FEATURE_CSV = MODEL_DIR / "ncaam_model_input_v1.csv"
    AVG_KEYS = (
        "home_avg_points_for",
        "home_avg_points_against",
        "away_avg_points_for",
        "away_avg_points_against",
    )
    OPTIONAL_KEYS = ("home_games_in_history", "away_games_in_history")
    LAST5_KEYS = (
        "home_last5_points_for",
        "home_last5_points_against",
        "home_last5_avg_margin",
        "home_last5_win_pct",
        "home_last5_games_in_history",
        "away_last5_points_for",
        "away_last5_points_against",
        "away_last5_avg_margin",
        "away_last5_win_pct",
        "away_last5_games_in_history",
    )
    if FEATURE_CSV.exists():
        with open(FEATURE_CSV, "r", encoding="utf-8", newline="") as f:
            feature_rows = list(csv.DictReader(f))
        feature_by_cid = {}
        for row in feature_rows:
            cid = (row.get("canonical_game_id") or "").strip()
            if cid:
                feature_by_cid[cid] = row
        enriched = 0
        for g in games:
            cid = (g.get("canonical_game_id") or "").strip()
            feat = feature_by_cid.get(cid) if cid else None
            if not feat:
                continue
            for key in AVG_KEYS + OPTIONAL_KEYS + LAST5_KEYS:
                if key not in feat:
                    continue
                val = feat.get(key)
                if val is None or (isinstance(val, str) and (val or "").strip() == ""):
                    continue
                existing = g.get(key)
                if existing is not None and (not isinstance(existing, str) or (existing or "").strip() != ""):
                    continue
                g[key] = val
            if all((g.get(k) or "").strip() != "" for k in AVG_KEYS):
                enriched += 1
        still_missing = total_games - enriched
        log_info(f"NCAAM avg features:   merged from {FEATURE_CSV.name}; enriched={enriched}, still_missing_avg={still_missing}")
    else:
        log_info(f"NCAAM avg features:   no feature table at {FEATURE_CSV.name}; games unchanged")

    from utils.ncaam_multimodel_nba_aliases import apply_nba_parallel_keys_ncaam_games

    apply_nba_parallel_keys_ncaam_games(games)
    log_info("NCAAM NBA-shell aliases: applied (game_id, home_team/away_team, spread_*_last, total_last, moneyline_*_last)")

    sort_key = lambda g: (g.get("game_date", ""), g.get("game_id") or g.get("canonical_game_id", ""))
    results = run_models(games, MODEL_REGISTRY, sort_key=sort_key)
    write_output("ncaam", results, "NCAAM_MULTI_MODEL_V1")
    write_csv(
        "ncaam",
        results,
        game_id_key="game_id",
        csv_extra_keys=["game_date"],
        extra_base_keys=["canonical_game_id"],
    )

    json_path = get_model_runner_output_json_path("ncaam")
    csv_path = get_model_runner_output_csv_path("ncaam")
    log_info(f"Loaded games:        {len(games)}")
    log_info(f"JSON output:        {json_path}")
    log_info(f"CSV output:         {csv_path}")
    log_info(f"Model registry:     {len(MODEL_REGISTRY)}")


def run_football(league: str) -> None:
    from utils.io_helpers import load_game_state, get_model_runner_output_json_path, get_model_runner_output_csv_path

    from eng.models.football.market_models import (
        FootballKeyNumberGuardModel,
        FootballLineMovementModel,
        FootballMarketBlendModel,
        FootballMarketConsensusModel,
        FootballSpreadValueModel,
        FootballTotalValueModel,
    )

    league = (league or "").strip().lower()
    if league not in ("nfl", "ncaaf"):
        raise ValueError(f"Football runner supports nfl/ncaaf only, got {league!r}")

    MODEL_REGISTRY = [
        FootballMarketConsensusModel,
        FootballSpreadValueModel,
        FootballTotalValueModel,
        FootballLineMovementModel,
        FootballKeyNumberGuardModel,
        FootballMarketBlendModel,
    ]

    games = load_game_state(league)
    results = run_models(games, MODEL_REGISTRY, sort_key=lambda g: (g.get("game_date", ""), g.get("game_id", "")))
    write_output(league, results, f"{league.upper()}_FOOTBALL_MULTI_MODEL_V1")
    write_csv(league, results, game_id_key="game_id", csv_extra_keys=["game_date"])

    json_path = get_model_runner_output_json_path(league)
    csv_path = get_model_runner_output_csv_path(league)
    log_info(f"Loaded games:        {len(games)}")
    log_info(f"JSON output:        {json_path}")
    log_info(f"CSV output:         {csv_path}")
    log_info(f"Model registry:     {len(MODEL_REGISTRY)}")


# =============================================================================
# ENTRYPOINT
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Run multi-model projections")
    parser.add_argument("--league", required=True, choices=["nba", "ncaam", "nfl", "ncaaf"])
    parser.add_argument("--silent", action="store_true", help="Only print critical errors")
    args = parser.parse_args()
    set_silent(args.silent)
    if args.league == "nba":
        run_nba()
    elif args.league == "ncaam":
        run_ncaam()
    else:
        run_football(args.league)


if __name__ == "__main__":
    main()
