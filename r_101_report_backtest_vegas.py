"""
r_101_report_backtest_vegas.py — NBA-only.

Invoked by: 000_RUN_ALL_NBA.py (EVALUATION step).

Purpose: Report backtest results vs Vegas (spread/total) from latest NBA backtest;
writes data/nba/view/report_backtest_vegas.csv.
"""
import json
import pandas as pd
from pathlib import Path

from eng.agent_stub import agent_stub_overrides
from configs.leagues.league_nba import VIEW_DIR

BACKTEST_ROOT = Path("../../data/nba/backtests")
OUT_CSV = VIEW_DIR / "report_backtest_vegas.csv"

def get_latest_json():
    subdirs = [d for d in BACKTEST_ROOT.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
    if not subdirs:
        raise FileNotFoundError(f"No backtest_* directories in {BACKTEST_ROOT}")
    latest = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest / "backtest_games.json"

json_path = get_latest_json()
print(f"Using JSON file: {json_path}")

with open(json_path, "r", encoding="utf-8") as f:
    games = json.load(f)

rows = []

for game in games:
    home_final = game.get("home_score_final") or game.get("home_points")
    away_final = game.get("away_score_final") or game.get("away_points")
    if home_final is None or away_final is None:
        continue
    try:
        home_final = float(home_final)
        away_final = float(away_final)
    except (TypeError, ValueError):
        continue
    margin = home_final - away_final
    actual_total = home_final + away_final

    for model_name, result_block in game.get("model_results", {}).items():

        model_block = game.get("models", {}).get(model_name, {})

        rows.append({
            "nba_game_day_local": game.get("nba_game_day_local", ""),
            "game_id": game.get("game_id", ""),
            "away_team": game.get("away_team", ""),
            "home_team": game.get("home_team", ""),
            "away_score": away_final,
            "home_score": home_final,
            "margin_home_minus_away": margin,
            "actual_total": actual_total,

            # MARKET (Vegas)
            "MARKET": ">>>",
            "vegas_spread_home": game.get("spread_home") or game.get("spread_home_last") or game.get("market_spread_home"),
            "vegas_total": game.get("total") or game.get("total_last") or game.get("market_total"),

            # MODEL IDENTITY
            "MODELS": ">>>",
            "model": model_name,

            # MODEL PROJECTIONS
            "model_projected_margin": model_block.get("home_line_proj"),
            "model_spread_edge": model_block.get("spread_edge"),
            "model_projected_total": model_block.get("total_projection"),
            "model_total_edge": model_block.get("total_edge"),

            # MODEL PICKS
            "model_spread_pick": result_block.get("spread_pick"),
            "model_total_pick": result_block.get("total_pick"),

            # MODEL RESULTS
            "model_spread_result": result_block.get("spread_result"),
            "model_total_result": result_block.get("total_result"),
            "model_parlay_result": result_block.get("parlay_result"),

            # EXECUTED (Selection Authority)
            "AUTHORITY": ">>>",
            "authority_spread_pick": game.get("Line Bet") or game.get("selected_spread_pick"),
            "authority_total_pick": game.get("Total Bet") or game.get("selected_total_pick"),
            "authority_spread_result": game.get("spread_result") or game.get("selected_spread_result"),
            "authority_total_result": game.get("total_result") or game.get("selected_total_result"),
            "selection_authority": game.get("selection_authority"),
            "is_authority": model_name == game.get("selection_authority"),

            "MODEL_FATIGUE":">>>",
            "home_rest_bucket": game.get("home_rest_bucket"),
            "away_rest_bucket": game.get("away_rest_bucket"),
            "home_fatigue_score": game.get("home_fatigue_score"),
            "away_fatigue_score": game.get("away_fatigue_score"),
            "fatigue_diff_home_minus_away": game.get("fatigue_diff_home_minus_away"),

            "MODEL_INJURY": ">>>",
            "home_injury_impact": game.get("home_injury_impact"),
            "away_injury_impact": game.get("away_injury_impact"),

            "FUTURE_MODEL_3PT":">>>",
            "home_score_final": game.get("home_score_final") or game.get("home_points"),
            "home_team_3pa": game.get("home_team_3pa"),
            "home_team_3pm": game.get("home_team_3pm"),
            "home_team_3pt_pct": game.get("home_team_3pt_pct"),
            "away_team_3pa": game.get("away_team_3pa"),
            "away_team_3pm": game.get("away_team_3pm"),
            "away_team_3pt_pct": game.get("away_team_3pt_pct"),

            "FUTURE_AGENT_DECISION_INFO": ">>>",
            "disagreement_flag": game.get("disagreement_flag"),
            "arbitration_cluster": game.get("arbitration_cluster"),
            "confidence_tier": game.get("confidence_tier"),
            "confidence_reason": game.get("confidence_reason"),
            "consensus_book_count": game.get("consensus_book_count"),
            "agent_override_confidence_delta": game.get("agent_override_confidence_delta"),
            "agent_override_pick": game.get("agent_override_pick"),
            "agent_override_reason": game.get("agent_override_reason"),
            "all_time_snapshot_count": game.get("all_time_snapshot_count"),
            "arbitration": game.get("arbitration"),

            "TIPOFF":">>>",
            "odds_commence_time_cst": game.get("odds_commence_time_cst"),

        })

export_df = pd.DataFrame(rows)
export_df.to_csv(OUT_CSV, index=False)

print(f"\nExport complete. Rows: {len(export_df)}")
print(f"\nlocation. Rows: {OUT_CSV}")