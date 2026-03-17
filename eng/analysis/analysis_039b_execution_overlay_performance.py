"""
analysis_039b_execution_overlay_performance.py

Analyzes performance by execution overlay bucket.

Buckets:
  - Dual Sweet Spot
  - Spread Sweet Spot
  - Total Sweet Spot
  - Neutral
  - Avoid
  - All Games

Measures:
  - Games
  - Win %
  - ROI (assumes -110 pricing)

Writes execution_overlay_performance.json to the same backtest dir when run,
for use by the dashboard (Execution Overlay Backtest Reference).
"""

import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.io_helpers import get_backtest_output_root
from eng.execution.build_execution_overlay import compute_overlay_from_edges

BET_PRICE = -110
PAYOUT_MULTIPLIER = 100 / abs(BET_PRICE)  # ~0.9091

ORDERED_BUCKETS = [
    "Dual Sweet Spot",
    "Spread Sweet Spot",
    "Total Sweet Spot",
    "Neutral",
    "Avoid",
    "All Games",
]

# Dynamic mode: always emit these 4 buckets + All Games (039a artifact key for status lookup)
DYNAMIC_REQUIRED_BUCKETS = ["Dual Sweet Spot", "Spread Sweet Spot", "Total Sweet Spot", "Avoid", "All Games"]
BUCKET_TO_ARTIFACT_KEY = {
    "Dual Sweet Spot": "dual_sweet_spot",
    "Spread Sweet Spot": "spread_sweet_spot",
    "Total Sweet Spot": "total_sweet_spot",
    "Avoid": "avoid",
}

# Human-readable rule for each bucket (matches eng/execution/build_execution_overlay.py).
# ASCII only for console; dashboard can show same or richer.
BUCKET_EXPLANATIONS = {
    "Dual Sweet Spot": "Spread edge 1-4 pts, total edge 1-4 pts, total 225-242, spread line <10",
    "Spread Sweet Spot": "Spread edge 1-4 pts, spread line <12",
    "Total Sweet Spot": "Total edge 1-4 pts, total 225-242, spread line <12",
    "Neutral": "Outside sweet spot and avoid bands",
    "Avoid": "Spread edge >6 or spread >=12, or total edge >8 or total <225",
    "All Games": "All graded games",
}

# League-specific total_avoid_below for dynamic Avoid explanation only (matches 039a GRID_CONFIG; artifact may have NBA value for both).
AVOID_TOTAL_BELOW_FOR_EXPLANATION = {"nba": 225, "ncaam": 120}

# NCAAM fixed baseline (aligned with 039a GRID_CONFIG["ncaam"]). Used only for 039b fixed reporting.
NCAAM_FIXED_TOTAL_LO, NCAAM_FIXED_TOTAL_HI = 135, 165
NCAAM_FIXED_TOTAL_AVOID_BELOW = 120
NCAAM_FIXED_SPREAD_AVOID_EDGE = 6
NCAAM_FIXED_SPREAD_AVOID_LINE = 12
NCAAM_FIXED_TOTAL_AVOID_EDGE = 8

# Fixed-mode explanations for NCAAM (total 135-165, total <120; not NBA 225-242).
BUCKET_EXPLANATIONS_NCAAM = {
    "Dual Sweet Spot": "Spread edge 1-4 pts, total edge 1-4 pts, total 135-165, spread line <10",
    "Spread Sweet Spot": "Spread edge 1-4 pts, spread line <12",
    "Total Sweet Spot": "Total edge 1-4 pts, total 135-165, spread line <12",
    "Neutral": "Outside sweet spot and avoid bands",
    "Avoid": "Spread edge >6 or spread >=12, or total edge >8 or total <120",
    "All Games": "All graded games",
}


def _compute_overlay_fixed_ncaam(spread_e, total_e, spread_line, vegas_total):
    """Compute execution overlay dict for NCAAM fixed mode using same numeric rules as 039a baseline.
    Returns dict with spread_sweet_spot, total_sweet_spot, dual_sweet_spot, spread_avoid, total_avoid; or None if any input missing."""
    if spread_e is None or total_e is None or spread_line is None or vegas_total is None:
        return None
    abs_se = abs(float(spread_e))
    abs_te = abs(float(total_e))
    spread_line = abs(float(spread_line))
    vegas_total = float(vegas_total)
    spread_sweet = 1 <= abs_se <= 4 and spread_line < NCAAM_FIXED_SPREAD_AVOID_LINE
    total_sweet = (
        1 <= abs_te <= 4
        and NCAAM_FIXED_TOTAL_LO <= vegas_total <= NCAAM_FIXED_TOTAL_HI
        and spread_line < NCAAM_FIXED_SPREAD_AVOID_LINE
    )
    dual_sweet = spread_sweet and total_sweet and spread_line < 10
    spread_avoid = abs_se > NCAAM_FIXED_SPREAD_AVOID_EDGE or spread_line >= NCAAM_FIXED_SPREAD_AVOID_LINE
    total_avoid = abs_te > NCAAM_FIXED_TOTAL_AVOID_EDGE or vegas_total < NCAAM_FIXED_TOTAL_AVOID_BELOW
    return {
        "spread_sweet_spot": spread_sweet,
        "total_sweet_spot": total_sweet,
        "dual_sweet_spot": dual_sweet,
        "spread_avoid": spread_avoid,
        "total_avoid": total_avoid,
    }


def _dynamic_bucket_explanation(bucket: str, chosen_thresholds: dict, league: str | None = None) -> str:
    """Build explanation from dynamic chosen_thresholds (039a artifact). Used only in dynamic mode."""
    if bucket == "All Games":
        return "All graded games"
    if bucket == "Neutral":
        return "Outside sweet spot and avoid bands"
    if bucket == "Avoid":
        avoid = chosen_thresholds.get("avoid") or {}
        se = avoid.get("spread_edge_above")
        sl = avoid.get("spread_line_at_or_above")
        te = avoid.get("total_edge_above")
        tb = avoid.get("total_below")
        if league is not None:
            tb = AVOID_TOTAL_BELOW_FOR_EXPLANATION.get(league, tb)
        parts = []
        if se is not None:
            parts.append(f"Spread edge >{se}")
        if sl is not None:
            parts.append(f"spread line >={sl}")
        if te is not None:
            parts.append(f"total edge >{te}")
        if tb is not None:
            parts.append(f"total <{tb}")
        return ", ".join(parts) if parts else "Spread edge >6 or spread >=12, or total edge >8 or total <225"
    if bucket == "Spread Sweet Spot":
        cfg = chosen_thresholds.get("spread_sweet_spot")
        if not cfg or not isinstance(cfg, dict):
            return "Spread sweet spot (dynamic, inactive)"
        emin, emax = cfg.get("edge_min"), cfg.get("edge_max")
        cap = cfg.get("spread_line_max_exclusive")
        if emin is not None and emax is not None and cap is not None:
            return f"Spread edge {emin}-{emax} pts, spread line <{cap}"
        return "Spread sweet spot (dynamic)"
    if bucket == "Total Sweet Spot":
        cfg = chosen_thresholds.get("total_sweet_spot")
        if not cfg or not isinstance(cfg, dict):
            return "Total sweet spot (dynamic, inactive)"
        emin, emax = cfg.get("edge_min"), cfg.get("edge_max")
        t_lo, t_hi = cfg.get("total_min"), cfg.get("total_max")
        cap = cfg.get("spread_line_max_exclusive")
        if all(x is not None for x in (emin, emax, t_lo, t_hi, cap)):
            return f"Total edge {emin}-{emax} pts, total {t_lo}-{t_hi}, spread line <{cap}"
        return "Total sweet spot (dynamic)"
    if bucket == "Dual Sweet Spot":
        cfg = chosen_thresholds.get("dual_sweet_spot")
        if not cfg or not isinstance(cfg, dict):
            return "Dual sweet spot (dynamic, inactive)"
        se_lo = cfg.get("spread_edge_min")
        se_hi = cfg.get("spread_edge_max")
        te_lo = cfg.get("total_edge_min")
        te_hi = cfg.get("total_edge_max")
        t_lo = cfg.get("total_min")
        t_hi = cfg.get("total_max")
        cap = cfg.get("spread_line_max_exclusive")
        if all(x is not None for x in (se_lo, se_hi, te_lo, te_hi, t_lo, t_hi, cap)):
            return f"Spread edge {se_lo}-{se_hi} pts, total edge {te_lo}-{te_hi} pts, total {t_lo}-{t_hi}, spread line <{cap}"
        return "Dual sweet spot (dynamic)"
    return ""


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_backtest_dir_and_games_path(league: str, backtest_dir: str | None = None):
    """Return (latest_backtest_dir, path_to_backtest_games.json)."""
    backtest_root = get_backtest_output_root(league)
    if not backtest_root.exists():
        raise FileNotFoundError(f"Backtest root not found: {backtest_root}")
    if backtest_dir:
        target = backtest_root / backtest_dir.strip()
        if not target.exists() or not target.is_dir():
            raise FileNotFoundError(f"Backtest dir not found: {target}")
        return target, target / "backtest_games.json"
    subdirs = [d for d in backtest_root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
    if not subdirs:
        raise FileNotFoundError(f"No backtest_* directories in {backtest_root}")
    latest_dir = max(subdirs, key=lambda d: d.stat().st_mtime)
    return latest_dir, latest_dir / "backtest_games.json"


def load_and_validate_dynamic_thresholds(latest_dir: Path):
    """
    Load dynamic_sweetspot_thresholds.json from latest_dir.
    Return (chosen_thresholds, artifact_buckets) if valid, else (None, None).
    Valid = file exists, valid JSON, has chosen_thresholds with avoid.
    artifact_buckets = data["buckets"] for status lookup.
    """
    path = latest_dir / "dynamic_sweetspot_thresholds.json"
    if not path.exists():
        return None, None
    try:
        data = load_json(path)
    except (json.JSONDecodeError, OSError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    ct = data.get("chosen_thresholds")
    if not isinstance(ct, dict):
        return None, None
    if ct.get("avoid") is None or not isinstance(ct["avoid"], dict):
        return None, None
    artifact_buckets = data.get("buckets") or {}
    return ct, artifact_buckets


def compute_overlay_from_dynamic_thresholds(spread_edge, total_edge, spread_line, vegas_total, chosen_thresholds, league=None):
    """
    Compute execution overlay dict from four numerics and chosen_thresholds (from 039a artifact).
    Returns dict with same keys as compute_overlay_from_edges. Uses only chosen_thresholds; no fixed fallback.
    For NCAAM, uses league-specific total-below (120) for avoid so games are not all forced into Avoid.
    """
    if spread_edge is None or total_edge is None or spread_line is None or vegas_total is None:
        return None
    abs_se = abs(float(spread_edge))
    abs_te = abs(float(total_edge))
    abs_spread = abs(float(spread_line))
    vt = float(vegas_total)

    spread_cfg = chosen_thresholds.get("spread_sweet_spot")
    if spread_cfg and isinstance(spread_cfg, dict):
        emin = spread_cfg.get("edge_min")
        emax = spread_cfg.get("edge_max")
        cap = spread_cfg.get("spread_line_max_exclusive")
        spread_sweet_spot = (
            emin is not None and emax is not None and cap is not None
            and emin <= abs_se <= emax
            and abs_spread < cap
        )
    else:
        spread_sweet_spot = False

    total_cfg = chosen_thresholds.get("total_sweet_spot")
    if total_cfg and isinstance(total_cfg, dict):
        emin = total_cfg.get("edge_min")
        emax = total_cfg.get("edge_max")
        t_lo = total_cfg.get("total_min")
        t_hi = total_cfg.get("total_max")
        cap = total_cfg.get("spread_line_max_exclusive")
        total_sweet_spot = (
            emin is not None and emax is not None and t_lo is not None and t_hi is not None and cap is not None
            and emin <= abs_te <= emax
            and t_lo <= vt <= t_hi
            and abs_spread < cap
        )
    else:
        total_sweet_spot = False

    dual_cfg = chosen_thresholds.get("dual_sweet_spot")
    if dual_cfg and isinstance(dual_cfg, dict):
        se_lo = dual_cfg.get("spread_edge_min")
        se_hi = dual_cfg.get("spread_edge_max")
        te_lo = dual_cfg.get("total_edge_min")
        te_hi = dual_cfg.get("total_edge_max")
        t_lo = dual_cfg.get("total_min")
        t_hi = dual_cfg.get("total_max")
        cap = dual_cfg.get("spread_line_max_exclusive")
        dual_sweet_spot = (
            se_lo is not None and se_hi is not None
            and te_lo is not None and te_hi is not None
            and t_lo is not None and t_hi is not None
            and cap is not None
            and se_lo <= abs_se <= se_hi
            and te_lo <= abs_te <= te_hi
            and t_lo <= vt <= t_hi
            and abs_spread < cap
        )
    else:
        dual_sweet_spot = False

    avoid = chosen_thresholds.get("avoid") or {}
    se_above = avoid.get("spread_edge_above")
    sl_at_or_above = avoid.get("spread_line_at_or_above")
    te_above = avoid.get("total_edge_above")
    total_below = avoid.get("total_below")
    if (league or "").strip().lower() == "ncaam":
        total_below = AVOID_TOTAL_BELOW_FOR_EXPLANATION.get("ncaam", total_below)  # 120 for NCAAM dynamic
    spread_avoid = (
        (se_above is not None and abs_se > se_above)
        or (sl_at_or_above is not None and abs_spread >= sl_at_or_above)
    )
    total_avoid = (
        (te_above is not None and abs_te > te_above)
        or (total_below is not None and vt < total_below)
    )

    return {
        "spread_sweet_spot": spread_sweet_spot,
        "total_sweet_spot": total_sweet_spot,
        "dual_sweet_spot": dual_sweet_spot,
        "spread_avoid": spread_avoid,
        "total_avoid": total_avoid,
    }


def _row_numerics(g):
    """Return (spread_edge, total_edge, spread_line, vegas_total) or (None, None, None, None) if any missing."""
    spread_e = g.get("selected_spread_edge") if g.get("selected_spread_edge") is not None else g.get("Spread Edge")
    total_e = g.get("selected_total_edge") if g.get("selected_total_edge") is not None else g.get("Total Edge")
    try:
        spread_e = float(spread_e) if spread_e is not None else None
    except (TypeError, ValueError):
        spread_e = None
    try:
        total_e = float(total_e) if total_e is not None else None
    except (TypeError, ValueError):
        total_e = None
    spread_line = g.get("market_spread_home") or g.get("spread_home") or g.get("spread_home_last")
    try:
        spread_line = abs(float(spread_line)) if spread_line is not None else None
    except (TypeError, ValueError):
        spread_line = None
    vegas_total = g.get("market_total") or g.get("total") or g.get("total_last")
    try:
        vegas_total = float(vegas_total) if vegas_total is not None else None
    except (TypeError, ValueError):
        vegas_total = None
    return spread_e, total_e, spread_line, vegas_total


def classify_overlay(g):
    overlay = g.get("execution_overlay") or {}

    if overlay.get("dual_sweet_spot"):
        return "Dual Sweet Spot"

    if overlay.get("spread_sweet_spot") and not overlay.get("total_sweet_spot"):
        return "Spread Sweet Spot"

    if overlay.get("total_sweet_spot") and not overlay.get("spread_sweet_spot"):
        return "Total Sweet Spot"

    if overlay.get("spread_avoid") or overlay.get("total_avoid"):
        return "Avoid"

    return "Neutral"


def main():
    parser = argparse.ArgumentParser(description="Execution overlay bucket performance; writes JSON for dashboard.")
    parser.add_argument("--league", choices=["nba", "ncaam"], default="nba", help="League (default: nba)")
    parser.add_argument("--backtest-dir", default=None, help="Use this backtest folder (e.g. backtest_20260316_221942) instead of latest by mtime.")
    parser.add_argument(
        "--use-dynamic-sweetspots",
        action="store_true",
        help="Use dynamic_sweetspot_thresholds.json from latest backtest dir; write execution_overlay_performance_dynamic.json.",
    )
    args = parser.parse_args()
    league = args.league.strip().lower()

    latest_dir, games_path = get_latest_backtest_dir_and_games_path(league, args.backtest_dir)
    games = load_json(games_path)

    use_dynamic = False
    dynamic_thresholds = None
    dynamic_artifact_buckets = {}
    if args.use_dynamic_sweetspots:
        dynamic_thresholds, dynamic_artifact_buckets = load_and_validate_dynamic_thresholds(latest_dir)
        if dynamic_thresholds is not None:
            use_dynamic = True
        else:
            print(
                "Warning: --use-dynamic-sweetspots requested but dynamic_sweetspot_thresholds.json is missing, invalid, or incomplete; using fixed thresholds.",
                file=sys.stderr,
            )

    bucket_data = defaultdict(lambda: {
        "games": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "profit": 0.0
    })
    skipped_rows_dynamic = 0

    for g in games:

        spread_result = g.get("selected_spread_result") or g.get("spread_result")
        total_result = g.get("selected_total_result") or g.get("total_result")

        if spread_result is None or total_result is None:
            continue

        if use_dynamic:
            spread_e, total_e, spread_line, vegas_total = _row_numerics(g)
            if spread_e is None or total_e is None or spread_line is None or vegas_total is None:
                skipped_rows_dynamic += 1
                continue
            overlay = compute_overlay_from_dynamic_thresholds(
                spread_e, total_e, spread_line, vegas_total, dynamic_thresholds, league=league
            )
            if overlay:
                g["execution_overlay"] = overlay
        else:
            if not g.get("execution_overlay"):
                if league == "ncaam":
                    spread_e, total_e, spread_line, vegas_total = _row_numerics(g)
                    overlay = _compute_overlay_fixed_ncaam(spread_e, total_e, spread_line, vegas_total)
                else:
                    spread_e = g.get("selected_spread_edge") if g.get("selected_spread_edge") is not None else g.get("Spread Edge")
                    total_e = g.get("selected_total_edge") if g.get("selected_total_edge") is not None else g.get("Total Edge")
                    try:
                        spread_e = float(spread_e) if spread_e is not None else None
                    except (TypeError, ValueError):
                        spread_e = None
                    try:
                        total_e = float(total_e) if total_e is not None else None
                    except (TypeError, ValueError):
                        total_e = None
                    spread_home = g.get("market_spread_home") or g.get("spread_home") or g.get("spread_home_last")
                    vegas_total = g.get("market_total") or g.get("total") or g.get("total_last")
                    overlay = compute_overlay_from_edges(spread_e, total_e, spread_home, vegas_total)
                if overlay:
                    g["execution_overlay"] = overlay

        bucket = classify_overlay(g)

        for result in [spread_result, total_result]:

            if result not in ["WIN", "LOSS", "PUSH"]:
                continue

            bucket_data[bucket]["games"] += 1
            bucket_data["All Games"]["games"] += 1

            if result == "WIN":
                bucket_data[bucket]["wins"] += 1
                bucket_data[bucket]["profit"] += PAYOUT_MULTIPLIER
                bucket_data["All Games"]["wins"] += 1
                bucket_data["All Games"]["profit"] += PAYOUT_MULTIPLIER

            elif result == "LOSS":
                bucket_data[bucket]["losses"] += 1
                bucket_data[bucket]["profit"] -= 1
                bucket_data["All Games"]["losses"] += 1
                bucket_data["All Games"]["profit"] -= 1

            elif result == "PUSH":
                bucket_data[bucket]["pushes"] += 1
                bucket_data["All Games"]["pushes"] += 1

    if use_dynamic and skipped_rows_dynamic > 0:
        print(f"Dynamic mode: skipped {skipped_rows_dynamic} row(s) missing required numeric fields.", file=sys.stderr)

    print("\n=== EXECUTION OVERLAY PERFORMANCE ===\n")
    print(f"{'Bucket':<20} {'Games':<8} {'Win%':<8} {'ROI':<8}  Explanation")
    print("-" * 90)

    buckets_for_json = []

    if use_dynamic and dynamic_thresholds is not None:
        for bucket in DYNAMIC_REQUIRED_BUCKETS:
            bd = bucket_data.get(bucket)
            if not bd:
                bd = {"games": 0, "wins": 0, "losses": 0, "pushes": 0, "profit": 0.0}
            games = bd["games"]
            if games > 0:
                win_rate = round(bd["wins"] / games, 4)
                roi = round(bd["profit"] / games, 4)
            else:
                win_rate = None
                roi = None
            explanation = _dynamic_bucket_explanation(bucket, dynamic_thresholds, league=league)
            artifact_bucket = dynamic_artifact_buckets.get(BUCKET_TO_ARTIFACT_KEY.get(bucket, ""))
            status = (artifact_bucket.get("status") if isinstance(artifact_bucket, dict) else None) or ("active" if bucket == "Avoid" else None)
            row = {
                "Bucket": bucket,
                "Games": games,
                "Win%": win_rate,
                "ROI": roi,
                "Explanation": explanation,
            }
            if status is not None:
                row["status"] = status
            buckets_for_json.append(row)
            print(
                f"{bucket:<20} "
                f"{games:<8} "
                f"{str(win_rate) if win_rate is not None else 'null':<8} "
                f"{str(roi) if roi is not None else 'null':<8}  "
                f"{explanation}"
            )
    else:
        for bucket in ORDERED_BUCKETS:
            bd = bucket_data.get(bucket)
            if not bd or bd["games"] == 0:
                continue
            win_rate = bd["wins"] / bd["games"]
            roi = bd["profit"] / bd["games"]
            explanation = (BUCKET_EXPLANATIONS_NCAAM if league == "ncaam" else BUCKET_EXPLANATIONS).get(bucket, "")
            print(
                f"{bucket:<20} "
                f"{bd['games']:<8} "
                f"{round(win_rate,3):<8} "
                f"{round(roi,3):<8}  "
                f"{explanation}"
            )
            buckets_for_json.append({
                "Bucket": bucket,
                "Games": bd["games"],
                "Win%": round(win_rate, 4),
                "ROI": round(roi, 4),
                "Explanation": explanation,
            })

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "league": league,
        "source_backtest_dir": latest_dir.name,
        "threshold_source": "dynamic" if use_dynamic else "fixed",
        "buckets": buckets_for_json,
    }
    if use_dynamic:
        payload["dynamic_thresholds_source"] = latest_dir.name
        out_path = latest_dir / "execution_overlay_performance_dynamic.json"
    else:
        out_path = latest_dir / "execution_overlay_performance.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\nWrote: {out_path}")


if __name__ == "__main__":
    main()
