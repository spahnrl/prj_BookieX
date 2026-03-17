"""
analysis_039a_dynamic_sweetspot_discovery.py

Discovery-only: finds candidate sweet-spot thresholds from latest backtest evidence.
Does not modify 039b or build_execution_overlay. Writes one immutable artifact per
backtest folder: dynamic_sweetspot_thresholds.json.

V1: Fixed avoid thresholds; no runner integration.
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

BET_PRICE = -110
PAYOUT_MULTIPLIER = 100 / abs(BET_PRICE)

# V1 candidate search space
SPREAD_EDGE_BANDS = [(1, 3), (1, 4), (2, 4)]
TOTAL_EDGE_BANDS = [(1, 3), (1, 4), (2, 4)]
SPREAD_LINE_CAPS = [10, 12]
TOTAL_WINDOWS = [(222, 244), (225, 242)]

# Fixed avoid (v1 baseline only)
FIXED_SPREAD_AVOID_EDGE = 6
FIXED_SPREAD_AVOID_LINE = 12
FIXED_TOTAL_AVOID_EDGE = 8
FIXED_TOTAL_AVOID_TOTAL_BELOW = 225

# Guardrails
MIN_SAMPLE_SPREAD_SWEET = 75
MIN_SAMPLE_TOTAL_SWEET = 75
MIN_SAMPLE_DUAL_SWEET = 50
MIN_ROI = 0.03
MIN_WIN_RATE = 0.53
MIN_ROI_BEAT_BASELINE = 0.01
MATERIALLY_LARGER_SAMPLE_RATIO = 1.2

# League-specific total grid (total windows and avoid-below; spread bands/caps/guardrails shared)
GRID_CONFIG = {
    "nba": {
        "total_windows": [(222, 244), (225, 242)],
        "baseline_total_window": (225, 242),
        "total_avoid_below": 225,
    },
    "ncaam": {
        "total_windows": [(132, 158), (138, 168)],
        "baseline_total_window": (135, 165),
        "total_avoid_below": 120,
    },
}


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_backtest_dir_and_games_path(league: str, backtest_dir: str | None = None):
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


def _float(g, *keys, default=None):
    v = None
    for k in keys:
        v = g.get(k)
        if v is not None:
            break
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _result(g, spread_key, total_key):
    sr = g.get("selected_spread_result") or g.get("spread_result")
    tr = g.get("selected_total_result") or g.get("total_result")
    return sr, tr


def extract_game_rows(games: list, league: str) -> list:
    """Return list of (spread_edge, total_edge, spread_line, vegas_total, spread_result, total_result)."""
    rows = []
    for g in games:
        spread_e = _float(g, "selected_spread_edge", "Spread Edge")
        total_e = _float(g, "selected_total_edge", "Total Edge")
        spread_line = _float(g, "market_spread_home", "spread_home", "spread_home_last")
        if spread_line is not None:
            spread_line = abs(spread_line)
        vegas_total = _float(g, "market_total", "total", "total_last")
        sr, tr = _result(g, "selected_spread_result", "selected_total_result")
        if sr is None or tr is None:
            continue
        if spread_e is None or total_e is None or spread_line is None or vegas_total is None:
            continue
        rows.append((spread_e, total_e, spread_line, vegas_total, sr, tr))
    return rows


def classify_fixed(
    spread_edge: float,
    total_edge: float,
    spread_line: float,
    vegas_total: float,
    baseline_total_window: tuple[int, int] = (225, 242),
    total_avoid_below: int = FIXED_TOTAL_AVOID_TOTAL_BELOW,
) -> str:
    """Bucket using fixed baseline thresholds (same logic as build_execution_overlay)."""
    abs_se = abs(spread_edge)
    abs_te = abs(total_edge)
    t_lo, t_hi = baseline_total_window
    spread_sweet = 1 <= abs_se <= 4 and spread_line < 12
    total_sweet = 1 <= abs_te <= 4 and t_lo <= vegas_total <= t_hi and spread_line < 12
    dual_sweet = spread_sweet and total_sweet and spread_line < 10
    spread_avoid = abs_se > FIXED_SPREAD_AVOID_EDGE or spread_line >= FIXED_SPREAD_AVOID_LINE
    total_avoid = abs_te > FIXED_TOTAL_AVOID_EDGE or vegas_total < total_avoid_below
    if dual_sweet:
        return "Dual Sweet Spot"
    if spread_sweet and not total_sweet:
        return "Spread Sweet Spot"
    if total_sweet and not spread_sweet:
        return "Total Sweet Spot"
    if spread_avoid or total_avoid:
        return "Avoid"
    return "Neutral"


def classify_candidate(
    spread_edge: float,
    total_edge: float,
    spread_line: float,
    vegas_total: float,
    spread_band: tuple,
    total_band: tuple,
    spread_cap: int,
    total_window: tuple,
    total_avoid_below: int = FIXED_TOTAL_AVOID_TOTAL_BELOW,
) -> str:
    """Bucket using candidate thresholds. Dual uses spread_line < 10."""
    abs_se = abs(spread_edge)
    abs_te = abs(total_edge)
    se_lo, se_hi = spread_band
    te_lo, te_hi = total_band
    t_lo, t_hi = total_window
    spread_sweet = se_lo <= abs_se <= se_hi and spread_line < spread_cap
    total_sweet = te_lo <= abs_te <= te_hi and t_lo <= vegas_total <= t_hi and spread_line < spread_cap
    dual_sweet = spread_sweet and total_sweet and spread_line < 10
    spread_avoid = abs_se > FIXED_SPREAD_AVOID_EDGE or spread_line >= FIXED_SPREAD_AVOID_LINE
    total_avoid = abs_te > FIXED_TOTAL_AVOID_EDGE or vegas_total < total_avoid_below
    if dual_sweet:
        return "Dual Sweet Spot"
    if spread_sweet and not total_sweet:
        return "Spread Sweet Spot"
    if total_sweet and not spread_sweet:
        return "Total Sweet Spot"
    if spread_avoid or total_avoid:
        return "Avoid"
    return "Neutral"


def bucket_stats_from_rows(rows: list, classify_fn) -> dict:
    """Compute games, wins, losses, pushes, profit per bucket. classify_fn(row) -> bucket name."""
    data = defaultdict(lambda: {"games": 0, "wins": 0, "losses": 0, "pushes": 0, "profit": 0.0})
    for spread_e, total_e, spread_line, vegas_total, sr, tr in rows:
        bucket = classify_fn(spread_e, total_e, spread_line, vegas_total)
        for result in [sr, tr]:
            if result not in ("WIN", "LOSS", "PUSH"):
                continue
            data[bucket]["games"] += 1
            if result == "WIN":
                data[bucket]["wins"] += 1
                data[bucket]["profit"] += PAYOUT_MULTIPLIER
            elif result == "LOSS":
                data[bucket]["losses"] += 1
                data[bucket]["profit"] -= 1
            else:
                data[bucket]["pushes"] += 1
    return dict(data)


def roi_winrate(data: dict) -> tuple:
    if not data or data["games"] == 0:
        return None, None
    return data["profit"] / data["games"], data["wins"] / data["games"]


def run_candidates(
    rows: list,
    total_windows: list[tuple[int, int]] | None = None,
    total_avoid_below: int = FIXED_TOTAL_AVOID_TOTAL_BELOW,
) -> list:
    """Yield (config, bucket_stats) for each candidate. config = spread_band, total_band, spread_cap, total_window."""
    windows = total_windows if total_windows is not None else TOTAL_WINDOWS
    for se_band in SPREAD_EDGE_BANDS:
        for te_band in TOTAL_EDGE_BANDS:
            for spread_cap in SPREAD_LINE_CAPS:
                for total_window in windows:

                    def fn(se, te, sl, vt, _se_band=se_band, _te_band=te_band, _spread_cap=spread_cap, _total_window=total_window):
                        return classify_candidate(se, te, sl, vt, _se_band, _te_band, _spread_cap, _total_window, total_avoid_below)

                    stats = bucket_stats_from_rows(rows, fn)
                    yield (se_band, te_band, spread_cap, total_window), stats


def _beats_baseline(roi: float, sample: int, baseline_roi: float, baseline_n: int) -> bool:
    """True if candidate beats baseline: +0.01 ROI or same ROI with materially larger sample."""
    if baseline_n is None or baseline_n < 1:
        return True
    if baseline_roi is None:
        return True
    if roi >= baseline_roi + MIN_ROI_BEAT_BASELINE:
        return True
    if roi >= baseline_roi and sample >= MATERIALLY_LARGER_SAMPLE_RATIO * baseline_n:
        return True
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Discovery-only: dynamic sweet-spot thresholds from latest backtest. Writes dynamic_sweetspot_thresholds.json."
    )
    parser.add_argument("--league", choices=["nba", "ncaam"], default="nba", help="League (default: nba)")
    parser.add_argument("--backtest-dir", default=None, help="Use this backtest folder (e.g. backtest_20260316_221942) instead of latest by mtime.")
    args = parser.parse_args()
    league = args.league.strip().lower()
    grid_config = GRID_CONFIG[league]

    latest_dir, games_path = get_latest_backtest_dir_and_games_path(league, args.backtest_dir)
    games = load_json(games_path)
    rows = extract_game_rows(games, league)
    if not rows:
        print("No graded game rows with edges and results; cannot run discovery.")
        sys.exit(1)

    # Baseline (fixed) stats on same backtest
    fixed_stats = bucket_stats_from_rows(
        rows,
        lambda se, te, sl, vt: classify_fixed(
            se, te, sl, vt,
            baseline_total_window=grid_config["baseline_total_window"],
            total_avoid_below=grid_config["total_avoid_below"],
        ),
    )
    baseline_spread = fixed_stats.get("Spread Sweet Spot")
    baseline_total = fixed_stats.get("Total Sweet Spot")
    baseline_dual = fixed_stats.get("Dual Sweet Spot")
    baseline_avoid = fixed_stats.get("Avoid")

    def roi_n(bd):
        if not bd or bd["games"] == 0:
            return None, 0
        return bd["profit"] / bd["games"], bd["games"]

    baseline_spread_roi, baseline_spread_n = roi_n(baseline_spread)
    baseline_total_roi, baseline_total_n = roi_n(baseline_total)
    baseline_dual_roi, baseline_dual_n = roi_n(baseline_dual)

    # Run all candidates
    candidates_by_config = list(run_candidates(
        rows,
        total_windows=grid_config["total_windows"],
        total_avoid_below=grid_config["total_avoid_below"],
    ))

    # Spread Sweet Spot: always publish a best candidate or baseline; guardrails set status only
    spread_candidates = [
        (cfg, st) for cfg, st in candidates_by_config if st.get("Spread Sweet Spot") and st["Spread Sweet Spot"]["games"] >= MIN_SAMPLE_SPREAD_SWEET
    ]
    spread_sel = [
        (cfg, st["Spread Sweet Spot"])
        for cfg, st in spread_candidates
        if roi_winrate(st["Spread Sweet Spot"])[0] is not None
        and roi_winrate(st["Spread Sweet Spot"])[0] >= MIN_ROI
        and roi_winrate(st["Spread Sweet Spot"])[1] >= MIN_WIN_RATE
        and _beats_baseline(
            roi_winrate(st["Spread Sweet Spot"])[0],
            st["Spread Sweet Spot"]["games"],
            baseline_spread_roi,
            baseline_spread_n,
        )
    ]
    spread_any = [(cfg, st["Spread Sweet Spot"]) for cfg, st in candidates_by_config if st.get("Spread Sweet Spot") and st["Spread Sweet Spot"]["games"] >= 1]
    if spread_sel:
        best_spread = max(spread_sel, key=lambda x: (roi_winrate(x[1])[0], roi_winrate(x[1])[1], x[1]["games"]))
        spread_config, spread_bd = best_spread[0], best_spread[1]
        spread_active = True
        spread_status = "active"
        spread_explanation = f"Guardrails met; beats baseline (ROI {roi_winrate(spread_bd)[0]:.4f}, n={spread_bd['games']})."
    elif spread_candidates:
        best_spread = max(
            [(cfg, st["Spread Sweet Spot"]) for cfg, st in spread_candidates],
            key=lambda x: (roi_winrate(x[1])[0] or -1, roi_winrate(x[1])[1] or 0, x[1]["games"]),
        )
        spread_config, spread_bd = best_spread[0], best_spread[1]
        spread_active = False
        spread_status = "near_miss"
        spread_explanation = "Best candidate met min sample but did not meet min ROI, min win rate, or beat baseline."
    elif spread_any:
        best_spread = max(spread_any, key=lambda x: (roi_winrate(x[1])[0] or -1, roi_winrate(x[1])[1] or 0, x[1]["games"]))
        spread_config, spread_bd = best_spread[0], best_spread[1]
        spread_active = False
        spread_status = "inactive"
        spread_explanation = "Best candidate below min sample; not used for sizing."
    else:
        spread_config, spread_bd = None, baseline_spread
        spread_active = False
        spread_status = "inactive"
        spread_explanation = "No candidate with Spread Sweet Spot; fixed baseline shown for visibility."

    # Total Sweet Spot: always publish best candidate or baseline; guardrails set status only
    total_candidates = [
        (cfg, st) for cfg, st in candidates_by_config if st.get("Total Sweet Spot") and st["Total Sweet Spot"]["games"] >= MIN_SAMPLE_TOTAL_SWEET
    ]
    total_sel = [
        (cfg, st["Total Sweet Spot"])
        for cfg, st in total_candidates
        if roi_winrate(st["Total Sweet Spot"])[0] is not None
        and roi_winrate(st["Total Sweet Spot"])[0] >= MIN_ROI
        and roi_winrate(st["Total Sweet Spot"])[1] >= MIN_WIN_RATE
        and _beats_baseline(
            roi_winrate(st["Total Sweet Spot"])[0],
            st["Total Sweet Spot"]["games"],
            baseline_total_roi,
            baseline_total_n,
        )
    ]
    total_any = [(cfg, st["Total Sweet Spot"]) for cfg, st in candidates_by_config if st.get("Total Sweet Spot") and st["Total Sweet Spot"]["games"] >= 1]
    if total_sel:
        best_total = max(total_sel, key=lambda x: (roi_winrate(x[1])[0], roi_winrate(x[1])[1], x[1]["games"]))
        total_config, total_bd = best_total[0], best_total[1]
        total_active = True
        total_status = "active"
        total_explanation = f"Guardrails met; beats baseline (ROI {roi_winrate(total_bd)[0]:.4f}, n={total_bd['games']})."
    elif total_candidates:
        best_total = max(
            [(cfg, st["Total Sweet Spot"]) for cfg, st in total_candidates],
            key=lambda x: (roi_winrate(x[1])[0] or -1, roi_winrate(x[1])[1] or 0, x[1]["games"]),
        )
        total_config, total_bd = best_total[0], best_total[1]
        total_active = False
        total_status = "near_miss"
        total_explanation = "Best candidate met min sample but did not meet min ROI, min win rate, or beat baseline."
    elif total_any:
        best_total = max(total_any, key=lambda x: (roi_winrate(x[1])[0] or -1, roi_winrate(x[1])[1] or 0, x[1]["games"]))
        total_config, total_bd = best_total[0], best_total[1]
        total_active = False
        total_status = "inactive"
        total_explanation = "Best candidate below min sample; not used for sizing."
    else:
        total_config, total_bd = None, baseline_total
        total_active = False
        total_status = "inactive"
        total_explanation = "No candidate with Total Sweet Spot; fixed baseline shown for visibility."

    # Dual Sweet Spot: always publish best candidate or baseline; guardrails set status only
    dual_candidates = [
        (cfg, st) for cfg, st in candidates_by_config if st.get("Dual Sweet Spot") and st["Dual Sweet Spot"]["games"] >= MIN_SAMPLE_DUAL_SWEET
    ]
    dual_sel = [
        (cfg, st["Dual Sweet Spot"])
        for cfg, st in dual_candidates
        if roi_winrate(st["Dual Sweet Spot"])[0] is not None
        and roi_winrate(st["Dual Sweet Spot"])[0] >= MIN_ROI
        and roi_winrate(st["Dual Sweet Spot"])[1] >= MIN_WIN_RATE
        and _beats_baseline(
            roi_winrate(st["Dual Sweet Spot"])[0],
            st["Dual Sweet Spot"]["games"],
            baseline_dual_roi,
            baseline_dual_n,
        )
    ]
    dual_any = [(cfg, st["Dual Sweet Spot"]) for cfg, st in candidates_by_config if st.get("Dual Sweet Spot") and st["Dual Sweet Spot"]["games"] >= 1]
    if dual_sel:
        best_dual = max(dual_sel, key=lambda x: (roi_winrate(x[1])[0], roi_winrate(x[1])[1], x[1]["games"]))
        dual_config, dual_bd = best_dual[0], best_dual[1]
        dual_active = True
        dual_status = "active"
        dual_explanation = f"Guardrails met; beats baseline (ROI {roi_winrate(dual_bd)[0]:.4f}, n={dual_bd['games']})."
    elif dual_candidates:
        best_dual = max(
            [(cfg, st["Dual Sweet Spot"]) for cfg, st in dual_candidates],
            key=lambda x: (roi_winrate(x[1])[0] or -1, roi_winrate(x[1])[1] or 0, x[1]["games"]),
        )
        dual_config, dual_bd = best_dual[0], best_dual[1]
        dual_active = False
        dual_status = "near_miss"
        dual_explanation = "Best candidate met min sample but did not meet min ROI, min win rate, or beat baseline."
    elif dual_any:
        best_dual = max(dual_any, key=lambda x: (roi_winrate(x[1])[0] or -1, roi_winrate(x[1])[1] or 0, x[1]["games"]))
        dual_config, dual_bd = best_dual[0], best_dual[1]
        dual_active = False
        dual_status = "inactive"
        dual_explanation = "Best candidate below min sample; not used for sizing."
    else:
        dual_config, dual_bd = None, baseline_dual
        dual_active = False
        dual_status = "inactive"
        dual_explanation = "No candidate with Dual Sweet Spot; fixed baseline shown for visibility."

    # Avoid: v1 fixed only; report baseline; always published with status active
    avoid_active = True
    avoid_status = "active"
    avoid_explanation = "Fixed baseline in v1; avoid thresholds not optimized."

    # Build artifact
    def _metrics(bd):
        if not bd or bd["games"] == 0:
            return None, None, 0
        return round(bd["profit"] / bd["games"], 4), round(bd["wins"] / bd["games"], 4), bd["games"]

    def _baseline_metrics(bd):
        if not bd or bd["games"] == 0:
            return {"roi": None, "win_rate": None, "sample_size": 0}
        return {"roi": round(bd["profit"] / bd["games"], 4), "win_rate": round(bd["wins"] / bd["games"], 4), "sample_size": bd["games"]}

    t_lo, t_hi = grid_config["baseline_total_window"]
    payload = {
        "league": league,
        "source_backtest_dir": latest_dir.name,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "chosen_thresholds": {
            "spread_sweet_spot": {
                "edge_min": spread_config[0][0] if spread_config else 1,
                "edge_max": spread_config[0][1] if spread_config else 4,
                "spread_line_max_exclusive": spread_config[2] if spread_config else 12,
            },
            "total_sweet_spot": {
                "edge_min": total_config[1][0] if total_config else 1,
                "edge_max": total_config[1][1] if total_config else 4,
                "total_min": total_config[3][0] if total_config else t_lo,
                "total_max": total_config[3][1] if total_config else t_hi,
                "spread_line_max_exclusive": total_config[2] if total_config else 12,
            },
            "dual_sweet_spot": {
                "spread_edge_min": dual_config[0][0] if dual_config else 1,
                "spread_edge_max": dual_config[0][1] if dual_config else 4,
                "total_edge_min": dual_config[1][0] if dual_config else 1,
                "total_edge_max": dual_config[1][1] if dual_config else 4,
                "total_min": dual_config[3][0] if dual_config else t_lo,
                "total_max": dual_config[3][1] if dual_config else t_hi,
                "spread_line_max_exclusive": 10,
            },
            "avoid": {
                "spread_edge_above": FIXED_SPREAD_AVOID_EDGE,
                "spread_line_at_or_above": FIXED_SPREAD_AVOID_LINE,
                "total_edge_above": FIXED_TOTAL_AVOID_EDGE,
                "total_below": FIXED_TOTAL_AVOID_TOTAL_BELOW,
            },
        },
        "buckets": {
            "spread_sweet_spot": {
                "active": spread_active,
                "status": spread_status,
                "roi": _metrics(spread_bd)[0] if spread_bd else None,
                "win_rate": _metrics(spread_bd)[1] if spread_bd else None,
                "sample_size": _metrics(spread_bd)[2] if spread_bd else 0,
                "explanation": spread_explanation,
            },
            "total_sweet_spot": {
                "active": total_active,
                "status": total_status,
                "roi": _metrics(total_bd)[0] if total_bd else None,
                "win_rate": _metrics(total_bd)[1] if total_bd else None,
                "sample_size": _metrics(total_bd)[2] if total_bd else 0,
                "explanation": total_explanation,
            },
            "dual_sweet_spot": {
                "active": dual_active,
                "status": dual_status,
                "roi": _metrics(dual_bd)[0] if dual_bd else None,
                "win_rate": _metrics(dual_bd)[1] if dual_bd else None,
                "sample_size": _metrics(dual_bd)[2] if dual_bd else 0,
                "explanation": dual_explanation,
            },
            "avoid": {
                "active": avoid_active,
                "status": avoid_status,
                "roi": _metrics(baseline_avoid)[0] if baseline_avoid else None,
                "win_rate": _metrics(baseline_avoid)[1] if baseline_avoid else None,
                "sample_size": _metrics(baseline_avoid)[2] if baseline_avoid else 0,
                "explanation": avoid_explanation,
            },
        },
        "baseline_fixed_comparison": {
            "spread_sweet_spot": _baseline_metrics(baseline_spread),
            "total_sweet_spot": _baseline_metrics(baseline_total),
            "dual_sweet_spot": _baseline_metrics(baseline_dual),
            "avoid": _baseline_metrics(baseline_avoid),
        },
    }

    out_path = latest_dir / "dynamic_sweetspot_thresholds.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Wrote: {out_path}")
    print(f"  league={league} source={latest_dir.name}")
    print(f"  spread_sweet_spot: active={spread_active}  total_sweet_spot: active={total_active}  dual_sweet_spot: active={dual_active}")


if __name__ == "__main__":
    main()
