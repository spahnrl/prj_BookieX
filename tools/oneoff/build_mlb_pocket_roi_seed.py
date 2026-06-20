"""
Build MLB Pocket ROI seed artifacts from the validated prediction ledger.

This is intentionally limited-sample output. It summarizes the existing
MLB prediction ledger only; it does not create new predictions or mature
NBA-style pocket confidence.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_DIR = PROJECT_ROOT / "data" / "mlb" / "backtests"
LEDGER_PATH = BACKTEST_DIR / "mlb_prediction_ledger_seed.json"

SEED_WARNING = (
    "MLB Pocket ROI seed artifact: limited sample from current MLB prediction ledger. "
    "Use for diagnostics only until a larger settled-game history exists."
)


def _safe_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _edge_bucket(edge) -> str:
    edge_f = _safe_float(edge)
    if edge_f >= 4:
        return "4+"
    if edge_f >= 2:
        return "2-4"
    if edge_f >= 1:
        return "1-2"
    if edge_f >= 0.5:
        return "0.5-1"
    return "0-0.5"


def _load_ledger() -> dict:
    if not LEDGER_PATH.exists():
        raise SystemExit(f"Missing MLB prediction ledger seed: {LEDGER_PATH}")
    with LEDGER_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise SystemExit(f"Invalid ledger JSON shape: {LEDGER_PATH}")
    rows = payload.get("ledger")
    if not isinstance(rows, list) or not rows:
        raise SystemExit(f"Ledger has no graded rows: {LEDGER_PATH}")
    return payload


def _summarize(rows: list[dict]) -> dict:
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
        "sample_notes": SEED_WARNING,
    }


def _group_rows(rows: list[dict], key_fields: tuple[str, ...]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = []
        for field in key_fields:
            if field == "edge_bucket":
                key.append(_edge_bucket(row.get("edge")))
            elif field == "model":
                key.append("MLB_MarketValueBlend_v1")
            else:
                key.append(_safe_text(row.get(field)) or "UNKNOWN")
        grouped[tuple(key)].append(row)

    out = []
    for key, group in grouped.items():
        summary = _summarize(group)
        row = {field: value for field, value in zip(key_fields, key)}
        row.update(summary)
        row["pocket_type"] = "+".join(f"{field}:{value}" for field, value in zip(key_fields, key))
        out.append(row)
    out.sort(key=lambda r: ((r.get("roi") if r.get("roi") is not None else -999), r.get("graded_games", 0)), reverse=True)
    return out


def _ranked_opportunities(rows: list[dict], pockets: list[dict]) -> list[dict]:
    pocket_lookup = {p["pocket_type"]: p for p in pockets}
    ranked = []
    for row in rows:
        keys = [
            ("model", "MLB_MarketValueBlend_v1"),
            ("pick_type", _safe_text(row.get("pick_type"))),
            ("confidence_tier", _safe_text(row.get("confidence_tier"))),
            ("edge_bucket", _edge_bucket(row.get("edge"))),
            ("actionability", _safe_text(row.get("actionability"))),
        ]
        pocket_type = "+".join(f"{k}:{v}" for k, v in keys)
        pocket = pocket_lookup.get(pocket_type) or _summarize([row])
        ranked.append(
            {
                "Rank": 0,
                "game_id": row.get("odds_game_id"),
                "slate_date": row.get("slate_date"),
                "Recommended Bet": f"{row.get('away_team')} @ {row.get('home_team')}: {row.get('pick')} ({row.get('line')})",
                "Pocket Type": row.get("pick_type"),
                "Pocket Models": "MLB_MarketValueBlend_v1",
                "State Signature": pocket_type,
                "ROI": pocket.get("roi"),
                "Win Rate": pocket.get("win_rate"),
                "Graded Games": pocket.get("graded_games"),
                "Trust Rating": "SEED",
                "Trust Score": min(50, int((pocket.get("graded_games") or 0) * 10)),
                "Why": f"Seed pocket from {pocket.get('graded_games')} graded MLB pick(s); result={row.get('result')}.",
                "Parlay Eligible": bool((pocket.get("roi") or 0) > 0 and (pocket.get("graded_games") or 0) >= 2),
                "sample_warning": SEED_WARNING,
            }
        )
    ranked.sort(key=lambda r: ((r.get("ROI") if r.get("ROI") is not None else -999), r.get("Graded Games") or 0), reverse=True)
    for idx, row in enumerate(ranked, start=1):
        row["Rank"] = idx
    return ranked


def _best_per_game(ranked: list[dict]) -> list[dict]:
    by_game: dict[str, dict] = {}
    for row in ranked:
        gid = _safe_text(row.get("game_id"))
        if not gid:
            continue
        current = by_game.get(gid)
        if current is None or ((row.get("ROI") or -999), row.get("Graded Games") or 0) > ((current.get("ROI") or -999), current.get("Graded Games") or 0):
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
                "sample_warning": SEED_WARNING,
            }
        )
    return out


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def build_seed_artifacts() -> dict:
    ledger_payload = _load_ledger()
    rows = [r for r in ledger_payload.get("ledger", []) if r.get("roi_ready")]
    if not rows:
        raise SystemExit("No ROI-ready MLB ledger rows available.")

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
        grouped = _group_rows(rows, spec)
        summaries["+".join(spec)] = grouped
        if spec == ("model", "pick_type", "confidence_tier", "edge_bucket", "actionability"):
            pockets = grouped

    ranked = _ranked_opportunities(rows, pockets)
    best = _best_per_game(ranked)

    base = {
        "league": "mlb",
        "artifact_scope": "seed_limited_sample",
        "generated_at_utc": generated_at,
        "source_ledger": str(LEDGER_PATH),
        "sample_warning": SEED_WARNING,
        "is_pocket_roi_output": True,
        "is_limited_sample": True,
        "graded_pick_count": len(rows),
        "overall": _summarize(rows),
    }
    model_pockets = {**base, "artifact_type": "model_pockets", "summaries": summaries, "pockets": pockets}
    ranked_doc = {**base, "artifact_type": "ranked_pocket_opportunities", "opportunities": ranked}
    best_doc = {**base, "artifact_type": "best_pocket_per_game", "games": best}
    live_doc = {**base, "artifact_type": "live_pocket_leaderboard", "slate_date": max(_safe_text(r.get("slate_date")) for r in rows), "opportunities": ranked}

    outputs = {
        "model_pockets": BACKTEST_DIR / "mlb_model_pockets.json",
        "ranked": BACKTEST_DIR / "mlb_ranked_pocket_opportunities.json",
        "best": BACKTEST_DIR / "mlb_best_pocket_per_game.json",
        "live": BACKTEST_DIR / "mlb_live_pocket_leaderboard.json",
    }
    _write_json(outputs["model_pockets"], model_pockets)
    _write_json(outputs["ranked"], ranked_doc)
    _write_json(outputs["best"], best_doc)
    _write_json(outputs["live"], live_doc)
    return {
        "graded_pick_count": len(rows),
        "ranked_count": len(ranked),
        "best_game_count": len(best),
        "overall_roi": model_pockets["overall"].get("roi"),
        "outputs": outputs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build MLB limited-sample Pocket ROI seed artifacts.")
    parser.parse_args()
    result = build_seed_artifacts()
    print("[mlb_pocket_seed] OK")
    print(f"graded_pick_count={result['graded_pick_count']}")
    print(f"ranked_count={result['ranked_count']}")
    print(f"best_game_count={result['best_game_count']}")
    print(f"overall_roi={result['overall_roi']}")
    for key, path in result["outputs"].items():
        print(f"{key}={path}")


if __name__ == "__main__":
    main()

