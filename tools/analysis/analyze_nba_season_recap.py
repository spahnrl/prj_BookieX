"""
tools/analysis/analyze_nba_season_recap.py

NBA season-end model performance recap (READ-ONLY analysis).

What this does
--------------
Reads the best available NBA backtest artifacts and produces a full-season recap,
with special focus on regular season vs postseason (play-in + playoffs) behavior.

It is strictly read-only with respect to the pipeline:
- Does NOT change model, scoring, daily-view, or dashboard logic.
- Does NOT mutate or overwrite any backtest folder.
- Only writes to a NEW folder: data/nba/analysis/season_recap_<YYYYMMDD_HHMMSS>/.

Shared rules (ROI = -110 accounting, execution-overlay banding/classification) are
IMPORTED from the existing pipeline modules so this recap mirrors live logic instead
of duplicating it.

Segment classification (per game)
---------------------------------
Three reportable segments: ``regular``, ``play_in``, ``playoffs``.
Priority:
  1. Explicit ``season_type`` field if it maps to a known value.
  2. NBA ``game_id`` prefix: 004=playoffs, 002=regular, 001=preseason.
  3. Date fallback using --play-in-start-date / --playoff-start-date.
Because neither ``season_type`` nor the ``game_id`` prefix can express the play-in
tournament (NBA play-in IDs are not 004/002/001), a documented date-window overlay
re-tags a game classified as ``playoffs`` to ``play_in`` when its date falls in
[play_in_start, playoff_start). ``preseason`` / ``unknown`` are tracked but excluded
from the headline comparisons.

CLI
---
python tools/analysis/analyze_nba_season_recap.py \
    --play-in-start-date 2026-04-14 \
    --playoff-start-date 2026-04-18 \
    --min-sample-size 20 \
    [--backtest-dir backtest_YYYYMMDD_HHMMSS]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Read-only imports of shared pipeline logic (no side effects at import time).
from eng.execution.build_execution_overlay import (  # noqa: E402
    compute_overlay_from_edges,
    determine_band,
)
from eng.analysis.analysis_039b_execution_overlay_performance import (  # noqa: E402
    classify_overlay,
)

LEAGUE = "nba"
DEFAULT_AUTHORITY = "Joel_Baseline_v1"
EXCLUDED_MODELS = frozenset({"MonkeyDarts_v2"})

# Known-corrupt backtest folder (quarantined). Never auto-select it.
QUARANTINED_BACKTESTS = frozenset({"backtest_20260517_100524"})

# -110 accounting, identical to build_nba_model_pockets / analysis_039b.
BET_PRICE = -110
PAYOUT_MULTIPLIER = 100 / abs(BET_PRICE)  # ~0.9091
BREAKEVEN_WIN_RATE = 100 / (100 + abs(BET_PRICE))  # ~0.52381

# Defaults for 2025-2026 NBA postseason.
DEFAULT_PLAY_IN_START = "2026-04-14"
DEFAULT_PLAYOFF_START = "2026-04-18"

OVERLAY_BUCKETS = [
    "Dual Sweet Spot",
    "Spread Sweet Spot",
    "Total Sweet Spot",
    "Neutral",
    "Avoid",
    "All Games",
]

POCKET_ARTIFACTS = [
    "nba_model_pockets.json",
    "nba_model_combo_pockets.json",
    "nba_live_pocket_leaderboard.json",
    "nba_best_pocket_per_game.json",
    "nba_ranked_pocket_opportunities.json",
    "nba_pocket_leaderboard_validation.json",
]


# ============================================================================
# Small helpers
# ============================================================================

def _safe_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm_result(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().upper()
    return s if s in ("WIN", "LOSS", "PUSH") else None


def _profit_for_leg(res: str) -> float:
    if res == "WIN":
        return PAYOUT_MULTIPLIER
    if res == "LOSS":
        return -1.0
    return 0.0


def _parse_iso_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s.strip()[:10])
    except (ValueError, AttributeError):
        return None


def _fmt_pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _fmt_roi(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:+.2f}%"


def _fmt_num(x: Optional[float], digits: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def _load_json_safe(path: Path, log: list[str]) -> Optional[Any]:
    """Load JSON; on missing/corrupt return None and append a log line."""
    if not path.exists():
        log.append(f"SKIP (missing): {path.name}")
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        log.append(f"SKIP (corrupt/unreadable): {path.name} -- {exc}")
        return None


# ============================================================================
# Backtest resolution
# ============================================================================

def resolve_backtest_dir(backtest_dir: Optional[str], log: list[str]) -> Path:
    root = PROJECT_ROOT / "data" / LEAGUE / "backtests"
    if not root.exists():
        raise FileNotFoundError(f"Backtest root not found: {root}")

    if backtest_dir:
        target = root / backtest_dir.strip()
        if not target.is_dir():
            raise FileNotFoundError(f"Backtest dir not found: {target}")
        if not (target / "backtest_games.json").exists():
            raise FileNotFoundError(f"No backtest_games.json in: {target}")
        log.append(f"Backtest dir (explicit): {target.name}")
        return target

    candidates = [
        d for d in root.iterdir()
        if d.is_dir()
        and d.name.startswith("backtest_")
        and d.name not in QUARANTINED_BACKTESTS
        and (d / "backtest_games.json").exists()
    ]
    if not candidates:
        raise FileNotFoundError(
            f"No usable backtest_* folders with backtest_games.json in {root} "
            f"(quarantined excluded: {sorted(QUARANTINED_BACKTESTS)})"
        )
    latest = max(candidates, key=lambda d: d.stat().st_mtime)
    log.append(f"Backtest dir (latest by mtime): {latest.name}")
    return latest


# ============================================================================
# Segment classification
# ============================================================================

_SEASON_TYPE_MAP = {
    "regular": "regular",
    "regular season": "regular",
    "reg": "regular",
    "playoffs": "playoffs",
    "playoff": "playoffs",
    "postseason": "playoffs",
    "post": "playoffs",
    "preseason": "preseason",
    "pre": "preseason",
    "play_in": "play_in",
    "play-in": "play_in",
    "playin": "play_in",
}


def classify_segment(
    game: dict,
    play_in_start: date,
    playoff_start: date,
) -> tuple[str, str]:
    """Return (segment, method). Segments: regular|play_in|playoffs|preseason|unknown."""
    gdate = _parse_iso_date(str(game.get("game_date") or ""))

    base: Optional[str] = None
    method = ""

    season_type = str(game.get("season_type") or "").strip().lower()
    if season_type and season_type in _SEASON_TYPE_MAP:
        base = _SEASON_TYPE_MAP[season_type]
        method = "season_type"

    if base is None:
        gid = str(game.get("game_id") or "")
        if gid.startswith("004"):
            base, method = "playoffs", "game_id"
        elif gid.startswith("002"):
            base, method = "regular", "game_id"
        elif gid.startswith("001"):
            base, method = "preseason", "game_id"

    if base is None:
        if gdate is None:
            return "unknown", "no_date"
        if gdate >= playoff_start:
            return "playoffs", "date"
        if gdate >= play_in_start:
            return "play_in", "date"
        return "regular", "date"

    # Date-window overlay: season_type/game_id cannot express the play-in tournament,
    # so a postseason game inside [play_in_start, playoff_start) is re-tagged play_in.
    if base == "playoffs" and gdate is not None and play_in_start <= gdate < playoff_start:
        return "play_in", f"{method}+date_playin_window"

    return base, method


# ============================================================================
# Record extraction
# ============================================================================

def _iter_model_results(game: dict):
    """Yield (model_name, result_blob) for graded models, excluding excluded models.

    Falls back to selected_* fields as a synthetic authority model when model_results
    is absent (older/simpler backtest rows).
    """
    mr = game.get("model_results") or {}
    if isinstance(mr, dict) and mr:
        for name, blob in mr.items():
            if name in EXCLUDED_MODELS or not isinstance(blob, dict):
                continue
            yield name, blob
        return
    auth = str(game.get("selection_authority") or DEFAULT_AUTHORITY)
    yield auth, {
        "spread_result": game.get("selected_spread_result"),
        "total_result": game.get("selected_total_result"),
        "parlay_result": game.get("selected_parlay_result"),
        "spread_edge": game.get("selected_spread_edge"),
        "total_edge": game.get("selected_total_edge"),
        "spread_pick": game.get("selected_spread_pick"),
        "total_pick": game.get("selected_total_pick"),
    }


def build_records(
    games: list[dict],
    play_in_start: date,
    playoff_start: date,
) -> tuple[list[dict], list[dict], dict, str]:
    """Build flat leg records + parlay records.

    Returns (leg_records, parlay_records, segment_counts, authority).
      leg record:    {model, segment, seg_method, date, game_id, market, result, abs_edge}
      parlay record: {model, segment, date, game_id, result}
    """
    leg_records: list[dict] = []
    parlay_records: list[dict] = []
    segment_counts: dict[str, int] = defaultdict(int)
    method_counts: dict[str, int] = defaultdict(int)

    authority = DEFAULT_AUTHORITY
    for g in games:
        a = str(g.get("selection_authority") or "").strip()
        if a:
            authority = a
            break

    for g in games:
        seg, method = classify_segment(g, play_in_start, playoff_start)
        segment_counts[seg] += 1
        method_counts[method] += 1
        gdate = str(g.get("game_date") or "")[:10]
        gid = str(g.get("canonical_game_id") or g.get("game_id") or "").strip()

        for model_name, blob in _iter_model_results(g):
            for market, rkey, ekey in (
                ("spread", "spread_result", "spread_edge"),
                ("total", "total_result", "total_edge"),
            ):
                res = _norm_result(blob.get(rkey))
                if res is None:
                    continue
                edge = _safe_float(blob.get(ekey))
                leg_records.append({
                    "model": model_name,
                    "segment": seg,
                    "seg_method": method,
                    "date": gdate,
                    "game_id": gid,
                    "market": market,
                    "result": res,
                    "abs_edge": abs(edge) if edge is not None else None,
                })
            pres = _norm_result(blob.get("parlay_result"))
            if pres is not None:
                parlay_records.append({
                    "model": model_name,
                    "segment": seg,
                    "date": gdate,
                    "game_id": gid,
                    "result": pres,
                })

    return leg_records, parlay_records, dict(segment_counts), authority


# ============================================================================
# Aggregation
# ============================================================================

def aggregate(records: list[dict]) -> dict:
    """Aggregate WIN/LOSS/PUSH records into stats with -110 ROI."""
    wins = losses = pushes = 0
    profit = 0.0
    edges: list[float] = []
    for r in records:
        res = r["result"]
        profit += _profit_for_leg(res)
        if res == "WIN":
            wins += 1
        elif res == "LOSS":
            losses += 1
        else:
            pushes += 1
        ae = r.get("abs_edge")
        if ae is not None:
            edges.append(ae)
    graded = wins + losses + pushes
    decisions = wins + losses
    return {
        "graded": graded,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": round(wins / graded, 4) if graded else None,
        "win_rate_ex_push": round(wins / decisions, 4) if decisions else None,
        "roi": round(profit / graded, 4) if graded else None,
        "profit_units": round(profit, 4),
        "avg_edge": round(sum(edges) / len(edges), 4) if edges else None,
    }


def _filter(records: list[dict], *, model=None, market=None, segments=None) -> list[dict]:
    out = records
    if model is not None:
        out = [r for r in out if r["model"] == model]
    if market is not None:
        out = [r for r in out if r.get("market") == market]
    if segments is not None:
        seg_set = set(segments)
        out = [r for r in out if r["segment"] in seg_set]
    return out


# Segment groupings used across the report.
SEG_GROUPS = {
    "overall": ["regular", "play_in", "playoffs"],
    "regular": ["regular"],
    "play_in": ["play_in"],
    "playoffs": ["playoffs"],
    "postseason": ["play_in", "playoffs"],
}


def edge_bucket_user(abs_edge: float) -> str:
    """Edge buckets per recap spec: 0-1, 1-2, 2-4, 4-6, 6+."""
    if abs_edge < 1:
        return "0-1"
    if abs_edge < 2:
        return "1-2"
    if abs_edge < 4:
        return "2-4"
    if abs_edge < 6:
        return "4-6"
    return "6+"


# ============================================================================
# Analysis sections
# ============================================================================

def analyze_headline(leg_records, parlay_records, authority) -> dict:
    """Authority overall performance, by bet type, across segment groups."""
    out: dict[str, Any] = {"authority": authority}
    for group, segs in SEG_GROUPS.items():
        spread = aggregate(_filter(leg_records, model=authority, market="spread", segments=segs))
        total = aggregate(_filter(leg_records, model=authority, market="total", segments=segs))
        combined = aggregate(_filter(leg_records, model=authority, segments=segs))
        parlay = aggregate(_filter(parlay_records, model=authority, segments=segs))
        out[group] = {
            "spread": spread,
            "total": total,
            "combined_spread_total": combined,
            "parlay": parlay,
        }
    return out


def analyze_models(leg_records, parlay_records, min_sample) -> dict:
    models = sorted({r["model"] for r in leg_records})
    per_model: dict[str, Any] = {}
    for m in models:
        per_model[m] = {}
        for group, segs in SEG_GROUPS.items():
            per_model[m][group] = {
                "combined_spread_total": aggregate(_filter(leg_records, model=m, segments=segs)),
                "spread": aggregate(_filter(leg_records, model=m, market="spread", segments=segs)),
                "total": aggregate(_filter(leg_records, model=m, market="total", segments=segs)),
                "parlay": aggregate(_filter(parlay_records, model=m, segments=segs)),
            }

    def _best(group: str) -> Optional[dict]:
        ranked = [
            {"model": m, "roi": per_model[m][group]["combined_spread_total"]["roi"],
             "graded": per_model[m][group]["combined_spread_total"]["graded"]}
            for m in models
            if (per_model[m][group]["combined_spread_total"]["graded"] or 0) >= min_sample
            and per_model[m][group]["combined_spread_total"]["roi"] is not None
        ]
        ranked.sort(key=lambda r: r["roi"], reverse=True)
        return ranked[0] if ranked else None

    return {
        "models": models,
        "per_model": per_model,
        "best_overall": _best("overall"),
        "best_playoffs": _best("playoffs"),
        "best_postseason": _best("postseason"),
        "min_sample_size": min_sample,
    }


def analyze_calibration(leg_records, authority) -> dict:
    """Edge-size buckets for the authority, across segment groups + monotonicity."""
    buckets_order = ["0-1", "1-2", "2-4", "4-6", "6+"]
    result: dict[str, Any] = {"bucket_order": buckets_order}
    for group, segs in SEG_GROUPS.items():
        rows = [
            r for r in _filter(leg_records, model=authority, segments=segs)
            if r.get("abs_edge") is not None
        ]
        by_bucket: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_bucket[edge_bucket_user(r["abs_edge"])].append(r)
        group_tbl = {b: aggregate(by_bucket.get(b, [])) for b in buckets_order}
        result[group] = group_tbl

    # Monotonicity verdict on overall ROI across buckets (ignoring empty buckets).
    overall = result["overall"]
    seq = [(b, overall[b]["roi"]) for b in buckets_order if overall[b]["roi"] is not None]
    monotonic = None
    if len(seq) >= 2:
        rois = [v for _, v in seq]
        monotonic = all(rois[i] <= rois[i + 1] for i in range(len(rois) - 1))
    result["bigger_edge_better"] = monotonic
    return result


def analyze_confidence(games, leg_records, authority, play_in_start, playoff_start) -> Optional[dict]:
    """Optional: calibration by confidence tier if such a field exists on rows."""
    conf_field = None
    for g in games:
        for cand in ("confidence_tier", "confidence_classification", "confidence_reason"):
            if g.get(cand) not in (None, ""):
                conf_field = cand
                break
        if conf_field:
            break
    if not conf_field:
        return None

    # Build authority legs keyed by game_id -> confidence.
    conf_by_game: dict[str, str] = {}
    for g in games:
        gid = str(g.get("canonical_game_id") or g.get("game_id") or "").strip()
        cv = g.get(conf_field)
        if gid and cv not in (None, ""):
            conf_by_game[gid] = str(cv)

    by_conf: dict[str, list[dict]] = defaultdict(list)
    for r in _filter(leg_records, model=authority):
        cv = conf_by_game.get(r["game_id"])
        if cv:
            by_conf[cv].append(r)
    return {
        "confidence_field": conf_field,
        "by_confidence": {k: aggregate(v) for k, v in sorted(by_conf.items())},
    }


def analyze_pockets_overall(pockets_doc, combo_doc, min_sample, log) -> dict:
    """Rank season single-model and combo pockets from on-disk artifacts."""
    out: dict[str, Any] = {"min_sample_size": min_sample}

    singles = []
    if isinstance(pockets_doc, dict):
        for p in pockets_doc.get("pockets") or []:
            if not isinstance(p, dict):
                continue
            if int(p.get("graded_games") or 0) < min_sample:
                continue
            singles.append({
                "model": p.get("model"),
                "market_type": p.get("market_type"),
                "edge_bucket": p.get("edge_bucket"),
                "graded_games": int(p.get("graded_games") or 0),
                "win_rate": _safe_float(p.get("win_rate")),
                "roi": _safe_float(p.get("roi")),
                "state": p.get("state"),
            })
    singles.sort(key=lambda r: (r["roi"] if r["roi"] is not None else -1e9, r["graded_games"]), reverse=True)
    out["single_model_ranked"] = singles

    combos = []
    if isinstance(combo_doc, dict):
        for c in combo_doc.get("combo_pockets") or []:
            if not isinstance(c, dict):
                continue
            if int(c.get("graded_games") or 0) < min_sample:
                continue
            combos.append({
                "combo_kind": c.get("combo_kind"),
                "market_type": c.get("market_type"),
                "models_key": c.get("models_key"),
                "state_signature": c.get("state_signature"),
                "graded_games": int(c.get("graded_games") or 0),
                "win_rate": _safe_float(c.get("win_rate")),
                "roi": _safe_float(c.get("roi")),
                "state": c.get("state"),
            })
    combos.sort(key=lambda r: (r["roi"] if r["roi"] is not None else -1e9, r["graded_games"]), reverse=True)
    out["combo_ranked"] = combos
    return out


def analyze_pockets_by_segment(games, min_sample, play_in_start, playoff_start) -> dict:
    """Recompute SINGLE-MODEL pocket ROI per segment from backtest_games.

    Uses determine_band (same banding as the on-disk pockets) so segments join to
    season buckets by (model, market_type, edge_bucket). Combo per-segment split is
    intentionally out of scope (documented) to keep this minimal and safe.
    """
    # (model, market, band, group) -> list of {result, abs_edge}
    cells: dict[tuple, list[dict]] = defaultdict(list)
    for g in games:
        seg, _ = classify_segment(g, play_in_start, playoff_start)
        groups = [grp for grp, segs in SEG_GROUPS.items() if seg in segs]
        for model_name, blob in _iter_model_results(g):
            for market, rkey, ekey in (
                ("spread", "spread_result", "spread_edge"),
                ("total", "total_result", "total_edge"),
            ):
                edge = _safe_float(blob.get(ekey))
                if edge is None:
                    continue
                res = _norm_result(blob.get(rkey))
                if res is None:
                    continue
                band = determine_band(edge)
                rec = {"result": res, "abs_edge": abs(edge)}
                for grp in groups:
                    cells[(model_name, market, band, grp)].append(rec)

    keys = sorted({(m, mk, b) for (m, mk, b, _grp) in cells})
    rows: list[dict] = []
    flags_improved: list[dict] = []
    flags_reg_ok_po_fail: list[dict] = []

    for (m, mk, b) in keys:
        by_group = {}
        for grp in SEG_GROUPS:
            by_group[grp] = aggregate(cells.get((m, mk, b, grp), []))
        row = {"model": m, "market_type": mk, "edge_bucket": b, "by_group": by_group}
        rows.append(row)

        reg = by_group["regular"]
        po = by_group["postseason"]
        playoffs = by_group["playoffs"]

        if (reg["graded"] >= min_sample and playoffs["graded"] >= min_sample
                and reg["roi"] is not None and playoffs["roi"] is not None):
            if playoffs["roi"] > reg["roi"]:
                flags_improved.append({
                    "model": m, "market_type": mk, "edge_bucket": b,
                    "regular_roi": reg["roi"], "playoffs_roi": playoffs["roi"],
                    "regular_n": reg["graded"], "playoffs_n": playoffs["graded"],
                })
            if reg["roi"] > 0 and playoffs["roi"] <= 0:
                flags_reg_ok_po_fail.append({
                    "model": m, "market_type": mk, "edge_bucket": b,
                    "regular_roi": reg["roi"], "playoffs_roi": playoffs["roi"],
                    "regular_n": reg["graded"], "playoffs_n": playoffs["graded"],
                })
        # Postseason-combined variant of the "worked-regular, failed-after" flag.
        if (reg["graded"] >= min_sample and po["graded"] >= min_sample
                and reg["roi"] is not None and po["roi"] is not None
                and reg["roi"] > 0 and po["roi"] <= 0):
            flags_reg_ok_po_fail.append({
                "model": m, "market_type": mk, "edge_bucket": b,
                "regular_roi": reg["roi"], "playoffs_roi": po["roi"],
                "regular_n": reg["graded"], "playoffs_n": po["graded"],
                "scope": "postseason",
            })

    return {
        "min_sample_size": min_sample,
        "rows": rows,
        "improved_in_playoffs": sorted(
            flags_improved, key=lambda r: r["playoffs_roi"] - r["regular_roi"], reverse=True
        ),
        "regular_ok_postseason_fail": sorted(
            flags_reg_ok_po_fail, key=lambda r: r["regular_roi"] - r["playoffs_roi"], reverse=True
        ),
    }


def _overlay_bucket_for_row(g: dict) -> Optional[str]:
    overlay = g.get("execution_overlay")
    if not overlay:
        se = g.get("selected_spread_edge")
        if se is None:
            se = g.get("Spread Edge")
        te = g.get("selected_total_edge")
        if te is None:
            te = g.get("Total Edge")
        sh = g.get("market_spread_home") or g.get("spread_home") or g.get("spread_home_last")
        vt = g.get("market_total") or g.get("total") or g.get("total_last")
        overlay = compute_overlay_from_edges(se, te, sh, vt)
    if not overlay:
        return None
    return classify_overlay({"execution_overlay": overlay})


def analyze_overlay(games, overlay_season, overlay_dynamic, play_in_start, playoff_start) -> dict:
    """Recompute overlay buckets per segment group from rows (mirrors 039b leg accounting)."""
    # group -> bucket -> counters
    data: dict[str, dict[str, dict]] = {
        grp: {b: {"games": 0, "wins": 0, "losses": 0, "pushes": 0, "profit": 0.0} for b in OVERLAY_BUCKETS}
        for grp in SEG_GROUPS
    }

    for g in games:
        spread_result = _norm_result(g.get("selected_spread_result") or g.get("spread_result"))
        total_result = _norm_result(g.get("selected_total_result") or g.get("total_result"))
        if spread_result is None and total_result is None:
            continue
        bucket = _overlay_bucket_for_row(g)
        if bucket is None:
            continue
        seg, _ = classify_segment(g, play_in_start, playoff_start)
        groups = [grp for grp, segs in SEG_GROUPS.items() if seg in segs]
        for res in (spread_result, total_result):
            if res not in ("WIN", "LOSS", "PUSH"):
                continue
            for grp in groups:
                for key in (bucket, "All Games"):
                    cell = data[grp][key]
                    cell["games"] += 1
                    if res == "WIN":
                        cell["wins"] += 1
                        cell["profit"] += PAYOUT_MULTIPLIER
                    elif res == "LOSS":
                        cell["losses"] += 1
                        cell["profit"] -= 1.0
                    else:
                        cell["pushes"] += 1

    out: dict[str, Any] = {
        "season_artifact": overlay_season if isinstance(overlay_season, dict) else None,
        "dynamic_artifact": overlay_dynamic if isinstance(overlay_dynamic, dict) else None,
        "by_segment": {},
        "value_verdict": {},
    }
    for grp in SEG_GROUPS:
        tbl = {}
        for b in OVERLAY_BUCKETS:
            cell = data[grp][b]
            n = cell["games"]
            tbl[b] = {
                "games": n,
                "wins": cell["wins"],
                "losses": cell["losses"],
                "pushes": cell["pushes"],
                "win_rate": round(cell["wins"] / n, 4) if n else None,
                "roi": round(cell["profit"] / n, 4) if n else None,
            }
        out["by_segment"][grp] = tbl

        all_roi = tbl["All Games"]["roi"]
        sweet = [tbl[b]["roi"] for b in ("Dual Sweet Spot", "Spread Sweet Spot", "Total Sweet Spot")
                 if tbl[b]["roi"] is not None]
        avoid_roi = tbl["Avoid"]["roi"]
        verdict = None
        if all_roi is not None and sweet:
            best_sweet = max(sweet)
            sweet_beats_all = best_sweet > all_roi
            avoid_worse = (avoid_roi is None) or (avoid_roi < all_roi)
            if sweet_beats_all and avoid_worse:
                verdict = "added_value"
            elif sweet_beats_all or avoid_worse:
                verdict = "mixed"
            else:
                verdict = "no_value"
        out["value_verdict"][grp] = verdict
    return out


def analyze_daily(leg_records, authority, play_in_start, playoff_start) -> dict:
    """Per-date authority timeline."""
    by_date: dict[str, dict] = {}
    legs = _filter(leg_records, model=authority)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in legs:
        if r["date"]:
            grouped[r["date"]].append(r)

    rows: list[dict] = []
    for d in sorted(grouped):
        recs = grouped[d]
        stats = aggregate(recs)
        segs = sorted({r["segment"] for r in recs})
        seg_label = segs[0] if len(segs) == 1 else "mixed:" + "+".join(segs)
        games_n = len({r["game_id"] for r in recs})
        row = {
            "date": d,
            "segment": seg_label,
            "games": games_n,
            "picks": stats["graded"],
            "wins": stats["wins"],
            "losses": stats["losses"],
            "pushes": stats["pushes"],
            "win_rate": stats["win_rate"],
            "win_rate_ex_push": stats["win_rate_ex_push"],
            "roi": stats["roi"],
            "avg_edge": stats["avg_edge"],
            "is_postseason": any(s in ("play_in", "playoffs") for s in segs),
        }
        rows.append(row)
        by_date[d] = row

    rankable = [r for r in rows if r["picks"] >= 3 and r["roi"] is not None]
    best_day = max(rankable, key=lambda r: r["roi"]) if rankable else None
    worst_day = min(rankable, key=lambda r: r["roi"]) if rankable else None
    postseason_days = [r for r in rows if r["is_postseason"]]

    return {
        "rows": rows,
        "best_day": best_day,
        "worst_day": worst_day,
        "postseason_days": postseason_days,
        "min_picks_for_ranking": 3,
    }


# ============================================================================
# Narrative: What worked / failed / trust
# ============================================================================

def build_narrative(headline, models_an, pockets_seg, overlay_an, calib, authority) -> dict:
    worked: list[str] = []
    failed: list[str] = []
    trust: list[str] = []

    def _roi(group, market="combined_spread_total"):
        return headline.get(group, {}).get(market, {}).get("roi")

    reg_roi = _roi("regular")
    po_roi = _roi("postseason")
    pl_roi = _roi("playoffs")

    if reg_roi is not None:
        (worked if reg_roi > 0 else failed).append(
            f"Regular-season authority ({authority}) ROI {_fmt_roi(reg_roi)} "
            f"on {headline['regular']['combined_spread_total']['graded']} graded legs."
        )
    if po_roi is not None:
        (worked if po_roi > 0 else failed).append(
            f"Postseason (play-in + playoffs) authority ROI {_fmt_roi(po_roi)} "
            f"on {headline['postseason']['combined_spread_total']['graded']} graded legs."
        )
    if reg_roi is not None and po_roi is not None:
        if po_roi > reg_roi:
            worked.append(f"Model improved after the regular season ({_fmt_roi(reg_roi)} -> {_fmt_roi(po_roi)}).")
            trust.append("Postseason held up vs regular season; the edge did not collapse in the playoffs.")
        else:
            failed.append(f"Model regressed in the postseason ({_fmt_roi(reg_roi)} -> {_fmt_roi(po_roi)}).")
            trust.append("Treat postseason signals with caution next season; regular-season edge did not carry over.")

    # Bet-type read on overall.
    sp = _roi("overall", "spread")
    tot = _roi("overall", "total")
    par = headline.get("overall", {}).get("parlay", {}).get("roi")
    for label, val in (("spread", sp), ("total", tot), ("parlay", par)):
        if val is None:
            continue
        (worked if val > 0 else failed).append(f"Overall {label} ROI {_fmt_roi(val)}.")

    # Best models.
    bo = models_an.get("best_overall")
    bp = models_an.get("best_playoffs")
    if bo:
        trust.append(f"Best overall model by ROI: {bo['model']} ({_fmt_roi(bo['roi'])}, n={bo['graded']}).")
    if bp:
        trust.append(f"Best playoff model by ROI: {bp['model']} ({_fmt_roi(bp['roi'])}, n={bp['graded']}).")
    if bo and bp and bo["model"] != bp["model"]:
        trust.append(
            f"Regular-season leader ({bo['model']}) differs from playoff leader ({bp['model']}); "
            "do not assume the season-long best model is the playoff best."
        )

    # Calibration.
    if calib.get("bigger_edge_better") is True:
        worked.append("Edge calibration is monotonic overall: bigger edge buckets earned higher ROI.")
        trust.append("Edge size is a usable confidence proxy; larger edges were better.")
    elif calib.get("bigger_edge_better") is False:
        failed.append("Edge calibration is NOT monotonic: bigger edge did not reliably mean better ROI.")
        trust.append("Do not size purely by raw edge; the largest-edge buckets were not the most profitable.")

    # Pockets.
    imp = pockets_seg.get("improved_in_playoffs") or []
    fail_p = pockets_seg.get("regular_ok_postseason_fail") or []
    if imp:
        top = imp[0]
        worked.append(
            f"{len(imp)} pocket(s) improved in the playoffs; top: {top['model']} "
            f"{top['market_type']} {top['edge_bucket']} "
            f"({_fmt_roi(top['regular_roi'])} -> {_fmt_roi(top['playoffs_roi'])})."
        )
    if fail_p:
        top = fail_p[0]
        failed.append(
            f"{len(fail_p)} pocket(s) worked in the regular season but failed after; e.g. {top['model']} "
            f"{top['market_type']} {top['edge_bucket']} ({_fmt_roi(top['regular_roi'])} -> {_fmt_roi(top['playoffs_roi'])})."
        )
        trust.append("Re-validate the flagged regular-season pockets before trusting them in next year's postseason.")

    # Overlay.
    for grp in ("regular", "postseason", "playoffs"):
        v = overlay_an.get("value_verdict", {}).get(grp)
        if v == "added_value":
            worked.append(f"Execution overlay added value in {grp} (sweet spots beat All Games, Avoid was worse).")
        elif v == "no_value":
            failed.append(f"Execution overlay added no value in {grp} (sweet spots did not beat All Games).")

    if not worked:
        worked.append("No clearly positive segment/bet-type stood out (see tables).")
    if not failed:
        failed.append("No clearly negative segment/bet-type stood out (see tables).")
    if not trust:
        trust.append("Insufficient sample to make strong next-season recommendations; collect more graded games.")

    return {"worked": worked, "failed": failed, "trust": trust}


# ============================================================================
# Output writers
# ============================================================================

def _stat_md_row(label, s: dict) -> str:
    return (
        f"| {label} | {s['graded']} | {s['wins']}-{s['losses']}-{s['pushes']} | "
        f"{_fmt_pct(s['win_rate_ex_push'])} | {_fmt_roi(s['roi'])} | {_fmt_num(s['avg_edge'])} |"
    )


def write_markdown(path: Path, ctx: dict) -> None:
    L: list[str] = []
    a = ctx["headline"]["authority"]
    L.append("# NBA Season Recap")
    L.append("")
    L.append(f"- Generated (UTC): `{ctx['generated_at_utc']}`")
    L.append(f"- Backtest source: `{ctx['backtest_dir']}`")
    L.append(f"- Authority model: `{a}`")
    L.append(f"- Excluded models: `{', '.join(sorted(EXCLUDED_MODELS))}`")
    L.append(f"- ROI accounting: -110 (WIN +{PAYOUT_MULTIPLIER:.4f}u, LOSS -1u, PUSH 0u); "
             f"breakeven win rate ~{BREAKEVEN_WIN_RATE:.4f}")
    L.append(f"- Play-in start: `{ctx['play_in_start']}` | Playoff start: `{ctx['playoff_start']}` "
             f"| Min sample: `{ctx['min_sample_size']}`")
    L.append("")
    seg = ctx["segment_counts"]
    L.append("Segment game counts: " + ", ".join(f"**{k}**={v}" for k, v in sorted(seg.items())))
    L.append("")
    L.append("> Win% shown excludes pushes (wins / decisions). ROI denominator includes pushes "
             "(matches pocket/overlay accounting).")
    L.append("")

    # 1. Overall by bet type.
    L.append("## 1. Overall model performance (authority)")
    L.append("")
    L.append("| Bet type | Graded | W-L-P | Win% | ROI | Avg edge |")
    L.append("|---|---|---|---|---|---|")
    ov = ctx["headline"]["overall"]
    L.append(_stat_md_row("Spread", ov["spread"]))
    L.append(_stat_md_row("Total", ov["total"]))
    L.append(_stat_md_row("Spread+Total", ov["combined_spread_total"]))
    L.append(_stat_md_row("Parlay", ov["parlay"]))
    L.append("")
    L.append("_Moneyline is not graded anywhere in the pipeline, so ML performance is unavailable._")
    L.append("")

    # 2. Segment comparison.
    L.append("## 2. Regular vs play-in vs playoffs")
    L.append("")
    L.append("Spread+Total combined per segment:")
    L.append("")
    L.append("| Segment | Graded | W-L-P | Win% | ROI | Avg edge |")
    L.append("|---|---|---|---|---|---|")
    for grp, label in (("regular", "Regular"), ("play_in", "Play-In"), ("playoffs", "Playoffs"),
                       ("postseason", "Postseason (play-in+playoffs)"), ("overall", "Overall")):
        L.append(_stat_md_row(label, ctx["headline"][grp]["combined_spread_total"]))
    L.append("")
    L.append("Parlay per segment:")
    L.append("")
    L.append("| Segment | Graded | W-L-P | Win% | ROI | Avg edge |")
    L.append("|---|---|---|---|---|---|")
    for grp, label in (("regular", "Regular"), ("play_in", "Play-In"), ("playoffs", "Playoffs"),
                       ("postseason", "Postseason"), ("overall", "Overall")):
        L.append(_stat_md_row(label, ctx["headline"][grp]["parlay"]))
    L.append("")

    # 3. Pockets.
    L.append("## 3. Pocket performance")
    L.append("")
    po = ctx["pockets_overall"]
    L.append(f"Top single-model pockets (season, min sample {po['min_sample_size']}):")
    L.append("")
    L.append("| Model | Market | Bucket | n | Win% | ROI | State |")
    L.append("|---|---|---|---|---|---|---|")
    for r in po["single_model_ranked"][:12]:
        L.append(f"| {r['model']} | {r['market_type']} | {r['edge_bucket']} | {r['graded_games']} | "
                 f"{_fmt_pct(r['win_rate'])} | {_fmt_roi(r['roi'])} | {r['state']} |")
    if not po["single_model_ranked"]:
        L.append("| _(none above min sample)_ | | | | | | |")
    L.append("")
    L.append(f"Top combo pockets (season, min sample {po['min_sample_size']}):")
    L.append("")
    L.append("| Kind | Market | Models | n | Win% | ROI | State |")
    L.append("|---|---|---|---|---|---|---|")
    for r in po["combo_ranked"][:10]:
        L.append(f"| {r['combo_kind']} | {r['market_type']} | {r['models_key']} | {r['graded_games']} | "
                 f"{_fmt_pct(r['win_rate'])} | {_fmt_roi(r['roi'])} | {r['state']} |")
    if not po["combo_ranked"]:
        L.append("| _(none above min sample)_ | | | | | | |")
    L.append("")
    ps = ctx["pockets_segment"]
    L.append("**Pockets that improved in the playoffs** (regular ROI -> playoff ROI):")
    L.append("")
    if ps["improved_in_playoffs"]:
        L.append("| Model | Market | Bucket | Reg ROI (n) | Playoff ROI (n) |")
        L.append("|---|---|---|---|---|")
        for r in ps["improved_in_playoffs"][:12]:
            L.append(f"| {r['model']} | {r['market_type']} | {r['edge_bucket']} | "
                     f"{_fmt_roi(r['regular_roi'])} ({r['regular_n']}) | {_fmt_roi(r['playoffs_roi'])} ({r['playoffs_n']}) |")
    else:
        L.append("_None met the min-sample threshold in both segments._")
    L.append("")
    L.append("**Pockets that worked in the regular season but failed in the postseason:**")
    L.append("")
    if ps["regular_ok_postseason_fail"]:
        L.append("| Model | Market | Bucket | Reg ROI (n) | Post ROI (n) | Scope |")
        L.append("|---|---|---|---|---|---|")
        for r in ps["regular_ok_postseason_fail"][:12]:
            L.append(f"| {r['model']} | {r['market_type']} | {r['edge_bucket']} | "
                     f"{_fmt_roi(r['regular_roi'])} ({r['regular_n']}) | {_fmt_roi(r['playoffs_roi'])} ({r['playoffs_n']}) | "
                     f"{r.get('scope', 'playoffs')} |")
    else:
        L.append("_None met the min-sample threshold in both segments._")
    L.append("")
    L.append("_Per-segment pocket ROI is recomputed from `backtest_games.json` using the same edge banding "
             "as the on-disk pockets (single-model only). Per-segment combo splits are not attempted; "
             "the combo table above uses season totals._")
    L.append("")

    # 4. Execution overlay.
    L.append("## 4. Execution overlay performance")
    L.append("")
    for grp, label in (("regular", "Regular"), ("postseason", "Postseason"), ("playoffs", "Playoffs"),
                       ("overall", "Overall")):
        tbl = ctx["overlay"]["by_segment"][grp]
        verdict = ctx["overlay"]["value_verdict"].get(grp)
        L.append(f"### {label} (verdict: {verdict or 'n/a'})")
        L.append("")
        L.append("| Bucket | Games | Win% | ROI |")
        L.append("|---|---|---|---|")
        for b in OVERLAY_BUCKETS:
            c = tbl[b]
            L.append(f"| {b} | {c['games']} | {_fmt_pct(c['win_rate'])} | {_fmt_roi(c['roi'])} |")
        L.append("")

    # 5. Model comparison.
    L.append("## 5. Model comparison")
    L.append("")
    ma = ctx["models"]
    bo, bp = ma.get("best_overall"), ma.get("best_playoffs")
    L.append(f"- Best overall (ROI, n>={ma['min_sample_size']}): "
             + (f"**{bo['model']}** {_fmt_roi(bo['roi'])} (n={bo['graded']})" if bo else "n/a"))
    L.append(f"- Best in playoffs (ROI, n>={ma['min_sample_size']}): "
             + (f"**{bp['model']}** {_fmt_roi(bp['roi'])} (n={bp['graded']})" if bp else "n/a"))
    L.append("")
    L.append("Spread+Total combined ROI by model and segment:")
    L.append("")
    L.append("| Model | Reg ROI (n) | Play-in ROI (n) | Playoff ROI (n) | Post ROI (n) | Overall ROI (n) |")
    L.append("|---|---|---|---|---|---|")
    for m in ma["models"]:
        pm = ma["per_model"][m]

        def cell(grp):
            s = pm[grp]["combined_spread_total"]
            return f"{_fmt_roi(s['roi'])} ({s['graded']})"
        star = " *(authority)*" if m == a else ""
        L.append(f"| {m}{star} | {cell('regular')} | {cell('play_in')} | {cell('playoffs')} | "
                 f"{cell('postseason')} | {cell('overall')} |")
    L.append("")

    # 6. Accuracy & calibration.
    L.append("## 6. Accuracy & calibration (authority, by edge size)")
    L.append("")
    cal = ctx["calibration"]
    for grp, label in (("overall", "Overall"), ("regular", "Regular"), ("postseason", "Postseason"),
                       ("playoffs", "Playoffs")):
        L.append(f"### {label}")
        L.append("")
        L.append("| Edge bucket | Graded | W-L-P | Win% | ROI | Avg edge |")
        L.append("|---|---|---|---|---|---|")
        for b in cal["bucket_order"]:
            L.append(_stat_md_row(b, cal[grp][b]))
        L.append("")
    bm = cal.get("bigger_edge_better")
    L.append(f"**Bigger edge => better ROI (overall, monotonic)?** "
             f"{'Yes' if bm is True else 'No' if bm is False else 'Inconclusive'}")
    L.append("")
    if ctx.get("confidence"):
        cf = ctx["confidence"]
        L.append(f"### Calibration by confidence (`{cf['confidence_field']}`)")
        L.append("")
        L.append("| Confidence | Graded | W-L-P | Win% | ROI |")
        L.append("|---|---|---|---|---|")
        for k, s in cf["by_confidence"].items():
            L.append(f"| {k} | {s['graded']} | {s['wins']}-{s['losses']}-{s['pushes']} | "
                     f"{_fmt_pct(s['win_rate_ex_push'])} | {_fmt_roi(s['roi'])} |")
        L.append("")
    else:
        L.append("_No usable confidence/probability field found on backtest rows; confidence calibration skipped._")
        L.append("")

    # 7. Daily timeline.
    L.append("## 7. Daily timeline")
    L.append("")
    daily = ctx["daily"]
    bd, wd = daily["best_day"], daily["worst_day"]
    L.append(f"- Best day (>= {daily['min_picks_for_ranking']} picks): "
             + (f"`{bd['date']}` ROI {_fmt_roi(bd['roi'])} ({bd['wins']}-{bd['losses']}-{bd['pushes']})" if bd else "n/a"))
    L.append(f"- Worst day (>= {daily['min_picks_for_ranking']} picks): "
             + (f"`{wd['date']}` ROI {_fmt_roi(wd['roi'])} ({wd['wins']}-{wd['losses']}-{wd['pushes']})" if wd else "n/a"))
    L.append(f"- Postseason days: {len(daily['postseason_days'])}")
    L.append("")
    L.append("Full daily detail is in `season_recap_daily.csv`. Postseason days:")
    L.append("")
    if daily["postseason_days"]:
        L.append("| Date | Segment | Picks | W-L-P | Win% | ROI |")
        L.append("|---|---|---|---|---|---|")
        for r in daily["postseason_days"]:
            L.append(f"| {r['date']} | {r['segment']} | {r['picks']} | "
                     f"{r['wins']}-{r['losses']}-{r['pushes']} | {_fmt_pct(r['win_rate_ex_push'])} | {_fmt_roi(r['roi'])} |")
    else:
        L.append("_No postseason days in this dataset._")
    L.append("")

    # 8. Narrative.
    nar = ctx["narrative"]
    L.append("## 8. What worked / What failed / What to trust next season")
    L.append("")
    L.append("### What worked")
    for b in nar["worked"]:
        L.append(f"- {b}")
    L.append("")
    L.append("### What failed")
    for b in nar["failed"]:
        L.append(f"- {b}")
    L.append("")
    L.append("### What to trust next season")
    for b in nar["trust"]:
        L.append(f"- {b}")
    L.append("")

    # 9. Assumptions / caveats.
    L.append("## 9. Assumptions & data caveats")
    L.append("")
    for line in ctx["load_log"]:
        L.append(f"- {line}")
    L.append(f"- Segment classification methods used (game counts): "
             + ", ".join(f"{k}={v}" for k, v in sorted(ctx['method_counts'].items())))
    L.append("- Segments `preseason` and `unknown` are excluded from headline comparisons.")
    L.append("- Play-in is separated from playoffs via a documented date-window overlay because "
             "`season_type`/`game_id` (004) cannot distinguish the play-in tournament.")
    L.append("- Moneyline is not graded by the pipeline; only spread, total, and parlay are available.")
    L.append("- ROI uses -110 pricing; this recap reads graded artifacts and does not place or price real bets.")
    L.append("")

    path.write_text("\n".join(L), encoding="utf-8")


def write_daily_csv(path: Path, daily: dict) -> None:
    fields = ["date", "segment", "games", "picks", "wins", "losses", "pushes",
              "win_rate", "win_rate_ex_push", "roi", "avg_edge", "is_postseason"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in daily["rows"]:
            w.writerow({k: r.get(k) for k in fields})


def write_pockets_csv(path: Path, pockets_overall: dict, pockets_segment: dict) -> None:
    fields = ["scope", "model_or_models", "market_type", "bucket_or_signature", "segment",
              "graded_games", "win_rate", "roi", "state"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in pockets_overall["single_model_ranked"]:
            w.writerow({
                "scope": "single_model", "model_or_models": r["model"], "market_type": r["market_type"],
                "bucket_or_signature": r["edge_bucket"], "segment": "season",
                "graded_games": r["graded_games"], "win_rate": r["win_rate"], "roi": r["roi"], "state": r["state"],
            })
        for r in pockets_overall["combo_ranked"]:
            w.writerow({
                "scope": "combo", "model_or_models": r["models_key"], "market_type": r["market_type"],
                "bucket_or_signature": r["state_signature"], "segment": "season",
                "graded_games": r["graded_games"], "win_rate": r["win_rate"], "roi": r["roi"], "state": r["state"],
            })
        for row in pockets_segment["rows"]:
            for grp in ("regular", "play_in", "playoffs", "postseason", "overall"):
                s = row["by_group"][grp]
                if s["graded"] == 0:
                    continue
                w.writerow({
                    "scope": "single_model_segment", "model_or_models": row["model"],
                    "market_type": row["market_type"], "bucket_or_signature": row["edge_bucket"],
                    "segment": grp, "graded_games": s["graded"], "win_rate": s["win_rate_ex_push"],
                    "roi": s["roi"], "state": "",
                })


def write_model_comparison_csv(path: Path, models_an: dict) -> None:
    fields = ["model", "segment", "market", "graded", "wins", "losses", "pushes",
              "win_rate", "win_rate_ex_push", "roi", "avg_edge"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for m in models_an["models"]:
            pm = models_an["per_model"][m]
            for grp in ("regular", "play_in", "playoffs", "postseason", "overall"):
                for market in ("spread", "total", "combined_spread_total", "parlay"):
                    s = pm[grp][market]
                    w.writerow({
                        "model": m, "segment": grp, "market": market,
                        "graded": s["graded"], "wins": s["wins"], "losses": s["losses"], "pushes": s["pushes"],
                        "win_rate": s["win_rate"], "win_rate_ex_push": s["win_rate_ex_push"],
                        "roi": s["roi"], "avg_edge": s["avg_edge"],
                    })


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="NBA season recap (read-only).")
    parser.add_argument("--play-in-start-date", default=DEFAULT_PLAY_IN_START,
                        help=f"Play-in start (YYYY-MM-DD). Default {DEFAULT_PLAY_IN_START}.")
    parser.add_argument("--playoff-start-date", default=DEFAULT_PLAYOFF_START,
                        help=f"Playoff start (YYYY-MM-DD). Default {DEFAULT_PLAYOFF_START}.")
    parser.add_argument("--min-sample-size", type=int, default=20,
                        help="Minimum graded sample for pocket/model ranking. Default 20.")
    parser.add_argument("--backtest-dir", default=None,
                        help="Use this backtest folder instead of latest by mtime.")
    args = parser.parse_args()

    play_in_start = _parse_iso_date(args.play_in_start_date)
    playoff_start = _parse_iso_date(args.playoff_start_date)
    if play_in_start is None or playoff_start is None:
        print("ERROR: invalid date(s). Use YYYY-MM-DD.")
        return 2
    if play_in_start > playoff_start:
        print("ERROR: --play-in-start-date must be on/before --playoff-start-date.")
        return 2

    load_log: list[str] = []

    try:
        bt_dir = resolve_backtest_dir(args.backtest_dir, load_log)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1

    games = _load_json_safe(bt_dir / "backtest_games.json", load_log)
    if not isinstance(games, list) or not games:
        print(f"ERROR: backtest_games.json missing, corrupt, or empty in {bt_dir}")
        for line in load_log:
            print(f"  {line}")
        return 1

    # Optional artifacts.
    pockets_doc = _load_json_safe(bt_dir / "nba_model_pockets.json", load_log)
    combo_doc = _load_json_safe(bt_dir / "nba_model_combo_pockets.json", load_log)
    for name in ("nba_live_pocket_leaderboard.json", "nba_best_pocket_per_game.json",
                 "nba_ranked_pocket_opportunities.json", "nba_pocket_leaderboard_validation.json"):
        _load_json_safe(bt_dir / name, load_log)  # logged for the report; not required downstream
    overlay_season = _load_json_safe(bt_dir / "execution_overlay_performance.json", load_log)
    overlay_dynamic = _load_json_safe(bt_dir / "execution_overlay_performance_dynamic.json", load_log)

    # Analysis.
    leg_records, parlay_records, segment_counts, authority = build_records(games, play_in_start, playoff_start)
    method_counts: dict[str, int] = defaultdict(int)
    for g in games:
        _seg, method = classify_segment(g, play_in_start, playoff_start)
        method_counts[method] += 1

    headline = analyze_headline(leg_records, parlay_records, authority)
    models_an = analyze_models(leg_records, parlay_records, args.min_sample_size)
    calibration = analyze_calibration(leg_records, authority)
    confidence = analyze_confidence(games, leg_records, authority, play_in_start, playoff_start)
    pockets_overall = analyze_pockets_overall(pockets_doc, combo_doc, args.min_sample_size, load_log)
    pockets_segment = analyze_pockets_by_segment(games, args.min_sample_size, play_in_start, playoff_start)
    overlay_an = analyze_overlay(games, overlay_season, overlay_dynamic, play_in_start, playoff_start)
    daily = analyze_daily(leg_records, authority, play_in_start, playoff_start)
    narrative = build_narrative(headline, models_an, pockets_segment, overlay_an, calibration, authority)

    generated_at_utc = datetime.now(timezone.utc).isoformat()
    ctx = {
        "generated_at_utc": generated_at_utc,
        "backtest_dir": bt_dir.name,
        "play_in_start": args.play_in_start_date,
        "playoff_start": args.playoff_start_date,
        "min_sample_size": args.min_sample_size,
        "segment_counts": segment_counts,
        "method_counts": dict(method_counts),
        "load_log": load_log,
        "headline": headline,
        "models": models_an,
        "calibration": calibration,
        "confidence": confidence,
        "pockets_overall": pockets_overall,
        "pockets_segment": pockets_segment,
        "overlay": overlay_an,
        "daily": daily,
        "narrative": narrative,
    }

    # Outputs (new folder only).
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / "data" / LEAGUE / "analysis" / f"season_recap_{run_ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    write_markdown(out_dir / "season_recap_summary.md", ctx)
    with (out_dir / "season_recap_tables.json").open("w", encoding="utf-8") as f:
        json.dump(ctx, f, indent=2, default=str)
    write_daily_csv(out_dir / "season_recap_daily.csv", daily)
    write_pockets_csv(out_dir / "season_recap_pockets.csv", pockets_overall, pockets_segment)
    write_model_comparison_csv(out_dir / "season_recap_model_comparison.csv", models_an)

    print("NBA season recap written:")
    print(f"  Backtest source : {bt_dir.name}")
    print(f"  Output dir      : {out_dir}")
    print(f"  Segments        : " + ", ".join(f"{k}={v}" for k, v in sorted(segment_counts.items())))
    print(f"  Files           : season_recap_summary.md, season_recap_tables.json, "
          f"season_recap_daily.csv, season_recap_pockets.csv, season_recap_model_comparison.csv")
    for line in load_log:
        print(f"  log: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
