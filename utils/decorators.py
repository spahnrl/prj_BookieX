"""
utils/decorators.py

Structured reasoning decorators for the BookieX pipeline.
- @agent_reasoning: Injects Sweet Spot reasoning from bias_report_ncaam.json
  when a game falls into a bias-report bucket (e.g. spread_edge_10.0_15.0).
  Reasoning string: "Selecting [PICK] because it falls into the [BUCKET] Sweet Spot (Historical Win Rate: [WR]%)".

Authority: eng/models/model_gen_0052_add_model.py, eng/outputs/analysis/bias_report_ncaam.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from functools import wraps

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BIAS_REPORT_NCAAM_PATH = PROJECT_ROOT / "data" / "ncaam" / "reports" / "bias_report_ncaam.json"


def _load_bias_report_ncaam() -> dict | None:
    if not BIAS_REPORT_NCAAM_PATH.exists():
        return None
    try:
        with open(BIAS_REPORT_NCAAM_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_float(x) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _parse_sweet_spot_bucket(scenario: str) -> tuple[float | None, float | None]:
    """
    Parse scenario like 'spread_edge_10.0_15.0' or 'spread_edge_25.0_inf' into (edge_min, edge_max).
    edge_max None means inf.
    """
    if not scenario or not isinstance(scenario, str):
        return None, None
    parts = scenario.split("_")
    if len(parts) < 4:
        return None, None
    try:
        edge_min = float(parts[-2])
        last = parts[-1].lower()
        if last == "inf":
            return edge_min, None
        edge_max = float(last)
        return edge_min, edge_max
    except (ValueError, IndexError):
        return None, None


def _sweet_spot_reasoning_for_row(row: dict, report: dict) -> str:
    """
    Build agent_reasoning string for one NCAAM row using sweet_spots from bias report.
    Returns one or two sentences for spread/total picks that fall into a Sweet Spot.
    """
    sweet_spots = report.get("sweet_spots") or []
    if not sweet_spots:
        return ""

    spread_edge = _safe_float(row.get("Spread Edge"))
    total_edge = _safe_float(row.get("Total Edge"))
    line_bet = (row.get("Line Bet") or "").strip()
    total_bet = (row.get("Total Bet") or "").strip()

    parts = []

    for ss in sweet_spots:
        scenario = ss.get("scenario") or ""
        stype = (ss.get("type") or "").strip()
        win_rate = ss.get("win_rate")
        if win_rate is None:
            continue
        wr_pct = f"{win_rate * 100:.2f}"

        if stype == "spread_edge_bucket" and line_bet and spread_edge is not None:
            edge_min, edge_max = _parse_sweet_spot_bucket(scenario)
            if edge_min is not None:
                in_range = edge_min <= abs(spread_edge)
                if edge_max is not None:
                    in_range = in_range and abs(spread_edge) < edge_max
                if in_range:
                    parts.append(
                        f"Selecting {line_bet} because it falls into the {scenario} Sweet Spot (Historical Win Rate: {wr_pct}%)"
                    )
        elif stype == "total_edge_bucket" and total_bet and total_edge is not None:
            edge_min, edge_max = _parse_sweet_spot_bucket(scenario)
            if edge_min is not None:
                in_range = edge_min <= abs(total_edge)
                if edge_max is not None:
                    in_range = in_range and abs(total_edge) < edge_max
                if in_range:
                    parts.append(
                        f"Selecting {total_bet} because it falls into the {scenario} Sweet Spot (Historical Win Rate: {wr_pct}%)"
                    )

    return " ".join(parts) if parts else ""


def add_agent_reasoning_to_rows(rows: list[dict], league: str = "ncaam") -> list[dict]:
    """
    In-place add agent_reasoning to each row when league is ncaam and row falls into a Sweet Spot.
    Use this when the row-producing function cannot be decorated (e.g. nested in run_ncaam).
    """
    if league != "ncaam":
        for r in rows:
            r["agent_reasoning"] = r.get("agent_reasoning") or ""
        return rows
    report = _load_bias_report_ncaam()
    if not report:
        for r in rows:
            r["agent_reasoning"] = r.get("agent_reasoning") or ""
        return rows
    for row in rows:
        reason = _sweet_spot_reasoning_for_row(row, report)
        row["agent_reasoning"] = reason
    return rows


def agent_reasoning(league: str = "ncaam"):
    """
    Decorator that injects agent_reasoning into rows returned by the wrapped function.
    Only applies to NCAAM; uses eng/outputs/analysis/bias_report_ncaam.json Sweet Spots.
    Wrapped function must accept (games: list) and return list[dict] (rows with Spread Edge, Total Edge, Line Bet, Total Bet).
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(games, *args, **kwargs):
            rows = fn(games, *args, **kwargs)
            if league != "ncaam":
                return rows
            report = _load_bias_report_ncaam()
            if not report:
                return rows
            for row in rows:
                reason = _sweet_spot_reasoning_for_row(row, report)
                row["agent_reasoning"] = reason
            return rows
        return wrapper
    return decorator
