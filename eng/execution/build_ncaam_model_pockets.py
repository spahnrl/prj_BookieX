"""
build_ncaam_model_pockets.py — NCAAM only.

Invoked after backtests exist (e.g. 000_RUN_ALL_NCAAM after backtest + 039b).

Reads the latest NCAAM backtest_games.json and writes artifacts into that
backtest directory (forward-only; does not mutate backtest rows):

- ncaam_model_pockets.json
- ncaam_model_combo_pockets.json
- ncaam_current_game_pocket_view.json (all games in final_game_view)
- ncaam_live_game_pocket_view.json (slate slice from latest daily_view_ncaam_*_v1.json)
- ncaam_live_pocket_leaderboard.json (ranked live-slate views from live pocket + daily picks)
- ncaam_best_pocket_per_game.json (one consolidated spread-pocket row per live-slate game for UI)
- ncaam_ranked_pocket_opportunities.json (all ROI-backed pocket candidates on the live slate, one row each)

Uses all models present in backtest rows (NCAAM registry: avg, momentum5, market_pressure — no NBA-only exclusions).
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eng.execution.build_execution_overlay import determine_band
from utils.io_helpers import (
    get_backtest_output_root,
    get_daily_view_output_dir,
    get_final_view_json_path,
)

LEAGUE = "ncaam"
EXCLUDED_MODELS: frozenset[str] = frozenset()

# Match analysis_039b_execution_overlay_performance (-110).
BET_PRICE = -110
PAYOUT_MULTIPLIER = 100 / abs(BET_PRICE)

# State thresholds (documented in artifact metadata).
MIN_GRADED_FOR_STATE = 15
MIN_GRADED_HOT = 25
HOT_WIN_RATE = 0.545
HOT_ROI = 0.035
COLD_WIN_RATE = 0.515
COLD_ROI = -0.03
MIN_COMBO_GRADED = 30

BREAKEVEN_WIN_RATE = 100 / (100 + abs(BET_PRICE))  # ~0.52381


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _ncaam_latest_daily_view_slate_order() -> tuple[Path | None, str | None, list[str], dict]:
    """
    Same convention as bookiex_dashboard: daily_view_ncaam_{YYYY-MM-DD}_v1.json under NCAAM daily dir.
    Date key is parts[3] (daily_view_ncaam_2026-03-12_v1.json).
    Picks the lexicographically greatest date, then newest mtime within that date (matches date_map rule).
    Returns (path, slate_date from JSON or filename, ordered game_id list, daily doc dict or {}).
    """
    daily_dir = get_daily_view_output_dir(LEAGUE)
    if not daily_dir.exists():
        return None, None, [], {}
    files = list(daily_dir.glob("daily_view_ncaam_*_v1.json"))
    if not files:
        return None, None, [], {}
    by_date: dict[str, list[Path]] = defaultdict(list)
    for f in files:
        parts = f.name.split("_")
        if len(parts) < 5:
            continue
        dkey = parts[3]
        by_date[dkey].append(f)
    if not by_date:
        return None, None, [], {}
    latest_d = max(by_date.keys())
    best_file = max(by_date[latest_d], key=lambda p: p.stat().st_mtime)
    try:
        doc = _load_json(best_file)
    except (OSError, json.JSONDecodeError):
        return best_file, latest_d, [], {}
    if not isinstance(doc, dict):
        return best_file, latest_d, [], {}
    slate_date = doc.get("date")
    if slate_date is not None and str(slate_date).strip():
        slate_date_str = str(slate_date).strip()
    else:
        slate_date_str = latest_d
    order: list[str] = []
    for g in doc.get("games") or []:
        if not isinstance(g, dict):
            continue
        ident = g.get("identity") if isinstance(g.get("identity"), dict) else {}
        gid = str(
            ident.get("game_id")
            or g.get("game_id")
            or g.get("canonical_game_id")
            or g.get("espn_game_id")
            or ""
        ).strip()
        if gid:
            order.append(gid)
    return best_file, slate_date_str, order, doc


def _state_rank(state: str | None) -> int:
    return {"hot": 3, "warm": 2, "cold": 1, "insufficient": 0}.get((state or "").strip().lower(), 0)


def _cluster_alignment_score(align: dict) -> float:
    """Higher = stronger hot/warm concentration on the slate for one market."""
    if not isinstance(align, dict):
        return 0.0
    h = int(align.get("hot") or 0)
    w = int(align.get("warm") or 0)
    c = int(align.get("cold") or 0)
    ins = int(align.get("insufficient") or 0)
    return 3.0 * h + 1.0 * w - 0.5 * c - 0.25 * ins


def _daily_picks_for_game(daily_by_id: dict[str, dict], game_id: str) -> tuple[str | None, str | None]:
    g = daily_by_id.get(game_id) or {}
    mo = g.get("model_output") if isinstance(g.get("model_output"), dict) else {}
    sp = mo.get("spread_pick")
    tp = mo.get("total_pick")
    sp = str(sp).strip() if sp not in (None, "") else None
    tp = str(tp).strip() if tp not in (None, "") else None
    return sp, tp


def _build_ncaam_live_pocket_leaderboard(
    live_rows: list[dict],
    daily_doc: dict,
    *,
    source_backtest_dir: str,
    slate_date: str | None,
    source_live_slate_path: str | None,
) -> dict:
    """
    Ranked views derived from ncaam_live_game_pocket_view rows + same-day daily view for authority picks only.
    """
    daily_by_id: dict[str, dict] = {}
    for g in (daily_doc or {}).get("games") or []:
        if not isinstance(g, dict):
            continue
        ident = g.get("identity") if isinstance(g.get("identity"), dict) else {}
        gid = str(
            ident.get("game_id")
            or g.get("game_id")
            or g.get("canonical_game_id")
            or g.get("espn_game_id")
            or ""
        ).strip()
        if gid:
            daily_by_id[gid] = g

    scoring_doc = {
        "single_model": (
            "leaderboard_score = 1000 * state_rank + 10*spread_hot + 4*spread_warm - 2*spread_cold "
            "+ min(abs_edge, 20); state_rank hot=3 warm=2 cold=1 insufficient=0. "
            "Uses per_model pocket state and game-level spread_pocket_alignment only (no per-game ROI)."
        ),
        "combo": (
            "leaderboard_score = 10000 * roi + 3 * graded_games + combo_state_weight; "
            "combo_state_weight hot=400 warm=150 cold=0 insufficient=0; roi from historical combo pocket."
        ),
        "cluster": (
            "cluster_score = 3*hot + 1*warm - 0.5*cold - 0.25*insufficient on spread or total alignment counts."
        ),
        "cold_warnings": (
            "warning_score = 5*cold + 2*insufficient - 3*hot - 1*warm on spread alignment (higher = more caution)."
        ),
        "pass_candidates": (
            "Games with spread cluster_score <= 0 and (no best_pair_spread or best_pair_spread.roi < 0)."
        ),
    }

    best_single_spread: list[dict] = []
    best_single_total: list[dict] = []
    for gr in live_rows:
        if not isinstance(gr, dict):
            continue
        gid = str(gr.get("game_id") or "").strip()
        mu = gr.get("matchup") or ""
        spa = gr.get("spread_pocket_alignment") or {}
        tpa = gr.get("total_pocket_alignment") or {}
        spread_pick, total_pick = _daily_picks_for_game(daily_by_id, gid)
        pm = gr.get("per_model") or {}
        if not isinstance(pm, dict):
            continue
        for mname, blob in pm.items():
            if mname in EXCLUDED_MODELS or not isinstance(blob, dict):
                continue
            for market, align, _ in (
                ("spread", spa, spread_pick),
                ("total", tpa, total_pick),
            ):
                leg = blob.get(market) if isinstance(blob.get(market), dict) else None
                if not leg:
                    continue
                pst = leg.get("state") or "insufficient"
                sr = _state_rank(pst)
                al = align if isinstance(align, dict) else {}
                h, w, c = int(al.get("hot") or 0), int(al.get("warm") or 0), int(al.get("cold") or 0)
                ins_ct = int(al.get("insufficient") or 0)
                ae = float(leg.get("abs_edge") or 0)
                score = 1000 * sr + 10 * h + 4 * w - 2 * c + min(ae, 20.0)
                row = {
                    "game_id": gid,
                    "matchup": mu,
                    "market": market,
                    "model": mname,
                    "edge_bucket": leg.get("edge_bucket"),
                    "abs_edge": round(ae, 4),
                    "pocket_state": pst,
                    "spread_pick": spread_pick if market == "spread" else None,
                    "total_pick": total_pick if market == "total" else None,
                    "roi": None,
                    "win_rate": None,
                    "graded_games": None,
                    "state_signature": None,
                    "spread_pocket_alignment": dict(spa) if isinstance(spa, dict) else {},
                    "total_pocket_alignment": dict(tpa) if isinstance(tpa, dict) else {},
                    "leaderboard_score": round(score, 4),
                    "reason": (
                        f"{mname} {market} pocket state={pst} (bucket {leg.get('edge_bucket')}); "
                        f"slate {market} alignment H/W/C/I={h}/{w}/{c}/{ins_ct}."
                    ),
                }
                if market == "spread":
                    best_single_spread.append(row)
                else:
                    best_single_total.append(row)

    best_single_spread.sort(key=lambda r: (-r["leaderboard_score"], -(r.get("abs_edge") or 0)))
    best_single_total.sort(key=lambda r: (-r["leaderboard_score"], -(r.get("abs_edge") or 0)))
    for i, r in enumerate(best_single_spread, start=1):
        r["rank"] = i
    for i, r in enumerate(best_single_total, start=1):
        r["rank"] = i

    def _combo_rows(key: str) -> list[dict]:
        out: list[dict] = []
        for gr in live_rows:
            if not isinstance(gr, dict):
                continue
            c = gr.get(key)
            if not isinstance(c, dict):
                continue
            gid = str(gr.get("game_id") or "").strip()
            spread_pick, total_pick = _daily_picks_for_game(daily_by_id, gid)
            roi = c.get("roi")
            graded = int(c.get("graded_games") or 0)
            cst = c.get("state") or "insufficient"
            sw = {"hot": 400, "warm": 150, "cold": 0, "insufficient": 0}.get(str(cst).lower(), 0)
            rv = float(roi) if roi is not None else -1.0
            score = 10000.0 * rv + 3 * graded + sw
            mkt = c.get("market_type") or ("spread" if "spread" in key else "total")
            out.append(
                {
                    "game_id": gid,
                    "matchup": gr.get("matchup") or "",
                    "market": mkt,
                    "combo_kind": c.get("combo_kind"),
                    "models_key": c.get("models_key"),
                    "state_signature": c.get("state_signature"),
                    "spread_pick": spread_pick if mkt == "spread" else None,
                    "total_pick": total_pick if mkt == "total" else None,
                    "roi": roi,
                    "win_rate": c.get("win_rate"),
                    "graded_games": graded,
                    "combo_state": cst,
                    "spread_pocket_alignment": dict(gr.get("spread_pocket_alignment") or {}),
                    "total_pocket_alignment": dict(gr.get("total_pocket_alignment") or {}),
                    "leaderboard_score": round(score, 4),
                    "reason": (
                        f"Historical {c.get('combo_kind')} {mkt} ROI={roi} over {graded} graded combo legs; "
                        f"pocket state={cst} for signature match."
                    ),
                }
            )
        out.sort(key=lambda r: (-r["leaderboard_score"], -r["graded_games"]))
        for i, r in enumerate(out, start=1):
            r["rank"] = i
        return out

    best_pair_spread = _combo_rows("best_pair_spread")
    best_pair_total = _combo_rows("best_pair_total")
    best_triple_spread = _combo_rows("best_triple_spread")
    best_triple_total = _combo_rows("best_triple_total")

    strongest_spread_cluster: list[dict] = []
    strongest_total_cluster: list[dict] = []
    cold_cluster_warnings: list[dict] = []
    pass_candidates: list[dict] = []

    for gr in live_rows:
        if not isinstance(gr, dict):
            continue
        gid = str(gr.get("game_id") or "").strip()
        spread_pick, total_pick = _daily_picks_for_game(daily_by_id, gid)
        spa = gr.get("spread_pocket_alignment") or {}
        tpa = gr.get("total_pocket_alignment") or {}
        scs = _cluster_alignment_score(spa)
        tcs = _cluster_alignment_score(tpa)
        warn = (
            5 * int(spa.get("cold") or 0)
            + 2 * int(spa.get("insufficient") or 0)
            - 3 * int(spa.get("hot") or 0)
            - int(spa.get("warm") or 0)
        )
        bps = gr.get("best_pair_spread")
        bps_roi = bps.get("roi") if isinstance(bps, dict) else None

        strongest_spread_cluster.append(
            {
                "game_id": gid,
                "matchup": gr.get("matchup") or "",
                "spread_pick": spread_pick,
                "spread_pocket_alignment": dict(spa) if isinstance(spa, dict) else {},
                "cluster_score": round(scs, 4),
                "leaderboard_score": round(scs, 4),
                "reason": "Slate spread pocket state mix (hot/warm/cold/insufficient) for this game.",
            }
        )
        strongest_total_cluster.append(
            {
                "game_id": gid,
                "matchup": gr.get("matchup") or "",
                "total_pick": total_pick,
                "total_pocket_alignment": dict(tpa) if isinstance(tpa, dict) else {},
                "cluster_score": round(tcs, 4),
                "leaderboard_score": round(tcs, 4),
                "reason": "Slate total pocket state mix (hot/warm/cold/insufficient) for this game.",
            }
        )
        cold_cluster_warnings.append(
            {
                "game_id": gid,
                "matchup": gr.get("matchup") or "",
                "spread_pocket_alignment": dict(spa) if isinstance(spa, dict) else {},
                "total_pocket_alignment": dict(tpa) if isinstance(tpa, dict) else {},
                "warning_score": round(float(warn), 4),
                "leaderboard_score": round(float(warn), 4),
                "reason": "Higher warning_score = more spread-side cold/insufficient vs hot/warm on this slate.",
            }
        )
        weak_spread = scs <= 0.0
        weak_pair = bps_roi is None or (isinstance(bps_roi, (int, float)) and float(bps_roi) < 0)
        if weak_spread and weak_pair:
            pass_candidates.append(
                {
                    "game_id": gid,
                    "matchup": gr.get("matchup") or "",
                    "spread_pick": spread_pick,
                    "total_pick": total_pick,
                    "spread_cluster_score": round(scs, 4),
                    "best_pair_spread_roi": bps_roi,
                    "spread_pocket_alignment": dict(spa) if isinstance(spa, dict) else {},
                    "leaderboard_score": round(-scs + (float(bps_roi) if bps_roi is not None else -1.0), 4),
                    "reason": "Weak spread cluster and no positive historical best-pair spread pocket (or missing pair).",
                }
            )

    strongest_spread_cluster.sort(key=lambda r: -r["cluster_score"])
    strongest_total_cluster.sort(key=lambda r: -r["cluster_score"])
    cold_cluster_warnings.sort(key=lambda r: -r["warning_score"])
    pass_candidates.sort(key=lambda r: -r["leaderboard_score"])

    for i, r in enumerate(strongest_spread_cluster, start=1):
        r["rank"] = i
    for i, r in enumerate(strongest_total_cluster, start=1):
        r["rank"] = i
    for i, r in enumerate(cold_cluster_warnings, start=1):
        r["rank"] = i
    for i, r in enumerate(pass_candidates, start=1):
        r["rank"] = i

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "league": LEAGUE,
        "source_backtest_dir": source_backtest_dir,
        "source_live_pocket_artifact": "ncaam_live_game_pocket_view.json",
        "source_daily_view_path": source_live_slate_path,
        "slate_date": slate_date,
        "game_count": len(live_rows),
        "scoring": scoring_doc,
        "best_single_model_spread": best_single_spread,
        "best_single_model_total": best_single_total,
        "best_pair_spread": best_pair_spread,
        "best_pair_total": best_pair_total,
        "best_triple_spread": best_triple_spread,
        "best_triple_total": best_triple_total,
        "strongest_spread_cluster": strongest_spread_cluster,
        "strongest_total_cluster": strongest_total_cluster,
        "cold_cluster_warnings": cold_cluster_warnings,
        "pass_candidates": pass_candidates,
    }


def _latest_backtest_dir(league: str) -> tuple[Path, Path]:
    root = get_backtest_output_root(league)
    if not root.exists():
        raise FileNotFoundError(f"Backtest root not found: {root}")
    subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
    if not subdirs:
        raise FileNotFoundError(f"No backtest_* directories in {root}")
    latest = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest, latest / "backtest_games.json"


def _safe_float(v: Any) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bpp_alignment_hci(align: Any) -> str:
    if not isinstance(align, dict):
        return ""
    return (
        f"H{int(align.get('hot') or 0)}/W{int(align.get('warm') or 0)}/"
        f"C{int(align.get('cold') or 0)}/I{int(align.get('insufficient') or 0)}"
    )


def build_ncaam_ranked_pocket_opportunities(lb_doc: dict, single_pocket_rows: list[dict]) -> dict:
    """
    One row per historical pocket opportunity on the live slate (combos + joined single-model).
    Sorted by ROI, then graded_games, then win_rate (all descending). No authority changes.
    Cluster-only rows are omitted (no ROI on leaderboard). Single-model rows join ncaam_model_pockets
    by (model, market_type, edge_bucket).
    """
    if not isinstance(lb_doc, dict):
        return {}

    lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in single_pocket_rows or []:
        if not isinstance(r, dict):
            continue
        m = r.get("model")
        mt = r.get("market_type")
        b = r.get("edge_bucket")
        if m is None or mt is None or b is None:
            continue
        key = (str(m).strip(), str(mt).strip().lower(), str(b).strip())
        lookup[key] = {
            "roi": _safe_float(r.get("roi")),
            "win_rate": _safe_float(r.get("win_rate")),
            "graded_games": int(r.get("graded_games") or 0),
            "state": r.get("state"),
        }

    out_rows: list[dict[str, Any]] = []

    def _append_combo(rows: Any, pocket_type: str) -> None:
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            gr = int(row.get("graded_games") or 0)
            if gr <= 0:
                continue
            roi = _safe_float(row.get("roi"))
            wr = _safe_float(row.get("win_rate"))
            mkt = str(row.get("market") or "").strip().lower()
            if mkt not in ("spread", "total"):
                mkt = "spread" if "spread" in pocket_type else "total"
            pick = row.get("spread_pick") if mkt == "spread" else row.get("total_pick")
            pick_s = str(pick).strip() if pick not in (None, "") else None
            eligible = mkt == "spread" and roi is not None and roi > 0.0 and bool(pick_s)
            gid = str(row.get("game_id") or "").strip()
            if not gid:
                continue
            out_rows.append(
                {
                    "game_id": gid,
                    "matchup": row.get("matchup") or "",
                    "market_type": mkt,
                    "pick": pick_s,
                    "pocket_type": pocket_type,
                    "model_name": None,
                    "models_key": row.get("models_key"),
                    "state_signature": row.get("state_signature"),
                    "roi": roi,
                    "win_rate": wr,
                    "graded_games": gr,
                    "combo_state": row.get("combo_state"),
                    "reason": ((row.get("reason") or "").strip())[:400],
                    "eligible_for_parlay": eligible,
                }
            )

    _append_combo(lb_doc.get("best_pair_spread"), "pair_spread")
    _append_combo(lb_doc.get("best_triple_spread"), "triple_spread")
    _append_combo(lb_doc.get("best_pair_total"), "pair_total")
    _append_combo(lb_doc.get("best_triple_total"), "triple_total")

    for row in lb_doc.get("best_single_model_spread") or []:
        if not isinstance(row, dict):
            continue
        m = str(row.get("model") or "").strip()
        b = str(row.get("edge_bucket") or "").strip()
        mt = str(row.get("market") or "spread").strip().lower()
        if mt != "spread":
            continue
        if not m or not b:
            continue
        hist = lookup.get((m, "spread", b))
        if not hist or int(hist.get("graded_games") or 0) <= 0:
            continue
        roi = hist.get("roi")
        wr = hist.get("win_rate")
        gr = int(hist.get("graded_games") or 0)
        pick = row.get("spread_pick")
        pick_s = str(pick).strip() if pick not in (None, "") else None
        pst = row.get("pocket_state") or hist.get("state")
        eligible = bool(pick_s) and roi is not None and roi > 0.0
        gid = str(row.get("game_id") or "").strip()
        if not gid:
            continue
        rs = (row.get("reason") or "").strip()
        hist_note = f"Historical spread pocket (ncaam_model_pockets): ROI={roi}, Win%={wr}, graded={gr}, state={hist.get('state')}."
        out_rows.append(
            {
                "game_id": gid,
                "matchup": row.get("matchup") or "",
                "market_type": "spread",
                "pick": pick_s,
                "pocket_type": "single_model",
                "model_name": m,
                "models_key": None,
                "state_signature": None,
                "roi": roi,
                "win_rate": wr,
                "graded_games": gr,
                "combo_state": pst,
                "reason": f"{rs} {hist_note}"[:400],
                "eligible_for_parlay": eligible,
            }
        )

    for row in lb_doc.get("best_single_model_total") or []:
        if not isinstance(row, dict):
            continue
        m = str(row.get("model") or "").strip()
        b = str(row.get("edge_bucket") or "").strip()
        mt = str(row.get("market") or "total").strip().lower()
        if mt != "total":
            continue
        if not m or not b:
            continue
        hist = lookup.get((m, "total", b))
        if not hist or int(hist.get("graded_games") or 0) <= 0:
            continue
        roi = hist.get("roi")
        wr = hist.get("win_rate")
        gr = int(hist.get("graded_games") or 0)
        pick = row.get("total_pick")
        pick_s = str(pick).strip() if pick not in (None, "") else None
        pst = row.get("pocket_state") or hist.get("state")
        eligible = False
        gid = str(row.get("game_id") or "").strip()
        if not gid:
            continue
        rs = (row.get("reason") or "").strip()
        hist_note = f"Historical total pocket (ncaam_model_pockets): ROI={roi}, Win%={wr}, graded={gr}, state={hist.get('state')}."
        out_rows.append(
            {
                "game_id": gid,
                "matchup": row.get("matchup") or "",
                "market_type": "total",
                "pick": pick_s,
                "pocket_type": "single_model",
                "model_name": m,
                "models_key": None,
                "state_signature": None,
                "roi": roi,
                "win_rate": wr,
                "graded_games": gr,
                "combo_state": pst,
                "reason": f"{rs} {hist_note}"[:400],
                "eligible_for_parlay": eligible,
            }
        )

    def _rpo_sort_key(r: dict) -> tuple:
        roi = _safe_float(r.get("roi"))
        gr = int(r.get("graded_games") or 0)
        wr = _safe_float(r.get("win_rate"))
        return (
            -(roi if roi is not None else -1e18),
            -gr,
            -(wr if wr is not None else -1.0),
        )

    out_rows.sort(key=_rpo_sort_key)
    for i, r in enumerate(out_rows, start=1):
        r["rank"] = i

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "league": LEAGUE,
        "source_backtest_dir": lb_doc.get("source_backtest_dir"),
        "source_leaderboard_artifact": "ncaam_live_pocket_leaderboard.json",
        "source_single_pockets_artifact": "ncaam_model_pockets.json",
        "source_daily_view_path": lb_doc.get("source_daily_view_path"),
        "slate_date": lb_doc.get("slate_date"),
        "opportunity_count": len(out_rows),
        "sort_order": ["roi descending", "graded_games descending", "win_rate descending"],
        "notes": (
            "Excludes strongest_spread_cluster / cold / pass slices (no per-row historical ROI on leaderboard). "
            "Single-model rows require a matching (model, market_type, edge_bucket) in ncaam_model_pockets with graded_games>0."
        ),
        "opportunities": out_rows,
    }


def build_ncaam_best_pocket_per_game_from_leaderboard(lb_doc: dict) -> dict:
    """
    One read-only row per live-slate game: best positive historical spread combo (triple > pair on ties),
    else PASS with explanation from pass/cold/cluster/combo context. Does not change authority or pocket math.

    Each row includes best_reference_* fields: the historical combo row examined (winner if positive, else
    best-ranked triple/pair by ROI/graded/tie-break, or empty if no combo exists).
    """
    if not isinstance(lb_doc, dict):
        return {}

    def _empty_reference_fields() -> dict[str, Any]:
        return {
            "best_reference_pocket_type": None,
            "best_reference_models_key": None,
            "best_reference_state_signature": None,
            "best_reference_roi": None,
            "best_reference_win_rate": None,
            "best_reference_graded_games": None,
            "best_reference_reason": None,
        }

    def _reference_from_combo_row(ref_type: str, row: dict) -> dict[str, Any]:
        roi = _safe_float(row.get("roi"))
        gr = int(row.get("graded_games") or 0)
        wr = _safe_float(row.get("win_rate"))
        mk = row.get("models_key")
        mk_s = str(mk).strip() if mk not in (None, "") else None
        sig = row.get("state_signature")
        sig_s = str(sig).strip() if sig not in (None, "") else None
        cst = row.get("combo_state")
        roi_s = f"{roi:.4f}" if roi is not None else "n/a"
        wr_s = f"{wr:.4f}" if wr is not None else "n/a"
        sig_short = (sig_s[:72] + "…") if sig_s and len(sig_s) > 72 else sig_s
        sig_part = f" signature={sig_short}" if sig_short else ""
        art = (row.get("reason") or "").strip()
        br_reason = (
            f"Historical {ref_type} pocket models={mk_s or 'unknown'}{sig_part}: "
            f"ROI={roi_s}, Win%={wr_s}, graded={gr}, pocket_state={cst}."
        )
        if art:
            br_reason = f"{br_reason} ({art[:180]})"
        return {
            "best_reference_pocket_type": ref_type,
            "best_reference_models_key": mk_s,
            "best_reference_state_signature": sig_s,
            "best_reference_roi": roi,
            "best_reference_win_rate": wr,
            "best_reference_graded_games": gr,
            "best_reference_reason": br_reason[:520],
        }

    clusters = [r for r in (lb_doc.get("strongest_spread_cluster") or []) if isinstance(r, dict)]
    triple_by: dict[str, dict] = {}
    pair_by: dict[str, dict] = {}
    for r in lb_doc.get("best_triple_spread") or []:
        if not isinstance(r, dict):
            continue
        gid = str(r.get("game_id") or "").strip()
        if gid:
            triple_by[gid] = r
    for r in lb_doc.get("best_pair_spread") or []:
        if not isinstance(r, dict):
            continue
        gid = str(r.get("game_id") or "").strip()
        if gid:
            pair_by[gid] = r
    pass_by: dict[str, dict] = {}
    for r in lb_doc.get("pass_candidates") or []:
        if not isinstance(r, dict):
            continue
        gid = str(r.get("game_id") or "").strip()
        if gid:
            pass_by[gid] = r
    cold_by: dict[str, dict] = {}
    for r in lb_doc.get("cold_cluster_warnings") or []:
        if not isinstance(r, dict):
            continue
        gid = str(r.get("game_id") or "").strip()
        if gid:
            cold_by[gid] = r

    # Tie-break when ROI and graded match: triple before spread_cluster before pair (cluster has no ROI).
    _type_tie = {"triple_spread": 0, "spread_cluster": 1, "pair_spread": 2}

    games_out: list[dict] = []

    for cl_row in clusters:
        gid = str(cl_row.get("game_id") or "").strip()
        if not gid:
            continue
        tr = triple_by.get(gid)
        pr = pair_by.get(gid)
        p_row = pass_by.get(gid)
        c_row = cold_by.get(gid)

        combo_for_sort: list[tuple[str, dict, Optional[float], int]] = []
        if tr is not None:
            combo_for_sort.append(
                (
                    "triple_spread",
                    tr,
                    _safe_float(tr.get("roi")),
                    int(tr.get("graded_games") or 0),
                )
            )
        if pr is not None:
            combo_for_sort.append(
                (
                    "pair_spread",
                    pr,
                    _safe_float(pr.get("roi")),
                    int(pr.get("graded_games") or 0),
                )
            )

        positive = [x for x in combo_for_sort if x[2] is not None and x[2] > 0.0]
        if positive:
            positive.sort(key=lambda x: (-x[2], -x[3], _type_tie[x[0]]))
            win_t, win_row, roi, n_gr = positive[0]
            wr_f = _safe_float(win_row.get("win_rate"))
            spread_pick = win_row.get("spread_pick") or cl_row.get("spread_pick")
            sp_s = str(spread_pick).strip() if spread_pick not in (None, "") else ""
            pocket_state = win_row.get("combo_state")
            spa = win_row.get("spread_pocket_alignment") if isinstance(win_row.get("spread_pocket_alignment"), dict) else {}
            hci = _bpp_alignment_hci(spa)
            cluster_bits = f"cluster_score={cl_row.get('cluster_score')}; slate_spread_align={_bpp_alignment_hci(cl_row.get('spread_pocket_alignment'))}."
            ref_fields = _reference_from_combo_row(win_t, win_row)
            mk_disp = ref_fields.get("best_reference_models_key") or "unknown"
            reason = (
                f"Positive pocket: **{mk_disp}** ({win_t}) ROI={roi:.4f} over {n_gr} graded combo legs; "
                f"pocket_state={pocket_state}; spread_align={hci}. {cluster_bits} Read-only; does not change authority."
            )
            eligible = bool(sp_s) and roi is not None and roi > 0.0
            games_out.append(
                {
                    "game_id": gid,
                    "matchup": cl_row.get("matchup") or win_row.get("matchup") or "",
                    "spread_pick": sp_s or None,
                    "best_pocket_type": win_t,
                    "best_pocket_roi": roi,
                    "best_pocket_win_rate": wr_f,
                    "best_pocket_graded_games": n_gr,
                    "pocket_state": pocket_state,
                    "spread_align_hci": hci or None,
                    "cluster_score": cl_row.get("cluster_score"),
                    "reason": reason[:520],
                    "eligible_for_parlay": eligible,
                    **ref_fields,
                }
            )
            continue

        # PASS: no positive-ROI triple/pair combo on this game.
        best_ref: Optional[tuple[str, dict, Optional[float], int]] = None
        if combo_for_sort:
            combo_for_sort.sort(
                key=lambda x: (
                    -(x[2] if x[2] is not None else -1e18),
                    -x[3],
                    _type_tie[x[0]],
                )
            )
            best_ref = combo_for_sort[0]

        ref_fields = _empty_reference_fields()
        ref_roi: Optional[float] = None
        ref_gr: int | None = None
        ref_wr: Optional[float] = None
        ref_state = None
        ref_hci = _bpp_alignment_hci(cl_row.get("spread_pocket_alignment"))
        if best_ref:
            _bt, _br, ref_roi, ref_gr = best_ref
            ref_fields = _reference_from_combo_row(_bt, _br)
            ref_wr = ref_fields.get("best_reference_win_rate")
            ref_state = _br.get("combo_state")
            ref_hci = _bpp_alignment_hci(_br.get("spread_pocket_alignment")) or ref_hci

        spread_pick = cl_row.get("spread_pick")
        sp_s = str(spread_pick).strip() if spread_pick not in (None, "") else ""

        mk_disp = ref_fields.get("best_reference_models_key") or "unknown"
        rt_disp = ref_fields.get("best_reference_pocket_type") or "combo"
        if best_ref:
            roi_fmt = f"{ref_roi:.4f}" if ref_roi is not None else "n/a"
            gr_disp = int(ref_gr or 0)
            core_pass = (
                f"PASS — Best reference pocket **{mk_disp}** ({rt_disp}) had ROI {roi_fmt} over {gr_disp} graded games; "
                f"no positive pocket exposed."
            )
        else:
            core_pass = (
                "PASS — No **triple** or **pair** spread combo row on the live leaderboard for this game "
                "(nothing to score against historical pockets)."
            )

        parts: list[str] = [core_pass]
        if p_row:
            pr_txt = (p_row.get("reason") or "").strip()
            if pr_txt:
                parts.append(f"Pass filter: {pr_txt}")
        if c_row:
            cw = c_row.get("warning_score")
            cr = (c_row.get("reason") or "").strip()
            parts.append(f"Cold-warning: {cr} (warning_score={cw}).".strip())
        parts.append(
            f"Spread cluster_score={cl_row.get('cluster_score')}; slate_spread_align={_bpp_alignment_hci(cl_row.get('spread_pocket_alignment'))}."
        )
        reason = " ".join(parts)[:520]

        games_out.append(
            {
                "game_id": gid,
                "matchup": cl_row.get("matchup") or "",
                "spread_pick": sp_s or None,
                "best_pocket_type": "PASS",
                "best_pocket_roi": None,
                "best_pocket_win_rate": ref_wr,
                "best_pocket_graded_games": ref_gr if best_ref else None,
                "pocket_state": ref_state,
                "spread_align_hci": ref_hci or None,
                "cluster_score": cl_row.get("cluster_score"),
                "reason": reason,
                "eligible_for_parlay": False,
                **ref_fields,
            }
        )

    def _board_sort_key(g: dict) -> tuple:
        roi = _safe_float(g.get("best_pocket_roi"))
        gr = int(g.get("best_pocket_graded_games") or 0)
        is_pos = roi is not None and roi > 0.0
        tier = 0 if is_pos else 1
        roi_key = -(roi if roi is not None else -1e12)
        return (tier, roi_key, -gr)

    games_sorted = sorted(games_out, key=_board_sort_key)
    for i, g in enumerate(games_sorted, start=1):
        g["rank"] = i

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "league": LEAGUE,
        "source_backtest_dir": lb_doc.get("source_backtest_dir"),
        "source_leaderboard_artifact": "ncaam_live_pocket_leaderboard.json",
        "source_daily_view_path": lb_doc.get("source_daily_view_path"),
        "slate_date": lb_doc.get("slate_date"),
        "game_count": len(games_sorted),
        "selection_rules": {
            "positive_winner": (
                "Among best_triple_spread and best_pair_spread rows for the game, require roi > 0; "
                "pick max ROI, then max graded_games, then type order triple_spread < spread_cluster < pair_spread "
                "(cluster is not in the positive pool — only triple/pair carry ROI)."
            ),
            "pass": (
                "If no positive-ROI combo, best_pocket_type=PASS; reason merges pass_candidates, cold_cluster_warnings, "
                "best non-positive combo reference, and cluster alignment."
            ),
            "parlay_eligible": "eligible_for_parlay true only when best_pocket_roi > 0 and spread_pick is non-empty.",
            "reference_fields": (
                "best_reference_* always describe the historical combo row used: for winners, the selected positive "
                "triple_spread or pair_spread row; for PASS, the best-ranked triple/pair by ROI (then graded, then type); "
                "if no combo row exists, reference fields are null."
            ),
        },
        "games": games_sorted,
    }


def _result_leg(res: Any) -> Optional[str]:
    if res is None:
        return None
    s = str(res).strip().upper()
    if s in ("WIN", "LOSS", "PUSH"):
        return s
    return None


def _profit_for_leg(res: str) -> float:
    if res == "WIN":
        return PAYOUT_MULTIPLIER
    if res == "LOSS":
        return -1.0
    return 0.0


def _combo_outcome_two(a: Optional[str], b: Optional[str]) -> Optional[str]:
    if a is None or b is None:
        return None
    if a == "LOSS" or b == "LOSS":
        return "LOSS"
    if a == "WIN" and b == "WIN":
        return "WIN"
    if a == "PUSH" or b == "PUSH":
        return "PUSH"
    return "LOSS"


def _combo_outcome_three(a: Optional[str], b: Optional[str], c: Optional[str]) -> Optional[str]:
    if a is None or b is None or c is None:
        return None
    if a == "LOSS" or b == "LOSS" or c == "LOSS":
        return "LOSS"
    if a == "WIN" and b == "WIN" and c == "WIN":
        return "WIN"
    if a == "PUSH" or b == "PUSH" or c == "PUSH":
        return "PUSH"
    return "LOSS"


def _classify_state(graded: int, win_rate: Optional[float], roi: Optional[float]) -> str:
    if graded < MIN_GRADED_FOR_STATE:
        return "insufficient"
    wr = win_rate if win_rate is not None else 0.0
    r = roi if roi is not None else 0.0
    if graded >= MIN_GRADED_HOT and wr >= HOT_WIN_RATE and r >= HOT_ROI:
        return "hot"
    if wr < COLD_WIN_RATE or r <= COLD_ROI:
        return "cold"
    return "warm"


def _aggregate_for_bucket(all_rows: list[dict]) -> dict:
    """all_rows: entries with abs_edge; res may be None if ungraded."""
    edges = [t["abs_edge"] for t in all_rows]
    graded_rows = [t for t in all_rows if t.get("res") is not None]
    games_n = len(all_rows)
    if not graded_rows:
        avg_edge = round(sum(edges) / len(edges), 4) if edges else None
        return {
            "games": games_n,
            "graded_games": 0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "win_rate": None,
            "roi": None,
            "avg_edge": avg_edge,
            "state": "insufficient",
        }
    wins = losses = pushes = 0
    profit = 0.0
    for t in graded_rows:
        res = t["res"]
        profit += _profit_for_leg(res)
        if res == "WIN":
            wins += 1
        elif res == "LOSS":
            losses += 1
        else:
            pushes += 1
    graded = wins + losses + pushes
    win_rate = round(wins / graded, 4) if graded else None
    roi = round(profit / graded, 4) if graded else None
    avg_edge = round(sum(edges) / len(edges), 4) if edges else None
    return {
        "games": games_n,
        "graded_games": graded,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": win_rate,
        "roi": roi,
        "avg_edge": avg_edge,
        "state": _classify_state(graded, win_rate, roi),
    }


def _collect_models(games: list[dict]) -> list[str]:
    names: set[str] = set()
    for g in games:
        mr = g.get("model_results") or {}
        for k in mr:
            if k not in EXCLUDED_MODELS:
                names.add(k)
    return sorted(names)


def build_ncaam_model_pocket_artifacts() -> dict[str, Path]:
    """
    Build NCAAM pocket JSON artifacts in the latest backtest directory.
    Returns dict of logical name -> path written.
    """
    latest_dir, games_path = _latest_backtest_dir(LEAGUE)
    if not games_path.exists():
        raise FileNotFoundError(f"Missing backtest games: {games_path}")

    games: list[dict] = _load_json(games_path)
    if not isinstance(games, list):
        raise ValueError("backtest_games.json must be a list")

    models = _collect_models(games)

    # (model, market, bucket) -> list of {res, abs_edge}
    bucket_rows: dict[tuple[str, str, str], list[dict]] = defaultdict(list)

    for g in games:
        mr = g.get("model_results") or {}
        for model_name, res_blob in mr.items():
            if model_name in EXCLUDED_MODELS:
                continue
            if not isinstance(res_blob, dict):
                continue
            se = _safe_float(res_blob.get("spread_edge"))
            te = _safe_float(res_blob.get("total_edge"))
            sr = _result_leg(res_blob.get("spread_result"))
            tr = _result_leg(res_blob.get("total_result"))

            if se is not None:
                b = determine_band(se)
                bucket_rows[(model_name, "spread", b)].append({"res": sr, "abs_edge": abs(se)})
            if te is not None:
                b = determine_band(te)
                bucket_rows[(model_name, "total", b)].append({"res": tr, "abs_edge": abs(te)})

    single_rows: list[dict] = []
    state_lookup: dict[tuple[str, str, str], str] = {}

    for (model_name, market, bucket), rows in sorted(bucket_rows.items()):
        stats = _aggregate_for_bucket(rows)
        stats_row = {
            "model": model_name,
            "market_type": market,
            "edge_bucket": bucket,
            **stats,
        }
        single_rows.append(stats_row)
        state_lookup[(model_name, market, bucket)] = stats["state"]

    # --- combo pockets (pairs + triples), per market ---
    combo_agg: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    # key: (market, kind, models_key, state_signature) -> list of combo outcomes

    for g in games:
        mr = g.get("model_results") or {}
        for market, res_key, edge_key in (
            ("spread", "spread_result", "spread_edge"),
            ("total", "total_result", "total_edge"),
        ):
            for combo in combinations(models, 2):
                m1, m2 = combo
                b1 = mr.get(m1) or {}
                b2 = mr.get(m2) or {}
                e1 = _safe_float(b1.get(edge_key))
                e2 = _safe_float(b2.get(edge_key))
                r1 = _result_leg(b1.get(res_key))
                r2 = _result_leg(b2.get(res_key))
                if e1 is None or e2 is None:
                    continue
                bucket1 = determine_band(e1)
                bucket2 = determine_band(e2)
                st1 = state_lookup.get((m1, market, bucket1), "insufficient")
                st2 = state_lookup.get((m2, market, bucket2), "insufficient")
                sig_parts = sorted([f"{m1}:{st1}", f"{m2}:{st2}"])
                sig = "|".join(sig_parts)
                co = _combo_outcome_two(r1, r2)
                if co is None:
                    continue
                mk = f"{m1}|{m2}"
                combo_agg[(market, "pair", mk, sig)].append(co)

            for combo in combinations(models, 3):
                m1, m2, m3 = combo
                b1 = mr.get(m1) or {}
                b2 = mr.get(m2) or {}
                b3 = mr.get(m3) or {}
                e1 = _safe_float(b1.get(edge_key))
                e2 = _safe_float(b2.get(edge_key))
                e3 = _safe_float(b3.get(edge_key))
                r1 = _result_leg(b1.get(res_key))
                r2 = _result_leg(b2.get(res_key))
                r3 = _result_leg(b3.get(res_key))
                if e1 is None or e2 is None or e3 is None:
                    continue
                bucket1 = determine_band(e1)
                bucket2 = determine_band(e2)
                bucket3 = determine_band(e3)
                st1 = state_lookup.get((m1, market, bucket1), "insufficient")
                st2 = state_lookup.get((m2, market, bucket2), "insufficient")
                st3 = state_lookup.get((m3, market, bucket3), "insufficient")
                sig_parts = sorted([f"{m1}:{st1}", f"{m2}:{st2}", f"{m3}:{st3}"])
                sig = "|".join(sig_parts)
                co = _combo_outcome_three(r1, r2, r3)
                if co is None:
                    continue
                mk = f"{m1}|{m2}|{m3}"
                combo_agg[(market, "triple", mk, sig)].append(co)

    combo_rows: list[dict] = []
    for (market, kind, models_key, sig), outcomes in combo_agg.items():
        wins = losses = pushes = profit = 0
        for o in outcomes:
            profit += _profit_for_leg(o)
            if o == "WIN":
                wins += 1
            elif o == "LOSS":
                losses += 1
            else:
                pushes += 1
        graded = len(outcomes)
        if graded < MIN_COMBO_GRADED:
            continue
        win_rate = round(wins / graded, 4)
        roi = round(profit / graded, 4)
        combo_rows.append({
            "market_type": market,
            "combo_kind": kind,
            "models_key": models_key,
            "state_signature": sig,
            "games": graded,
            "graded_games": graded,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "win_rate": win_rate,
            "roi": roi,
            "state": _classify_state(graded, win_rate, roi),
        })

    # Index combos for slate matching: (market, models_key, sig) -> list of rows (should be 0-1)
    combo_by_key: dict[tuple[str, str, str], dict] = {}
    for row in combo_rows:
        k = (row["market_type"], row["models_key"], row["state_signature"])
        combo_by_key[k] = row

    # --- current slate from final game view ---
    final_path = get_final_view_json_path(LEAGUE)
    slate_games: list[dict] = []
    if final_path.exists():
        raw = _load_json(final_path)
        slate_games = raw["games"] if isinstance(raw, dict) and "games" in raw else (raw if isinstance(raw, list) else [])

    def _slate_model_states(game: dict) -> dict[str, Any]:
        models_blob = game.get("models") or {}
        per_model: dict[str, dict] = {}
        spread_summary = {"hot": 0, "warm": 0, "cold": 0, "insufficient": 0}
        total_summary = {"hot": 0, "warm": 0, "cold": 0, "insufficient": 0}
        for mname, blob in models_blob.items():
            if mname in EXCLUDED_MODELS or not isinstance(blob, dict):
                continue
            se = _safe_float(blob.get("spread_edge") or blob.get("Spread Edge"))
            te = _safe_float(blob.get("total_edge") or blob.get("Total Edge"))
            sd = td = None
            ss = ts = None
            if se is not None:
                sb = determine_band(se)
                ss = state_lookup.get((mname, "spread", sb), "insufficient")
                spread_summary[ss] = spread_summary.get(ss, 0) + 1
                sd = {"edge_bucket": sb, "state": ss, "abs_edge": round(abs(se), 4)}
            if te is not None:
                tb = determine_band(te)
                ts = state_lookup.get((mname, "total", tb), "insufficient")
                total_summary[ts] = total_summary.get(ts, 0) + 1
                td = {"edge_bucket": tb, "state": ts, "abs_edge": round(abs(te), 4)}
            per_model[mname] = {"spread": sd, "total": td}

        def _best_combo(market: str, size: int) -> Optional[dict]:
            names = [n for n in per_model if per_model[n].get(market)]
            if len(names) < size:
                return None
            best: Optional[dict] = None
            for combo in combinations(sorted(names), size):
                parts = []
                for mn in combo:
                    st = (per_model[mn][market] or {}).get("state", "insufficient")
                    parts.append(f"{mn}:{st}")
                sig = "|".join(sorted(parts))
                mk = "|".join(combo)
                hit = combo_by_key.get((market, mk, sig))
                if hit is None:
                    continue
                if best is None:
                    best = hit
                    continue
                if hit["graded_games"] > best["graded_games"]:
                    best = hit
                elif hit["graded_games"] == best["graded_games"] and (hit.get("roi") or 0) > (best.get("roi") or 0):
                    best = hit
            return best

        gid = (
            game.get("canonical_game_id")
            or game.get("game_id")
            or game.get("espn_game_id")
            or ""
        )
        return {
            "game_id": str(gid).strip(),
            "matchup": (
                f"{(game.get('away_team_display') or game.get('away_team') or '').strip()} @ "
                f"{(game.get('home_team_display') or game.get('home_team') or '').strip()}"
            ).strip(),
            "per_model": per_model,
            "spread_pocket_alignment": spread_summary,
            "total_pocket_alignment": total_summary,
            "best_pair_spread": _best_combo("spread", 2),
            "best_triple_spread": _best_combo("spread", 3),
            "best_pair_total": _best_combo("total", 2),
            "best_triple_total": _best_combo("total", 3),
        }

    current_rows = [_slate_model_states(g) for g in slate_games if isinstance(g, dict)]

    live_path, live_slate_date, live_id_order, daily_doc = _ncaam_latest_daily_view_slate_order()
    by_gid_current = {str(r.get("game_id", "")).strip(): r for r in current_rows if str(r.get("game_id", "")).strip()}
    live_rows = [by_gid_current[gid] for gid in live_id_order if gid in by_gid_current]

    meta = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "league": LEAGUE,
        "source_backtest_dir": latest_dir.name,
        "source_games_path": str(games_path.as_posix()),
        "excluded_models": sorted(EXCLUDED_MODELS),
        "formulas": {
            "roi_minus_110": "Per graded leg: WIN adds 100/|price| units profit, LOSS adds -1, PUSH adds 0; ROI = total_profit / graded_games (matches execution overlay 039b leg accounting).",
            "win_rate": "wins / graded_games where graded_games = wins + losses + pushes (pushes count in denominator).",
            "breakeven_win_rate": round(BREAKEVEN_WIN_RATE, 6),
            "state_rules": {
                "insufficient": f"graded_games < {MIN_GRADED_FOR_STATE}",
                "hot": f"graded_games >= {MIN_GRADED_HOT} and win_rate >= {HOT_WIN_RATE} and roi >= {HOT_ROI}",
                "cold": f"graded_games >= {MIN_GRADED_FOR_STATE} and (win_rate < {COLD_WIN_RATE} or roi <= {COLD_ROI})",
                "warm": "else when graded_games >= MIN_GRADED_FOR_STATE",
            },
            "combo_outcome_pair": "LOSS if either leg LOSS; WIN if both WIN; PUSH if any PUSH without LOSS.",
            "combo_outcome_triple": "LOSS if any leg LOSS; WIN if all WIN; PUSH if any PUSH without LOSS.",
            "combo_min_graded": MIN_COMBO_GRADED,
        },
    }

    out_single = latest_dir / "ncaam_model_pockets.json"
    out_combo = latest_dir / "ncaam_model_combo_pockets.json"
    out_current = latest_dir / "ncaam_current_game_pocket_view.json"
    out_live = latest_dir / "ncaam_live_game_pocket_view.json"
    out_leaderboard = latest_dir / "ncaam_live_pocket_leaderboard.json"
    out_best_per_game = latest_dir / "ncaam_best_pocket_per_game.json"
    out_ranked_pockets = latest_dir / "ncaam_ranked_pocket_opportunities.json"

    _write_json(out_single, {**meta, "pockets": single_rows})
    _write_json(out_combo, {**meta, "combo_pockets": combo_rows})
    _write_json(out_current, {**meta, "games": current_rows})

    live_meta = {
        **meta,
        "slate_date": live_slate_date,
        "source_live_slate_artifact": str(live_path.resolve()) if live_path else None,
        "game_count": len(live_rows),
        "games": live_rows,
    }
    _write_json(out_live, live_meta)

    lb_doc = _build_ncaam_live_pocket_leaderboard(
        live_rows,
        daily_doc,
        source_backtest_dir=latest_dir.name,
        slate_date=live_slate_date,
        source_live_slate_path=str(live_path.resolve()) if live_path else None,
    )
    _write_json(out_leaderboard, lb_doc)
    bpp_doc = build_ncaam_best_pocket_per_game_from_leaderboard(lb_doc)
    _write_json(out_best_per_game, bpp_doc)
    rpo_doc = build_ncaam_ranked_pocket_opportunities(lb_doc, single_rows)
    _write_json(out_ranked_pockets, rpo_doc)

    print(f"Wrote {out_single}")
    print(f"Wrote {out_combo}")
    print(f"Wrote {out_current}")
    print(f"Wrote {out_live} ({len(live_rows)} games)")
    print(f"Wrote {out_leaderboard}")
    print(f"Wrote {out_best_per_game}")
    print(f"Wrote {out_ranked_pockets}")

    try:
        from eng.execution.build_ncaam_pocket_leaderboard_validation import (
            write_ncaam_pocket_leaderboard_validation,
        )

        write_ncaam_pocket_leaderboard_validation(latest_dir)
    except Exception as exc:
        print(f"Warning: NCAAM pocket leaderboard validation skipped: {exc}", file=sys.stderr)

    return {
        "ncaam_model_pockets": out_single,
        "ncaam_model_combo_pockets": out_combo,
        "ncaam_current_game_pocket_view": out_current,
        "ncaam_live_game_pocket_view": out_live,
        "ncaam_live_pocket_leaderboard": out_leaderboard,
        "ncaam_best_pocket_per_game": out_best_per_game,
        "ncaam_ranked_pocket_opportunities": out_ranked_pockets,
    }


def main() -> None:
    try:
        build_ncaam_model_pocket_artifacts()
    except FileNotFoundError as e:
        print(f"Skipping NCAAM model pockets: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
