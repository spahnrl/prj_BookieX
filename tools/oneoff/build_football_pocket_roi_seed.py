"""
Build NFL/NCAAF Pocket ROI seed artifacts from graded football backtests.

The artifact contract matches the WNBA/MLB seed Pocket ROI dashboard path:
historical 2025 backtest rows provide limited-sample ROI pockets, while the
current active final view provides the selected-slate opportunities.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BET_PRICE = -110
PAYOUT_MULTIPLIER = 100 / abs(BET_PRICE)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _edge_bucket(edge: Any) -> str:
    edge_f = abs(_safe_float(edge))
    if edge_f >= 4:
        return "4+"
    if edge_f >= 2:
        return "2-4"
    if edge_f >= 1:
        return "1-2"
    if edge_f >= 0.5:
        return "0.5-1"
    return "0-0.5"


def _norm_pick(value: Any) -> str:
    return " ".join(_safe_text(value).upper().split())


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _latest_backtest_games_path(league: str) -> Path:
    root = PROJECT_ROOT / "data" / league / "backtests"
    candidates = sorted(root.glob("backtest_*/backtest_games.json"))
    if not candidates:
        raise SystemExit(f"Missing football backtest_games.json under {root}")
    return candidates[-1]


def _load_rows(path: Path) -> list[dict]:
    payload = _load_json(path)
    rows = payload.get("games") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise SystemExit(f"Invalid row JSON shape: {path}")
    return [r for r in rows if isinstance(r, dict)]


def _unit_result(result: str) -> float | None:
    result = _safe_text(result).upper()
    if result == "WIN":
        return round(PAYOUT_MULTIPLIER, 4)
    if result == "LOSS":
        return -1.0
    if result == "PUSH":
        return 0.0
    return None


def _format_line(row: dict, pick_type: str, pick: str) -> Any:
    if pick_type == "total":
        return row.get("total_last", row.get("total"))
    if pick == "HOME":
        return row.get("spread_home_last", row.get("spread_home"))
    if pick == "AWAY":
        return row.get("spread_away_last", row.get("spread_away"))
    return None


def _display_pick(row: dict, pick_type: str, pick: str, line: Any) -> str:
    away = _safe_text(row.get("away_team")) or "Away"
    home = _safe_text(row.get("home_team")) or "Home"
    if pick_type == "total":
        return f"{pick} {line}" if line not in (None, "") else pick
    team = home if pick == "HOME" else away if pick == "AWAY" else pick
    return f"{team} {line}" if line not in (None, "") else team


def _row_base(league: str, game: dict, model_name: str, pick_type: str, model_row: dict) -> dict | None:
    pick_key = "spread_pick" if pick_type == "spread" else "total_pick"
    edge_key = "spread_edge" if pick_type == "spread" else "total_edge"
    result_key = "spread_result" if pick_type == "spread" else "total_result"
    pick = _norm_pick(model_row.get(pick_key))
    if not pick or pick in {"PENDING MARKET", "PASS", "NONE"}:
        return None
    line = _format_line(game, pick_type, pick)
    result = _safe_text(model_row.get(result_key)).upper()
    unit = _unit_result(result)
    return {
        "league": league,
        "slate_date": _safe_text(game.get("game_date")),
        "odds_game_id": _safe_text(game.get("game_id") or game.get("odds_event_id")),
        "away_team": _safe_text(game.get("away_team")),
        "home_team": _safe_text(game.get("home_team")),
        "model_name": model_name,
        "pick_type": pick_type,
        "pick": pick,
        "line": line,
        "display_pick": _display_pick(game, pick_type, pick, line),
        "edge": _optional_float(model_row.get(edge_key)),
        "confidence_tier": _safe_text(game.get("confidence_tier")) or "SEED",
        "actionability": _safe_text(game.get("actionability")) or "ACTIVE",
        "result": result,
        "unit_result": unit,
        "roi_ready": unit is not None,
        "source_row_type": "single_model",
    }


def _model_rows_from_games(league: str, games: list[dict], require_graded: bool) -> list[dict]:
    out = []
    for game in games:
        models = game.get("model_results") or game.get("models") or {}
        if not isinstance(models, dict):
            continue
        for model_name, model_row in models.items():
            if not isinstance(model_row, dict):
                continue
            for pick_type in ("spread", "total"):
                row = _row_base(league, game, _safe_text(model_name), pick_type, model_row)
                if not row:
                    continue
                if require_graded and not row["roi_ready"]:
                    continue
                out.append(row)
    return out


def _summarize(rows: list[dict], seed_warning: str) -> dict:
    graded = [r for r in rows if _safe_text(r.get("result")) in ("WIN", "LOSS", "PUSH")]
    wins = sum(1 for r in graded if r.get("result") == "WIN")
    losses = sum(1 for r in graded if r.get("result") == "LOSS")
    pushes = sum(1 for r in graded if r.get("result") == "PUSH")
    units = round(sum(_safe_float(r.get("unit_result")) for r in graded), 4)
    risked = wins + losses
    return {
        "graded_games": len(graded),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": round(wins / risked, 4) if risked else None,
        "units": units,
        "roi": round(units / risked, 4) if risked else None,
        "sample_notes": seed_warning,
    }


def _combo_rows(rows: list[dict]) -> list[dict]:
    by_alignment: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        model_name = _safe_text(row.get("model_name"))
        key = (
            _safe_text(row.get("slate_date")),
            _safe_text(row.get("odds_game_id")),
            _safe_text(row.get("pick_type")),
            _norm_pick(row.get("pick")),
        )
        if model_name and all(key):
            by_alignment[key][model_name] = row

    combos = []
    for (_slate_date, _game_id, _pick_type, _pick), model_rows in by_alignment.items():
        model_names = sorted(model_rows)
        for size in range(2, min(3, len(model_names)) + 1):
            for model_set in combinations(model_names, size):
                aligned = [model_rows[name] for name in model_set]
                representative = dict(aligned[0])
                edges = [_safe_float(row.get("edge")) for row in aligned if row.get("edge") is not None]
                representative.update(
                    {
                        "model_name": "+".join(model_set),
                        "combo_models": list(model_set),
                        "combo_size": size,
                        "pocket_family": f"combo_{size}_model",
                        "confidence_tier": f"{size}_MODEL_ALIGN",
                        "actionability": "ALIGNED",
                        "edge": round(sum(edges) / len(edges), 4) if edges else None,
                        "source_row_type": "model_alignment_combo",
                    }
                )
                combos.append(representative)
    return combos


def _group_rows(rows: list[dict], key_fields: tuple[str, ...], seed_warning: str) -> list[dict]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = []
        for field in key_fields:
            if field == "edge_bucket":
                key.append(_edge_bucket(row.get("edge")))
            elif field == "model":
                key.append(_safe_text(row.get("model_name")) or "Football_MarketBlend_v1")
            else:
                key.append(_safe_text(row.get(field)) or "UNKNOWN")
        grouped[tuple(key)].append(row)

    out = []
    for key, group in grouped.items():
        summary = _summarize(group, seed_warning)
        row = {field: value for field, value in zip(key_fields, key)}
        row.update(summary)
        row["pocket_type"] = "+".join(f"{field}:{value}" for field, value in zip(key_fields, key))
        out.append(row)
    out.sort(
        key=lambda r: ((r.get("roi") if r.get("roi") is not None else -999), r.get("graded_games", 0)),
        reverse=True,
    )
    return out


def _ranked_opportunities(rows: list[dict], pockets: list[dict], league_label: str, seed_warning: str) -> list[dict]:
    pocket_lookup = {p["pocket_type"]: p for p in pockets}
    ranked = []
    for row in rows:
        model_name = _safe_text(row.get("model_name")) or "Football_MarketBlend_v1"
        keys = [
            ("model", model_name),
            ("pick_type", _safe_text(row.get("pick_type"))),
            ("confidence_tier", _safe_text(row.get("confidence_tier"))),
            ("edge_bucket", _edge_bucket(row.get("edge"))),
            ("actionability", _safe_text(row.get("actionability"))),
        ]
        pocket_type = "+".join(f"{k}:{v}" for k, v in keys)
        pocket = pocket_lookup.get(pocket_type) or {}
        if not pocket:
            historical_single = dict(row)
            historical_single["result"] = ""
            pocket = _summarize([], seed_warning)
        family = _safe_text(row.get("pocket_family")) or "single_model"
        model_count = _safe_text(row.get("combo_size")) or "1"
        why_prefix = f"{model_count} {league_label} models aligned; " if family.startswith("combo_") else ""
        matchup = f"{row.get('away_team')} @ {row.get('home_team')}"
        graded = pocket.get("graded_games") or 0
        ranked.append(
            {
                "Rank": 0,
                "game_id": row.get("odds_game_id"),
                "slate_date": row.get("slate_date"),
                "Recommended Bet": f"{matchup}: {row.get('display_pick')}",
                "Pocket Type": f"{family}_{row.get('pick_type')}",
                "Pocket Models": model_name,
                "State Signature": pocket_type,
                "ROI": pocket.get("roi"),
                "Win Rate": pocket.get("win_rate"),
                "Graded Games": graded,
                "Trust Rating": "SEED",
                "Trust Score": min(50, int(graded * 2)),
                "Why": f"{why_prefix}Historical seed pocket from {graded} graded {league_label} pick(s).",
                "Parlay Eligible": bool((pocket.get("roi") or 0) > 0 and graded >= 5 and row.get("pick_type") == "spread"),
                "Source Row Type": _safe_text(row.get("source_row_type")) or "single_model",
                "sample_warning": seed_warning,
            }
        )
    ranked.sort(
        key=lambda r: ((r.get("ROI") if r.get("ROI") is not None else -999), r.get("Graded Games") or 0),
        reverse=True,
    )
    for idx, row in enumerate(ranked, start=1):
        row["Rank"] = idx
    return ranked


def _best_per_game(ranked: list[dict], seed_warning: str) -> list[dict]:
    by_game: dict[str, dict] = {}
    for row in ranked:
        gid = _safe_text(row.get("game_id"))
        if not gid:
            continue
        current = by_game.get(gid)
        row_key = (row.get("ROI") if row.get("ROI") is not None else -999, row.get("Graded Games") or 0)
        cur_key = (
            current.get("ROI") if current and current.get("ROI") is not None else -999,
            current.get("Graded Games") if current else 0,
        )
        if current is None or row_key > cur_key:
            by_game[gid] = row
    out = []
    for idx, row in enumerate(sorted(by_game.values(), key=lambda r: r.get("Rank") or 999), start=1):
        out.append(
            {
                "Rank": idx,
                "Game": row.get("Recommended Bet", "").split(":")[0],
                "Recommended Bet": row.get("Recommended Bet"),
                "Best Pocket Type": row.get("Pocket Type"),
                "Pocket Models": row.get("Pocket Models"),
                "Pocket ROI": row.get("ROI"),
                "Pocket Win Rate": row.get("Win Rate"),
                "Pocket Games": row.get("Graded Games"),
                "Why": row.get("Why"),
                "Parlay Eligible": row.get("Parlay Eligible"),
                "sample_warning": seed_warning,
            }
        )
    return out


def build_seed_artifacts(league: str) -> dict:
    league = league.lower().strip()
    if league not in {"nfl", "ncaaf"}:
        raise SystemExit("--league must be nfl or ncaaf")
    league_label = league.upper()
    backtest_dir = PROJECT_ROOT / "data" / league / "backtests"
    backtest_path = _latest_backtest_games_path(league)
    active_path = PROJECT_ROOT / "data" / league / "view" / f"final_game_view_{league}_active.json"
    if not active_path.exists():
        active_path = PROJECT_ROOT / "data" / league / "view" / f"final_game_view_{league}.json"
    seed_warning = (
        f"{league_label} Pocket ROI seed artifact: limited sample from 2025 football backtest rows. "
        "Read-only diagnostics until larger settled football histories exist."
    )

    historical_rows = _model_rows_from_games(league, _load_rows(backtest_path), require_graded=True)
    if not historical_rows:
        raise SystemExit(f"No ROI-ready {league_label} football model rows available.")
    live_rows = _model_rows_from_games(league, _load_rows(active_path), require_graded=False)
    live_rows = [r for r in live_rows if r.get("slate_date") and not r.get("roi_ready")]

    historical_combo_rows = _combo_rows(historical_rows)
    live_combo_rows = _combo_rows(live_rows)
    historical_opportunity_rows = historical_rows + historical_combo_rows
    live_opportunity_rows = live_rows + live_combo_rows

    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    group_specs = [
        ("model",),
        ("pick_type",),
        ("confidence_tier",),
        ("edge_bucket",),
        ("actionability",),
        ("model", "pick_type", "confidence_tier", "edge_bucket", "actionability"),
    ]
    pockets = []
    summaries = {}
    for spec in group_specs:
        grouped = _group_rows(historical_opportunity_rows, spec, seed_warning)
        summaries["+".join(spec)] = grouped
        if spec == ("model", "pick_type", "confidence_tier", "edge_bucket", "actionability"):
            pockets = grouped

    ranked = _ranked_opportunities(live_opportunity_rows, pockets, league_label, seed_warning)
    best = _best_per_game(ranked, seed_warning)
    slate_dates = sorted({_safe_text(r.get("slate_date")) for r in ranked if _safe_text(r.get("slate_date"))})
    base = {
        "league": league,
        "artifact_scope": "football_seed_limited_sample",
        "generated_at_utc": generated_at,
        "source_backtest_games": str(backtest_path),
        "source_active_view": str(active_path),
        "sample_warning": seed_warning,
        "is_pocket_roi_output": True,
        "is_limited_sample": True,
        "graded_pick_count": len(historical_rows),
        "single_model_pick_count": len(live_rows),
        "combo_alignment_pick_count": len(live_combo_rows),
        "opportunity_pick_count": len(live_opportunity_rows),
        "overall": _summarize(historical_rows, seed_warning),
    }
    model_pockets = {**base, "artifact_type": "model_pockets", "summaries": summaries, "pockets": pockets}
    ranked_doc = {**base, "artifact_type": "ranked_pocket_opportunities", "opportunities": ranked}
    best_doc = {**base, "artifact_type": "best_pocket_per_game", "games": best}
    live_doc = {
        **base,
        "artifact_type": "live_pocket_leaderboard",
        "slate_date": max(slate_dates) if slate_dates else None,
        "slate_dates": slate_dates,
        "opportunities": ranked,
    }

    outputs = {
        "model_pockets": backtest_dir / f"{league}_model_pockets.json",
        "ranked": backtest_dir / f"{league}_ranked_pocket_opportunities.json",
        "best": backtest_dir / f"{league}_best_pocket_per_game.json",
        "live": backtest_dir / f"{league}_live_pocket_leaderboard.json",
    }
    _write_json(outputs["model_pockets"], model_pockets)
    _write_json(outputs["ranked"], ranked_doc)
    _write_json(outputs["best"], best_doc)
    _write_json(outputs["live"], live_doc)
    return {
        "league": league,
        "graded_pick_count": len(historical_rows),
        "ranked_count": len(ranked),
        "best_game_count": len(best),
        "overall_roi": model_pockets["overall"].get("roi"),
        "outputs": outputs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build NFL/NCAAF limited-sample Pocket ROI seed artifacts.")
    parser.add_argument("--league", choices=["nfl", "ncaaf"], required=True)
    args = parser.parse_args()
    result = build_seed_artifacts(args.league)
    print(f"[{result['league']}_pocket_seed] OK")
    print(f"graded_pick_count={result['graded_pick_count']}")
    print(f"ranked_count={result['ranked_count']}")
    print(f"best_game_count={result['best_game_count']}")
    print(f"overall_roi={result['overall_roi']}")
    for key, path in result["outputs"].items():
        print(f"{key}={path}")


if __name__ == "__main__":
    main()
