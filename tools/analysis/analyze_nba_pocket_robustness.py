"""
tools/analysis/analyze_nba_pocket_robustness.py

NBA pocket ROBUSTNESS analysis (READ-ONLY).

Purpose
-------
The production pocket layer scores pockets on season-long historical ROI only. It
ignores regular vs play-in vs playoffs, recent decay, and out-of-sample stability,
so a "hot" pocket may just be a backtest artifact. This tool recomputes pockets from
``backtest_games.json`` and stress-tests each one across segments, recent windows, and
an out-of-sample (first-half / second-half) split, then assigns a trust rating:
KEEP / WATCH / FADE / KILL.

It is strictly read-only:
- Imports (does not modify) production pocket math from build_nba_model_pockets.
- Does NOT touch pocket builders, model/scoring/dashboard logic, or backtests.
- Writes only to a new folder: data/nba/analysis/pocket_robustness_<YYYYMMDD_HHMMSS>/.

CLI
---
python tools/analysis/analyze_nba_pocket_robustness.py \
    --play-in-start-date 2026-04-14 --playoff-start-date 2026-04-18 \
    --min-keep-sample 100 --min-post-sample 20
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Read-only reuse of production pocket math (no side effects at import).
from eng.execution.build_execution_overlay import determine_band  # noqa: E402
from eng.execution.build_nba_model_pockets import (  # noqa: E402
    BREAKEVEN_WIN_RATE,
    EXCLUDED_MODELS,
    MIN_COMBO_GRADED,
    PAYOUT_MULTIPLIER,
    _aggregate_for_bucket,
    _classify_state,
    _combo_outcome_three,
    _combo_outcome_two,
    _profit_for_leg,
    _result_leg,
    _safe_float,
)

LEAGUE = "nba"
QUARANTINED_BACKTESTS = frozenset({"backtest_20260517_100524"})

DEFAULT_PLAY_IN_START = "2026-04-14"
DEFAULT_PLAYOFF_START = "2026-04-18"

# Segment groups used for aggregation (mirrors the season recap for reconciliation).
SEG_GROUPS = {
    "full": ["regular", "play_in", "playoffs"],
    "regular": ["regular"],
    "play_in": ["play_in"],
    "playoffs": ["playoffs"],
    "postseason": ["play_in", "playoffs"],
}

# Flags that indicate instability/decay (used to filter "best candidates"). The
# first_half_hot_second_half_positive flag is intentionally NOT here (it is reassuring).
NEGATIVE_FLAGS = frozenset({
    "hot_full_season_but_bad_recent",
    "positive_full_season_but_negative_recent",
    "positive_regular_but_negative_postseason",
    "positive_full_season_but_negative_playoffs",
    "first_half_hot_second_half_negative",
    "first_half_positive_second_half_negative",
})

_SEASON_TYPE_MAP = {
    "regular": "regular", "regular season": "regular", "reg": "regular",
    "playoffs": "playoffs", "playoff": "playoffs", "postseason": "playoffs", "post": "playoffs",
    "preseason": "preseason", "pre": "preseason",
    "play_in": "play_in", "play-in": "play_in", "playin": "play_in",
}


# ============================================================================
# Helpers
# ============================================================================

def _parse_iso_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(str(s).strip()[:10])
    except (ValueError, AttributeError):
        return None


def _fmt_pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _fmt_roi(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:+.2f}%"


def _load_json_safe(path: Path, log: list[str]) -> Optional[Any]:
    if not path.exists():
        log.append(f"SKIP (missing): {path.name}")
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        log.append(f"SKIP (corrupt/unreadable): {path.name} -- {exc}")
        return None


def resolve_backtest_dir(backtest_dir: Optional[str], log: list[str]) -> Path:
    root = PROJECT_ROOT / "data" / LEAGUE / "backtests"
    if not root.exists():
        raise FileNotFoundError(f"Backtest root not found: {root}")
    if backtest_dir:
        target = root / backtest_dir.strip()
        if not target.is_dir() or not (target / "backtest_games.json").exists():
            raise FileNotFoundError(f"Backtest dir invalid or missing backtest_games.json: {target}")
        log.append(f"Backtest dir (explicit): {target.name}")
        return target
    candidates = [
        d for d in root.iterdir()
        if d.is_dir() and d.name.startswith("backtest_")
        and d.name not in QUARANTINED_BACKTESTS
        and (d / "backtest_games.json").exists()
    ]
    if not candidates:
        raise FileNotFoundError(f"No usable backtest_* folders in {root}")
    latest = max(candidates, key=lambda d: d.stat().st_mtime)
    log.append(f"Backtest dir (latest by mtime): {latest.name}")
    return latest


def classify_segment(game: dict, play_in_start: date, playoff_start: date) -> str:
    """Return regular|play_in|playoffs|preseason|unknown (priority: season_type, game_id, date)."""
    gdate = _parse_iso_date(game.get("game_date") or "")
    base: Optional[str] = None
    season_type = str(game.get("season_type") or "").strip().lower()
    if season_type in _SEASON_TYPE_MAP:
        base = _SEASON_TYPE_MAP[season_type]
    if base is None:
        gid = str(game.get("game_id") or "")
        if gid.startswith("004"):
            base = "playoffs"
        elif gid.startswith("002"):
            base = "regular"
        elif gid.startswith("001"):
            base = "preseason"
    if base is None:
        if gdate is None:
            return "unknown"
        if gdate >= playoff_start:
            return "playoffs"
        if gdate >= play_in_start:
            return "play_in"
        return "regular"
    # Play-in date-window overlay (season_type/game_id 004 cannot express play-in).
    if base == "playoffs" and gdate is not None and play_in_start <= gdate < playoff_start:
        return "play_in"
    return base


def _groups_for_segment(seg: str) -> list[str]:
    return [grp for grp, segs in SEG_GROUPS.items() if seg in segs]


def _norm_agg(raw: dict) -> dict:
    """Normalize _aggregate_for_bucket output to a compact stats dict."""
    return {
        "graded": raw.get("graded_games", 0),
        "wins": raw.get("wins", 0),
        "losses": raw.get("losses", 0),
        "pushes": raw.get("pushes", 0),
        "win_rate": raw.get("win_rate"),
        "roi": raw.get("roi"),
        "avg_edge": raw.get("avg_edge"),
        "state": raw.get("state"),
    }


def _agg_legs(legs: list[dict]) -> dict:
    """Single-model leg aggregation via production _aggregate_for_bucket (identical math/state)."""
    return _norm_agg(_aggregate_for_bucket([{"res": x["res"], "abs_edge": x["abs_edge"]} for x in legs]))


def _agg_combo(outcomes: list[str]) -> dict:
    wins = losses = pushes = 0
    profit = 0.0
    for o in outcomes:
        if o == "WIN":
            wins += 1
            profit += PAYOUT_MULTIPLIER
        elif o == "LOSS":
            losses += 1
            profit -= 1.0
        elif o == "PUSH":
            pushes += 1
    graded = wins + losses + pushes
    win_rate = round(wins / graded, 4) if graded else None
    roi = round(profit / graded, 4) if graded else None
    return {
        "graded": graded, "wins": wins, "losses": losses, "pushes": pushes,
        "win_rate": win_rate, "roi": roi, "avg_edge": None,
        "state": _classify_state(graded, win_rate, roi),
    }


# ============================================================================
# Trust rating
# ============================================================================

def _is_pos(agg: Optional[dict], min_sample: int = 0) -> bool:
    return bool(agg and agg["graded"] >= min_sample and agg["roi"] is not None and agg["roi"] > 0)


def _is_neg(agg: Optional[dict], min_sample: int = 0) -> bool:
    return bool(agg and agg["graded"] >= min_sample and agg["roi"] is not None and agg["roi"] < 0)


def _component(roi: Optional[float], scale: float) -> float:
    if roi is None:
        return 0.0
    return max(-1.0, min(1.0, roi / scale))


def rate_pocket(scopes: dict, args) -> tuple[str, float, list[str], dict]:
    """Return (rating, trust_score 0-100, flags, component_breakdown)."""
    full = scopes.get("full")
    h2 = scopes.get("second_half")
    h1 = scopes.get("first_half")
    post = scopes.get("postseason")
    playoffs = scopes.get("playoffs")
    regular = scopes.get("regular")
    recent = scopes.get("recent")  # primary recent window (may be None for combos)

    flags: list[str] = []

    # --- Decay / segment flags ---
    if full and full.get("state") == "hot" and _is_neg(recent, args.min_recent_sample):
        flags.append("hot_full_season_but_bad_recent")
    if _is_pos(full) and _is_neg(recent, args.min_recent_sample):
        flags.append("positive_full_season_but_negative_recent")
    if _is_pos(regular) and _is_neg(post, args.min_post_sample):
        flags.append("positive_regular_but_negative_postseason")
    if _is_pos(full) and _is_neg(playoffs, args.min_post_sample):
        flags.append("positive_full_season_but_negative_playoffs")

    # --- Out-of-sample flags ---
    h1_state = h1.get("state") if h1 else None
    if h1_state == "hot" and _is_pos(h2):
        flags.append("first_half_hot_second_half_positive")
    if h1_state == "hot" and _is_neg(h2):
        flags.append("first_half_hot_second_half_negative")
    if _is_pos(h1) and _is_neg(h2):
        flags.append("first_half_positive_second_half_negative")

    # --- Categorical rating (configurable thresholds) ---
    full_roi = full["roi"] if full else None
    full_n = full["graded"] if full else 0
    h2_roi = h2["roi"] if h2 else None

    rating = "WATCH"
    if full_roi is None or full_n == 0:
        rating = "KILL"
    elif full_roi <= 0:
        rating = "KILL"
    elif (h2_roi is not None and h2_roi <= args.kill_second_half_roi) or \
         (recent is not None and recent["roi"] is not None and recent["graded"] >= args.min_recent_sample
          and recent["roi"] <= args.kill_recent_roi):
        rating = "KILL"
    else:
        neg_recent = _is_neg(recent, args.min_recent_sample)
        neg_post = _is_neg(post, args.min_post_sample)
        post_ok = (post is None) or (post["graded"] < args.min_post_sample) or \
                  (post["roi"] is not None and post["roi"] >= 0)
        if neg_recent or neg_post:
            rating = "FADE"
        elif (h2_roi is not None and h2_roi > 0) and post_ok and full_n >= args.min_keep_sample:
            rating = "KEEP"
        else:
            rating = "WATCH"

    # --- Numeric trust score (transparent additive, clamped 0-100) ---
    sample_factor = min(1.0, full_n / args.min_keep_sample) if args.min_keep_sample else 1.0
    seg_positive = [s for s in (regular, post) if s and s["graded"] >= args.min_post_sample and s["roi"] is not None]
    consistency = (sum(1 for s in seg_positive if s["roi"] > 0) / len(seg_positive)) if seg_positive else 0.5

    comp = {
        "full_roi": _component(full_roi, args.roi_scale),
        "second_half_roi": _component(h2_roi, args.roi_scale),
        "postseason_roi": _component(post["roi"] if post else None, args.roi_scale),
        "playoff_roi": _component(playoffs["roi"] if playoffs else None, args.roi_scale),
        "recent_roi": _component(recent["roi"] if recent else None, args.roi_scale),
        "sample_factor": sample_factor,
        "consistency": consistency,
    }
    raw = (
        18 * max(0.0, comp["full_roi"])
        + 22 * comp["second_half_roi"]
        + 15 * comp["postseason_roi"]
        + 10 * comp["playoff_roi"]
        + 15 * comp["recent_roi"]
        + 12 * comp["sample_factor"]
        + 8 * comp["consistency"]
    )
    penalty = 0.0
    if full_n < args.min_keep_sample:
        penalty += 12.0 * (1.0 - sample_factor)
    if "positive_full_season_but_negative_recent" in flags:
        penalty += 10.0
    if "positive_regular_but_negative_postseason" in flags or "positive_full_season_but_negative_playoffs" in flags:
        penalty += 12.0
    if "first_half_positive_second_half_negative" in flags or "first_half_hot_second_half_negative" in flags:
        penalty += 12.0
    trust_score = round(max(0.0, min(100.0, raw - penalty)), 2)
    return rating, trust_score, flags, comp


# ============================================================================
# Single-model recomputation
# ============================================================================

def build_single_pockets(games_sorted, play_in_start, playoff_start, args) -> list[dict]:
    # key -> ordered list of legs {res, abs_edge, date, game_id, segment}
    pocket_legs: dict[tuple, list[dict]] = defaultdict(list)
    cutoff = args._oos_cutoff  # ISO string; first half: date < cutoff

    for g in games_sorted:
        seg = classify_segment(g, play_in_start, playoff_start)
        gdate = str(g.get("game_date") or "")[:10]
        gid = str(g.get("canonical_game_id") or g.get("game_id") or "").strip()
        mr = g.get("model_results") or {}
        if not isinstance(mr, dict):
            continue
        for model_name, blob in mr.items():
            if model_name in EXCLUDED_MODELS or not isinstance(blob, dict):
                continue
            for market, rkey, ekey in (
                ("spread", "spread_result", "spread_edge"),
                ("total", "total_result", "total_edge"),
            ):
                edge = _safe_float(blob.get(ekey))
                if edge is None:
                    continue
                res = _result_leg(blob.get(rkey))
                if res is None:
                    continue
                band = determine_band(edge)
                pocket_legs[(model_name, market, band)].append({
                    "res": res, "abs_edge": abs(edge), "date": gdate, "game_id": gid, "segment": seg,
                })

    rows: list[dict] = []
    for (model, market, band), legs in sorted(pocket_legs.items()):
        scopes: dict[str, dict] = {}
        for grp, segs in SEG_GROUPS.items():
            scopes[grp] = _agg_legs([x for x in legs if x["segment"] in segs])

        ordered = sorted(legs, key=lambda x: (x["date"], x["game_id"]))
        for n in (300, 150, 75):
            scopes[f"last{n}"] = _agg_legs(ordered[-n:])
        scopes["recent"] = scopes[f"last{args.recent_window_primary}"]

        scopes["first_half"] = _agg_legs([x for x in ordered if x["date"] < cutoff])
        scopes["second_half"] = _agg_legs([x for x in ordered if x["date"] >= cutoff])

        rating, trust, flags, comp = rate_pocket(scopes, args)
        rows.append({
            "model": model, "market_type": market, "edge_bucket": band,
            "state_full": scopes["full"]["state"],
            "scopes": scopes, "flags": flags, "trust_score": trust, "rating": rating,
            "components": comp,
        })

    rows.sort(key=lambda r: r["trust_score"], reverse=True)
    return rows


# ============================================================================
# Combo recomputation (per-segment; full-season state_signature)
# ============================================================================

def build_combo_pockets(games_sorted, single_rows, play_in_start, playoff_start, args) -> list[dict]:
    # Full-season state lookup from recomputed single pockets (matches production signature basis).
    state_lookup: dict[tuple[str, str, str], str] = {}
    for r in single_rows:
        state_lookup[(r["model"], r["market_type"], r["edge_bucket"])] = r["state_full"]

    cutoff = args._oos_cutoff
    # key -> scope -> list[outcome]
    combo_cells: dict[tuple, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    for g in games_sorted:
        seg = classify_segment(g, play_in_start, playoff_start)
        gdate = str(g.get("game_date") or "")[:10]
        groups = _groups_for_segment(seg)
        oos = "first_half" if gdate < cutoff else "second_half"
        mr = g.get("model_results") or {}
        if not isinstance(mr, dict):
            continue
        present = [m for m in mr if m not in EXCLUDED_MODELS and isinstance(mr[m], dict)]

        for market, rkey, ekey in (
            ("spread", "spread_result", "spread_edge"),
            ("total", "total_result", "total_edge"),
        ):
            # Precompute per-model band/state/result for this market.
            info: dict[str, tuple] = {}
            for m in present:
                edge = _safe_float(mr[m].get(ekey))
                if edge is None:
                    continue
                band = determine_band(edge)
                st = state_lookup.get((m, market, band), "insufficient")
                res = _result_leg(mr[m].get(rkey))
                info[m] = (band, st, res)

            usable = [m for m in info if info[m][2] is not None]

            for size, outfn in ((2, _combo_outcome_two), (3, _combo_outcome_three)):
                for combo in combinations(sorted(usable), size):
                    sig = "|".join(sorted(f"{m}:{info[m][1]}" for m in combo))
                    mk = "|".join(combo)
                    results = [info[m][2] for m in combo]
                    outcome = outfn(*results)
                    if outcome is None:
                        continue
                    kind = "pair" if size == 2 else "triple"
                    key = (market, kind, mk, sig)
                    cell = combo_cells[key]
                    for grp in groups:
                        cell[grp].append(outcome)
                    cell["full"].append(outcome)
                    cell[oos].append(outcome)

    rows: list[dict] = []
    for (market, kind, mk, sig), scope_outcomes in combo_cells.items():
        full_outcomes = scope_outcomes.get("full", [])
        if len(full_outcomes) < MIN_COMBO_GRADED:
            continue  # same emission gate as production
        scopes: dict[str, dict] = {}
        for grp in SEG_GROUPS:
            scopes[grp] = _agg_combo(scope_outcomes.get(grp, []))
        scopes["first_half"] = _agg_combo(scope_outcomes.get("first_half", []))
        scopes["second_half"] = _agg_combo(scope_outcomes.get("second_half", []))
        scopes["recent"] = None  # recent-window decay omitted for combos (documented)

        rating, trust, flags, comp = rate_pocket(scopes, args)
        rows.append({
            "market_type": market, "combo_kind": kind, "models_key": mk, "state_signature": sig,
            "state_full": scopes["full"]["state"],
            "scopes": scopes, "flags": flags, "trust_score": trust, "rating": rating,
            "components": comp,
        })

    rows.sort(key=lambda r: r["trust_score"], reverse=True)
    return rows


# ============================================================================
# Output
# ============================================================================

_SCOPE_ORDER_SINGLE = ["full", "regular", "play_in", "playoffs", "postseason",
                       "last300", "last150", "last75", "first_half", "second_half"]
_SCOPE_ORDER_COMBO = ["full", "regular", "play_in", "playoffs", "postseason", "first_half", "second_half"]


def _scope_csv_cols(scope: str, include_wr: bool = True) -> list[str]:
    cols = [f"{scope}_graded", f"{scope}_roi"]
    if include_wr:
        cols.insert(1, f"{scope}_win_rate")
    return cols


def write_single_csv(path: Path, rows: list[dict]) -> None:
    fields = ["model", "market_type", "edge_bucket", "state_full", "rating", "trust_score"]
    for s in _SCOPE_ORDER_SINGLE:
        fields += _scope_csv_cols(s)
    fields += ["first_half_state", "flags"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            row = {"model": r["model"], "market_type": r["market_type"], "edge_bucket": r["edge_bucket"],
                   "state_full": r["state_full"], "rating": r["rating"], "trust_score": r["trust_score"],
                   "first_half_state": r["scopes"]["first_half"]["state"], "flags": ";".join(r["flags"])}
            for s in _SCOPE_ORDER_SINGLE:
                sc = r["scopes"][s]
                row[f"{s}_graded"] = sc["graded"]
                row[f"{s}_win_rate"] = sc["win_rate"]
                row[f"{s}_roi"] = sc["roi"]
            w.writerow(row)


def write_combo_csv(path: Path, rows: list[dict]) -> None:
    fields = ["market_type", "combo_kind", "models_key", "state_signature", "state_full", "rating", "trust_score"]
    for s in _SCOPE_ORDER_COMBO:
        fields += _scope_csv_cols(s)
    fields += ["first_half_state", "flags"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            row = {"market_type": r["market_type"], "combo_kind": r["combo_kind"], "models_key": r["models_key"],
                   "state_signature": r["state_signature"], "state_full": r["state_full"], "rating": r["rating"],
                   "trust_score": r["trust_score"], "first_half_state": r["scopes"]["first_half"]["state"],
                   "flags": ";".join(r["flags"])}
            for s in _SCOPE_ORDER_COMBO:
                sc = r["scopes"][s]
                row[f"{s}_graded"] = sc["graded"]
                row[f"{s}_win_rate"] = sc["win_rate"]
                row[f"{s}_roi"] = sc["roi"]
            w.writerow(row)


# Short, human-readable decision string per rating (used in the stable dashboard artifact).
_RATING_RECOMMENDATION = {
    "KEEP": "Trust — held up out-of-sample and in the postseason.",
    "WATCH": "Monitor — mixed signal; not confirmed out-of-sample.",
    "FADE": "Fade — decayed recently or failed the postseason.",
    "KILL": "Remove — negative full-season or failed the hold-out.",
}


def _scope_roi(r: dict, scope: str) -> Optional[float]:
    sc = r["scopes"].get(scope)
    if not isinstance(sc, dict):
        return None
    return sc.get("roi")


def build_stable_robustness_doc(ctx: dict) -> dict:
    """Compact, join-ready artifact for the dashboard (stable 'latest' file).

    Singles keyed by (model, market_type, edge_bucket); combos keyed by
    (market_type, combo_kind, models_key, state_signature). Read-only projection of
    the same recomputed rows that back the timestamped outputs.
    """
    singles_out: list[dict] = []
    for r in ctx["single_rows"]:
        singles_out.append({
            "model": r["model"],
            "market_type": r["market_type"],
            "edge_bucket": r["edge_bucket"],
            "rating": r["rating"],
            "trust_score": r["trust_score"],
            "full_roi": _scope_roi(r, "full"),
            "second_half_roi": _scope_roi(r, "second_half"),
            "recent_roi": _scope_roi(r, "recent"),
            "postseason_roi": _scope_roi(r, "postseason"),
            "flags": list(r["flags"]),
            "recommendation": _RATING_RECOMMENDATION.get(r["rating"], ""),
        })
    combos_out: list[dict] = []
    for r in ctx["combo_rows"]:
        combos_out.append({
            "market_type": r["market_type"],
            "combo_kind": r["combo_kind"],
            "models_key": r["models_key"],
            "state_signature": r["state_signature"],
            "rating": r["rating"],
            "trust_score": r["trust_score"],
            "full_roi": _scope_roi(r, "full"),
            "second_half_roi": _scope_roi(r, "second_half"),
            "recent_roi": _scope_roi(r, "recent"),
            "postseason_roi": _scope_roi(r, "postseason"),
            "flags": list(r["flags"]),
            "recommendation": _RATING_RECOMMENDATION.get(r["rating"], ""),
        })
    return {
        "schema_version": 1,
        "league": LEAGUE,
        "generated_at_utc": ctx["generated_at_utc"],
        "source_backtest_dir": ctx["backtest_dir"],
        "source_analysis_dir": ctx.get("output_dir_name"),
        "rating_counts": ctx["rating_counts"],
        "singles": singles_out,
        "combos": combos_out,
    }


def _single_label(r: dict) -> str:
    return f"{r['model']} · {r['market_type']} · {r['edge_bucket']}"


def _combo_label(r: dict) -> str:
    return f"{r['combo_kind']} {r['market_type']} · {r['models_key']}"


def write_markdown(path: Path, ctx: dict) -> None:
    L: list[str] = []
    s_rows = ctx["single_rows"]
    c_rows = ctx["combo_rows"]
    counts = ctx["rating_counts"]

    def _scope(r, sc, key):
        v = r["scopes"][sc][key]
        return v

    L.append("# NBA Pocket Robustness Report")
    L.append("")
    L.append(f"- Generated (UTC): `{ctx['generated_at_utc']}`")
    L.append(f"- Backtest source: `{ctx['backtest_dir']}`")
    L.append(f"- Out-of-sample cutoff date (first < cutoff <= second): `{ctx['oos_cutoff']}`")
    L.append(f"- Play-in start `{ctx['play_in_start']}` | Playoff start `{ctx['playoff_start']}`")
    L.append(f"- Thresholds: min_keep_sample={ctx['args']['min_keep_sample']}, "
             f"min_post_sample={ctx['args']['min_post_sample']}, min_recent_sample={ctx['args']['min_recent_sample']}, "
             f"recent_window_primary={ctx['args']['recent_window_primary']}, roi_scale={ctx['args']['roi_scale']}, "
             f"kill_second_half_roi={ctx['args']['kill_second_half_roi']}, kill_recent_roi={ctx['args']['kill_recent_roi']}")
    L.append(f"- ROI accounting: -110 (WIN +{PAYOUT_MULTIPLIER:.4f}u, LOSS -1u, PUSH 0u); "
             f"breakeven win rate ~{BREAKEVEN_WIN_RATE:.4f}; pushes in denominator.")
    L.append("")

    # Executive summary.
    L.append("## Executive summary")
    L.append("")
    L.append(f"- Single-model pockets analyzed: **{len(s_rows)}** | combo pockets: **{len(c_rows)}**")
    L.append(f"- Single ratings: " + ", ".join(f"**{k}**={counts['single'].get(k, 0)}" for k in ("KEEP", "WATCH", "FADE", "KILL")))
    L.append(f"- Combo ratings: " + ", ".join(f"**{k}**={counts['combo'].get(k, 0)}" for k in ("KEEP", "WATCH", "FADE", "KILL")))
    pos_full = [r for r in s_rows if _is_pos(r["scopes"]["full"])]
    pos_but_h2_neg = [r for r in pos_full if _is_neg(r["scopes"]["second_half"])]
    pos_but_post_neg = [r for r in pos_full if _is_neg(r["scopes"]["postseason"], ctx['args']['min_post_sample'])]
    L.append(f"- Single pockets positive full-season: **{len(pos_full)}**; of those, "
             f"**{len(pos_but_h2_neg)}** were negative in the second half (out-of-sample) and "
             f"**{len(pos_but_post_neg)}** were negative in the postseason.")
    L.append("")
    L.append("> Read this as a trust filter on the season-long pocket layer: a high season ROI that does not "
             "survive the second-half hold-out or the postseason is most likely a backtest artifact.")
    L.append("")

    def _single_table(rows, title, note=""):
        L.append(f"### {title}")
        if note:
            L.append("")
            L.append(note)
        L.append("")
        if not rows:
            L.append("_None._")
            L.append("")
            return
        L.append("| Pocket | Trust | Full ROI (n) | 2nd-half ROI (n) | Postseason ROI (n) | Recent ROI (n) | Flags |")
        L.append("|---|---|---|---|---|---|---|")
        for r in rows:
            full = r["scopes"]["full"]; h2 = r["scopes"]["second_half"]
            post = r["scopes"]["postseason"]; rec = r["scopes"]["recent"]
            L.append(
                f"| {_single_label(r)} | {r['trust_score']:.0f} | "
                f"{_fmt_roi(full['roi'])} ({full['graded']}) | {_fmt_roi(h2['roi'])} ({h2['graded']}) | "
                f"{_fmt_roi(post['roi'])} ({post['graded']}) | {_fmt_roi(rec['roi'])} ({rec['graded']}) | "
                f"{', '.join(r['flags']) or '-'} |"
            )
        L.append("")

    keep = [r for r in s_rows if r["rating"] == "KEEP"]
    watch = [r for r in s_rows if r["rating"] == "WATCH"]
    fade = [r for r in s_rows if r["rating"] == "FADE"]
    kill = [r for r in s_rows if r["rating"] == "KILL"]

    L.append("## Single-model pockets by rating")
    L.append("")
    _single_table(keep[:15], "Top KEEP pockets")
    _single_table(watch[:15], "Top WATCH pockets")
    _single_table(fade[:15], "Top FADE pockets")
    _single_table(sorted(kill, key=lambda r: (r["scopes"]["full"]["roi"] or 0))[:15], "Top KILL pockets",
                  "_Sorted worst full-season ROI first._")

    # Specific failure lists.
    L.append("## Positive-season pockets that failed in the playoffs")
    L.append("")
    failed_po = [r for r in pos_full if _is_neg(r["scopes"]["playoffs"], ctx['args']['min_post_sample'])]
    if failed_po:
        L.append("| Pocket | Full ROI (n) | Playoff ROI (n) |")
        L.append("|---|---|---|")
        for r in sorted(failed_po, key=lambda r: r["scopes"]["playoffs"]["roi"] or 0):
            L.append(f"| {_single_label(r)} | {_fmt_roi(r['scopes']['full']['roi'])} ({r['scopes']['full']['graded']}) | "
                     f"{_fmt_roi(r['scopes']['playoffs']['roi'])} ({r['scopes']['playoffs']['graded']}) |")
    else:
        L.append("_None met the postseason sample threshold._")
    L.append("")

    L.append("## Positive-season pockets that decayed recently")
    L.append("")
    decayed = [r for r in pos_full if _is_neg(r["scopes"]["recent"], ctx['args']['min_recent_sample'])]
    if decayed:
        L.append(f"_Recent window = last {ctx['args']['recent_window_primary']} graded legs._")
        L.append("")
        L.append("| Pocket | Full ROI (n) | Recent ROI (n) | State |")
        L.append("|---|---|---|---|")
        for r in sorted(decayed, key=lambda r: r["scopes"]["recent"]["roi"] or 0):
            L.append(f"| {_single_label(r)} | {_fmt_roi(r['scopes']['full']['roi'])} ({r['scopes']['full']['graded']}) | "
                     f"{_fmt_roi(r['scopes']['recent']['roi'])} ({r['scopes']['recent']['graded']}) | {r['state_full']} |")
    else:
        L.append("_None._")
    L.append("")

    L.append("## First-half hot pockets that failed the second half (overfitting test)")
    L.append("")
    oos_fail = [r for r in s_rows if "first_half_hot_second_half_negative" in r["flags"]]
    if oos_fail:
        L.append("| Pocket | 1st-half ROI (n) | 2nd-half ROI (n) |")
        L.append("|---|---|---|")
        for r in oos_fail:
            h1 = r["scopes"]["first_half"]; h2 = r["scopes"]["second_half"]
            L.append(f"| {_single_label(r)} | {_fmt_roi(h1['roi'])} ({h1['graded']}) | {_fmt_roi(h2['roi'])} ({h2['graded']}) |")
    else:
        L.append("_No first-half-hot pocket flipped negative out-of-sample._")
    L.append("")

    # Combos.
    L.append("## Combo pockets (per-segment recompute)")
    L.append("")
    L.append("_Combo `state_signature` uses full-season single-pocket states (production basis); outcomes are "
             "partitioned by segment and by the out-of-sample half. Recent-window decay is not computed for combos._")
    L.append("")
    if c_rows:
        L.append("| Combo | Rating | Trust | Full ROI (n) | 2nd-half ROI (n) | Post ROI (n) | Flags |")
        L.append("|---|---|---|---|---|---|---|")
        for r in c_rows[:20]:
            full = r["scopes"]["full"]; h2 = r["scopes"]["second_half"]; post = r["scopes"]["postseason"]
            L.append(f"| {_combo_label(r)} | {r['rating']} | {r['trust_score']:.0f} | "
                     f"{_fmt_roi(full['roi'])} ({full['graded']}) | {_fmt_roi(h2['roi'])} ({h2['graded']}) | "
                     f"{_fmt_roi(post['roi'])} ({post['graded']}) | {', '.join(r['flags']) or '-'} |")
    else:
        L.append("_No combo pockets cleared the MIN_COMBO_GRADED gate._")
    L.append("")

    # Recommendations.
    L.append("## Best candidates for next season")
    L.append("")
    best = [r for r in keep if not (set(r["flags"]) & NEGATIVE_FLAGS)][:10]
    if best:
        for r in best:
            full = r["scopes"]["full"]; h2 = r["scopes"]["second_half"]
            pos_flag = " (OOS-confirmed)" if "first_half_hot_second_half_positive" in r["flags"] else ""
            L.append(f"- **{_single_label(r)}**{pos_flag} — trust {r['trust_score']:.0f}; full {_fmt_roi(full['roi'])} "
                     f"(n={full['graded']}), 2nd-half {_fmt_roi(h2['roi'])} (n={h2['graded']}).")
    else:
        L.append("_No KEEP pockets free of negative-decay flags; treat all current pockets as provisional._")
    L.append("")

    L.append("## Pockets to remove or hide from the dashboard")
    L.append("")
    remove = kill + fade
    if remove:
        for r in sorted(remove, key=lambda r: r["trust_score"])[:20]:
            L.append(f"- **{_single_label(r)}** ({r['rating']}, trust {r['trust_score']:.0f}) — {', '.join(r['flags']) or 'negative full-season'}.")
    else:
        L.append("_Nothing flagged for removal._")
    L.append("")

    # Dashboard state recommendation.
    L.append("## Recommendation: should the dashboard keep showing season-long hot/warm/cold?")
    L.append("")
    keep_n = counts['single'].get("KEEP", 0)
    bad_n = counts['single'].get("FADE", 0) + counts['single'].get("KILL", 0)
    total_n = max(1, len(s_rows))
    artifact_rate = len(pos_but_h2_neg) / max(1, len(pos_full)) if pos_full else 0.0
    L.append(f"- Of {len(pos_full)} positive-season single pockets, {artifact_rate * 100:.0f}% did not hold up in the "
             f"out-of-sample second half. KEEP={keep_n}, FADE+KILL={bad_n} of {total_n}.")
    if artifact_rate >= 0.4 or keep_n == 0:
        L.append("- **Recommendation: do NOT rely on the season-long hot/warm/cold state as-is.** A large share of "
                 "season-positive pockets fail out-of-sample/postseason, so the current state label overstates trust. "
                 "Prefer surfacing the trust rating (KEEP/WATCH/FADE/KILL) or at minimum annotate season state with "
                 "second-half and postseason ROI. (No code changed here — this is a recommendation only.)")
    else:
        L.append("- **Recommendation: season-long state is usable but should be annotated** with second-half and "
                 "postseason ROI so users can see decay. Hide FADE/KILL pockets from the primary view.")
    L.append("")

    # Caveats.
    L.append("## Assumptions & caveats")
    L.append("")
    for line in ctx["load_log"]:
        L.append(f"- {line}")
    L.append(f"- Segment counts: " + ", ".join(f"{k}={v}" for k, v in sorted(ctx['segment_counts'].items())))
    L.append("- Single-model pocket math reuses production `_aggregate_for_bucket` / `_classify_state` and "
             "`determine_band`; ROI/state are identical to the live pocket layer.")
    L.append("- Combo `state_signature` uses full-season states (matches production keys); per-segment combo outcomes "
             "are recomputed; combo recent-window decay is intentionally omitted.")
    L.append("- Out-of-sample split is a single global date cut (first-half train, second-half test); it is a "
             "stability check, not a walk-forward backtest.")
    L.append("- Read-only: no production builders, dashboard, models, scoring, or backtests were modified.")
    L.append("")

    path.write_text("\n".join(L), encoding="utf-8")


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="NBA pocket robustness analysis (read-only).")
    parser.add_argument("--play-in-start-date", default=DEFAULT_PLAY_IN_START)
    parser.add_argument("--playoff-start-date", default=DEFAULT_PLAYOFF_START)
    parser.add_argument("--backtest-dir", default=None)
    parser.add_argument("--min-keep-sample", type=int, default=100)
    parser.add_argument("--min-post-sample", type=int, default=20)
    parser.add_argument("--min-recent-sample", type=int, default=30,
                        help="Min graded legs in a recent window before its sign is trusted for flags/rating.")
    parser.add_argument("--recent-window-primary", type=int, default=75, choices=[75, 150, 300])
    parser.add_argument("--roi-scale", type=float, default=0.05,
                        help="ROI that maps to full +1 trust component (default 5%).")
    parser.add_argument("--kill-second-half-roi", type=float, default=-0.05)
    parser.add_argument("--kill-recent-roi", type=float, default=-0.08)
    parser.add_argument("--emit-latest", action="store_true",
                        help="Also write a stable join-ready artifact to "
                             "data/nba/view/nba_pocket_robustness_latest.json (timestamped outputs unchanged).")
    args = parser.parse_args()

    play_in_start = _parse_iso_date(args.play_in_start_date)
    playoff_start = _parse_iso_date(args.playoff_start_date)
    if play_in_start is None or playoff_start is None or play_in_start > playoff_start:
        print("ERROR: invalid date window. Use YYYY-MM-DD with play-in <= playoff.")
        return 2

    load_log: list[str] = []
    try:
        bt_dir = resolve_backtest_dir(args.backtest_dir, load_log)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1

    games = _load_json_safe(bt_dir / "backtest_games.json", load_log)
    if not isinstance(games, list) or not games:
        print(f"ERROR: backtest_games.json missing/corrupt/empty in {bt_dir}")
        for line in load_log:
            print(f"  {line}")
        return 1

    # Reference-only loads (logged; the recompute is authoritative).
    _load_json_safe(bt_dir / "nba_model_pockets.json", load_log)
    _load_json_safe(bt_dir / "nba_model_combo_pockets.json", load_log)

    # Global out-of-sample cutoff: median of present game dates.
    dates = sorted({str(g.get("game_date") or "")[:10] for g in games if g.get("game_date")})
    if not dates:
        print("ERROR: no game_date values present; cannot segment or split.")
        return 1
    cutoff = dates[len(dates) // 2]
    args._oos_cutoff = cutoff

    games_sorted = sorted(games, key=lambda g: (str(g.get("game_date") or "")[:10],
                                                str(g.get("canonical_game_id") or g.get("game_id") or "")))

    segment_counts: dict[str, int] = defaultdict(int)
    for g in games_sorted:
        segment_counts[classify_segment(g, play_in_start, playoff_start)] += 1

    single_rows = build_single_pockets(games_sorted, play_in_start, playoff_start, args)
    combo_rows = build_combo_pockets(games_sorted, single_rows, play_in_start, playoff_start, args)

    rating_counts = {
        "single": {k: sum(1 for r in single_rows if r["rating"] == k) for k in ("KEEP", "WATCH", "FADE", "KILL")},
        "combo": {k: sum(1 for r in combo_rows if r["rating"] == k) for k in ("KEEP", "WATCH", "FADE", "KILL")},
    }

    ctx = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "backtest_dir": bt_dir.name,
        "oos_cutoff": cutoff,
        "play_in_start": args.play_in_start_date,
        "playoff_start": args.playoff_start_date,
        "segment_counts": dict(segment_counts),
        "load_log": load_log,
        "single_rows": single_rows,
        "combo_rows": combo_rows,
        "rating_counts": rating_counts,
        "args": {
            "min_keep_sample": args.min_keep_sample, "min_post_sample": args.min_post_sample,
            "min_recent_sample": args.min_recent_sample, "recent_window_primary": args.recent_window_primary,
            "roi_scale": args.roi_scale, "kill_second_half_roi": args.kill_second_half_roi,
            "kill_recent_roi": args.kill_recent_roi,
        },
    }

    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / "data" / LEAGUE / "analysis" / f"pocket_robustness_{run_ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx["output_dir_name"] = out_dir.name

    write_markdown(out_dir / "pocket_robustness_summary.md", ctx)
    write_single_csv(out_dir / "pocket_robustness_single_model.csv", single_rows)
    write_combo_csv(out_dir / "pocket_robustness_combo.csv", combo_rows)
    with (out_dir / "pocket_robustness_tables.json").open("w", encoding="utf-8") as f:
        json.dump(ctx, f, indent=2, default=str)

    stable_path: Optional[Path] = None
    if args.emit_latest:
        stable_doc = build_stable_robustness_doc(ctx)
        view_dir = PROJECT_ROOT / "data" / LEAGUE / "view"
        view_dir.mkdir(parents=True, exist_ok=True)
        stable_path = view_dir / "nba_pocket_robustness_latest.json"
        with stable_path.open("w", encoding="utf-8") as f:
            json.dump(stable_doc, f, indent=2, default=str)

    print("NBA pocket robustness written:")
    print(f"  Backtest source : {bt_dir.name}")
    print(f"  OOS cutoff date : {cutoff}")
    print(f"  Output dir      : {out_dir}")
    print(f"  Single pockets  : {len(single_rows)} ({rating_counts['single']})")
    print(f"  Combo pockets   : {len(combo_rows)} ({rating_counts['combo']})")
    if stable_path is not None:
        print(f"  Stable artifact : {stable_path}")
    for line in load_log:
        print(f"  log: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
