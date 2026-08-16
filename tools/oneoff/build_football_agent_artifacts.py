"""
Build additive football agent improvement artifacts.

The artifacts are advisory only. They read final views/backtests and write
outcome audits, regime candidates, and threshold proposals without mutating
deterministic model outputs or thresholds.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.io_helpers import get_backtest_output_root

MIN_REGIME_SAMPLE = 10


def _safe_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _latest_backtest_dir(league: str) -> Path | None:
    root = get_backtest_output_root(league)
    if not root.exists():
        return None
    dirs = [p for p in root.glob("backtest_*") if p.is_dir()]
    return sorted(dirs)[-1] if dirs else None


def _load_backtest_rows(league: str) -> tuple[Path | None, list[dict]]:
    backtest_dir = _latest_backtest_dir(league)
    if backtest_dir is None:
        return None, []
    path = backtest_dir / "backtest_games.json"
    if not path.exists():
        return backtest_dir, []
    with path.open("r", encoding="utf-8") as f:
        rows = json.load(f)
    return backtest_dir, rows if isinstance(rows, list) else []


def _edge_bucket(edge) -> str:
    edge_f = abs(_safe_float(edge))
    if edge_f >= 3:
        return "3+"
    if edge_f >= 2:
        return "2-3"
    if edge_f >= 1:
        return "1-2"
    if edge_f >= 0.5:
        return "0.5-1"
    return "0-0.5"


def _line_bucket(spread_home) -> str:
    line = abs(_safe_float(spread_home))
    if line >= 14:
        return "14+"
    if line >= 10:
        return "10-14"
    if line >= 7:
        return "7-10"
    if line >= 3:
        return "3-7"
    return "0-3"


def _summary(rows: list[dict], result_key: str) -> dict:
    graded = [r for r in rows if _safe_text(r.get(result_key)) in ("WIN", "LOSS", "PUSH")]
    wins = sum(1 for r in graded if r.get(result_key) == "WIN")
    losses = sum(1 for r in graded if r.get(result_key) == "LOSS")
    pushes = sum(1 for r in graded if r.get(result_key) == "PUSH")
    denom = wins + losses
    return {
        "graded": len(graded),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate_ex_push": round(wins / denom, 4) if denom else None,
    }


def _group(rows: list[dict], fields: tuple[str, ...], result_key: str) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = []
        for field in fields:
            if field == "spread_edge_bucket":
                key.append(_edge_bucket(row.get("selected_spread_edge")))
            elif field == "total_edge_bucket":
                key.append(_edge_bucket(row.get("selected_total_edge")))
            elif field == "spread_line_bucket":
                key.append(_line_bucket(row.get("spread_home") or row.get("market_spread_home")))
            else:
                key.append(_safe_text(row.get(field)) or "UNKNOWN")
        groups[tuple(key)].append(row)
    out = []
    for key, members in groups.items():
        result = {field: value for field, value in zip(fields, key)}
        result.update(_summary(members, result_key))
        result["regime_key"] = "+".join(f"{f}:{v}" for f, v in zip(fields, key))
        result["eligible_for_proposal"] = (result.get("graded") or 0) >= MIN_REGIME_SAMPLE
        out.append(result)
    out.sort(key=lambda r: ((r.get("win_rate_ex_push") if r.get("win_rate_ex_push") is not None else -1), r.get("graded", 0)), reverse=True)
    return out


def build_artifacts(league: str) -> dict:
    league = _safe_text(league).lower()
    if league not in ("nfl", "ncaaf"):
        raise ValueError("Football agent artifacts support nfl/ncaaf only")
    source_dir, rows = _load_backtest_rows(league)
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    agent_dir = PROJECT_ROOT / "data" / league / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    spread_audit = _summary(rows, "selected_spread_result")
    total_audit = _summary(rows, "selected_total_result")
    regime_specs = [
        ("spread_edge_bucket",),
        ("total_edge_bucket",),
        ("spread_line_bucket",),
        ("confidence_tier",),
        ("spread_edge_bucket", "spread_line_bucket", "confidence_tier"),
    ]
    spread_regimes = []
    total_regimes = []
    for spec in regime_specs:
        spread_regimes.extend(_group(rows, spec, "selected_spread_result"))
        total_regimes.extend(_group(rows, spec, "selected_total_result"))

    proposals = []
    for regime in spread_regimes[:10]:
        if regime.get("eligible_for_proposal") and (regime.get("win_rate_ex_push") or 0) >= 0.54:
            proposals.append(
                {
                    "market": "spread",
                    "proposal": "promote_regime_for_agent_execute",
                    "regime_key": regime["regime_key"],
                    "sample": regime["graded"],
                    "win_rate_ex_push": regime["win_rate_ex_push"],
                    "requires_human_review": True,
                }
            )
    for regime in total_regimes[:10]:
        if regime.get("eligible_for_proposal") and (regime.get("win_rate_ex_push") or 0) >= 0.54:
            proposals.append(
                {
                    "market": "total",
                    "proposal": "promote_regime_for_agent_execute",
                    "regime_key": regime["regime_key"],
                    "sample": regime["graded"],
                    "win_rate_ex_push": regime["win_rate_ex_push"],
                    "requires_human_review": True,
                }
            )

    base = {
        "league": league,
        "generated_at_utc": generated,
        "source_backtest_dir": str(source_dir) if source_dir else None,
        "row_count": len(rows),
        "advisory_only": True,
        "mutation_policy": "agents do not modify deterministic model output",
    }
    audit = {**base, "artifact_type": "football_outcome_audit", "spread": spread_audit, "total": total_audit}
    regimes = {**base, "artifact_type": "football_regime_candidates", "spread_regimes": spread_regimes, "total_regimes": total_regimes}
    proposal_doc = {**base, "artifact_type": "football_threshold_proposals", "proposals": proposals}

    paths = {
        "audit": agent_dir / f"{league}_outcome_audit.json",
        "regimes": agent_dir / f"{league}_regime_candidates.json",
        "proposals": agent_dir / f"{league}_threshold_proposals.json",
    }
    for name, payload in (("audit", audit), ("regimes", regimes), ("proposals", proposal_doc)):
        with paths[name].open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    return {"paths": paths, "row_count": len(rows), "proposal_count": len(proposals)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build football additive agent artifacts")
    parser.add_argument("--league", required=True, choices=["nfl", "ncaaf"])
    args = parser.parse_args()
    result = build_artifacts(args.league)
    print(f"[football_agent] {args.league} rows={result['row_count']} proposals={result['proposal_count']}")
    for key, path in result["paths"].items():
        print(f"{key}={path}")


if __name__ == "__main__":
    main()
