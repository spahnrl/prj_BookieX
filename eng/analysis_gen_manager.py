"""
eng/analysis_gen_manager.py

Unified analysis intelligence: bias detection and edge calibration for NBA and NCAAM.
Ports logic from eng/analysis/analysis_003_bias_detection.py and analysis_018_spread_edge_strength_curve.py.

- Bias detection: Home Team Bias, Favorite Bias, Over vs Under (league-agnostic).
- Edge calibration: Win Probability Curve mapping |edge| buckets to actual Win Rate.
- Sweet Spots: scenarios where Win Rate > 55% and Edge > 5.0.
- Output: bias_report_{league}.json (e.g. bias_report_ncaam.json).

Authority: eng/backtest_gen_runner.py, eng/analysis/analysis_003_bias_detection.py,
          eng/analysis/analysis_018_spread_edge_strength_curve.py, utils/mapping_helpers.py.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.io_helpers import get_backtest_output_root

# Edge buckets for Win Probability Curve (min edge in bucket)
EDGE_BUCKETS = [0.0, 2.5, 5.0, 7.5, 10.0, 15.0, 25.0]
SWEET_SPOT_WIN_RATE_MIN = 0.55
SWEET_SPOT_EDGE_MIN = 5.0


def _get_latest_backtest_path(league: str) -> Path | None:
    backtest_root = get_backtest_output_root(league)
    if not backtest_root.exists():
        return None
    dirs = [d for d in backtest_root.iterdir() if d.is_dir() and d.name.startswith(f"backtest_{league}_")]
    if not dirs:
        dirs = [d for d in backtest_root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
    if not dirs:
        return None
    dirs.sort(key=lambda p: p.name, reverse=True)
    for d in dirs:
        p = d / "backtest_games.json"
        if p.exists():
            return p
    return None


def load_backtest_games(league: str, path: Path | None = None) -> list[dict]:
    if path is None:
        path = _get_latest_backtest_path(league)
    if path is None or not path.exists():
        raise FileNotFoundError(f"No backtest file found for league={league}. Run backtest_gen_runner first.")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _safe_float(x) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _pick_result(g: dict, result_key: str) -> str:
    """Get spread_result or total_result from authority model or top-level."""
    auth = (g.get("model_results") or {}).get(g.get("selection_authority") or "") or {}
    if result_key == "spread_result":
        res = auth.get("spread_result") or g.get("selected_spread_result") or g.get("spread_result")
    else:
        res = auth.get("total_result") or g.get("selected_total_result") or g.get("total_result")
    return (res or "").strip()


def _pick_edge(g: dict, edge_key: str) -> float | None:
    auth = (g.get("model_results") or {}).get(g.get("selection_authority") or "") or {}
    if edge_key == "spread_edge":
        e = auth.get("spread_edge") or g.get("spread_edge") or g.get("selected_spread_edge")
    else:
        e = auth.get("total_edge") or g.get("total_edge") or g.get("selected_total_edge")
    return _safe_float(e)


def _spread_pick(g: dict) -> str:
    auth = (g.get("model_results") or {}).get(g.get("selection_authority") or {}) or {}
    return (auth.get("spread_pick") or g.get("Line Bet") or g.get("selected_spread_pick") or "").strip()


def _total_pick(g: dict) -> str:
    auth = (g.get("model_results") or {}).get(g.get("selection_authority") or {}) or {}
    return (auth.get("total_pick") or g.get("Total Bet") or g.get("selected_total_pick") or "").strip()


def _market_spread_home(g: dict) -> float | None:
    return _safe_float(g.get("market_spread_home") or g.get("spread_home") or g.get("line_spread"))


def _is_bet_on_home(g: dict) -> bool | None:
    """True if spread pick is home team, False if away, None if unknown."""
    pick = _spread_pick(g)
    if not pick:
        return None
    pick_upper = pick.upper()
    if pick_upper in ("HOME", "AWAY"):
        return pick_upper == "HOME"
    home = (g.get("home_team_display") or g.get("home_team") or "").strip().upper()
    away = (g.get("away_team_display") or g.get("away_team") or "").strip().upper()
    if not home or not away:
        return None
    return pick_upper == home


def _is_home_favorite(g: dict) -> bool | None:
    spread = _market_spread_home(g)
    if spread is None:
        return None
    return spread < 0


def run_bias_detection(games: list[dict], league: str) -> dict:
    """
    Bias detection: Over vs Under, Favorites vs Dogs, Home vs Away,
    and (for any league) Home Favorite / Home Dog / Away Favorite / Away Dog.
    """
    over_wins, over_count = [], 0
    under_wins, under_count = [], 0
    fav_wins, fav_count = [], 0
    dog_wins, dog_count = [], 0
    home_pick_wins, home_pick_count = [], 0
    away_pick_wins, away_pick_count = [], 0
    home_fav_wins, home_fav_count = [], 0
    home_dog_wins, home_dog_count = [], 0
    away_fav_wins, away_fav_count = [], 0
    away_dog_wins, away_dog_count = [], 0

    for g in games:
        total_pick = _total_pick(g)
        total_result = _pick_result(g, "total_result")
        if total_pick and total_result:
            win = total_result == "WIN"
            if total_pick.upper() == "OVER":
                over_wins.append(win)
                over_count += 1
            elif total_pick.upper() == "UNDER":
                under_wins.append(win)
                under_count += 1

        spread_result = _pick_result(g, "spread_result")
        if not spread_result:
            continue
        win = spread_result == "WIN"
        spread_home = _market_spread_home(g)
        bet_on_home = _is_bet_on_home(g)
        home_is_fav = _is_home_favorite(g)

        if spread_home is not None and bet_on_home is not None:
            is_favorite_pick = (home_is_fav and bet_on_home) or (not home_is_fav and not bet_on_home)
            if is_favorite_pick:
                fav_wins.append(win)
                fav_count += 1
            else:
                dog_wins.append(win)
                dog_count += 1

        if bet_on_home is not None:
            if bet_on_home:
                home_pick_wins.append(win)
                home_pick_count += 1
            else:
                away_pick_wins.append(win)
                away_pick_count += 1

        if spread_home is not None and bet_on_home is not None and home_is_fav is not None:
            if home_is_fav and bet_on_home:
                home_fav_wins.append(win)
                home_fav_count += 1
            elif not home_is_fav and bet_on_home:
                home_dog_wins.append(win)
                home_dog_count += 1
            elif home_is_fav and not bet_on_home:
                away_fav_wins.append(win)
                away_fav_count += 1
            else:
                away_dog_wins.append(win)
                away_dog_count += 1

    def wr(wins: list, count: int) -> float | None:
        if not count:
            return None
        return round(sum(wins) / count, 4)

    return {
        "over_under": {
            "over_win_rate": wr(over_wins, over_count),
            "over_count": over_count,
            "under_win_rate": wr(under_wins, under_count),
            "under_count": under_count,
        },
        "favorite_vs_dog": {
            "favorite_win_rate": wr(fav_wins, fav_count),
            "favorite_count": fav_count,
            "dog_win_rate": wr(dog_wins, dog_count),
            "dog_count": dog_count,
        },
        "home_vs_away_pick": {
            "home_pick_win_rate": wr(home_pick_wins, home_pick_count),
            "home_pick_count": home_pick_count,
            "away_pick_win_rate": wr(away_pick_wins, away_pick_count),
            "away_pick_count": away_pick_count,
        },
        "home_favorite": {"win_rate": wr(home_fav_wins, home_fav_count), "count": home_fav_count},
        "home_dog": {"win_rate": wr(home_dog_wins, home_dog_count), "count": home_dog_count},
        "away_favorite": {"win_rate": wr(away_fav_wins, away_fav_count), "count": away_fav_count},
        "away_dog": {"win_rate": wr(away_dog_wins, away_dog_count), "count": away_dog_count},
    }


def run_edge_calibration(games: list[dict], edge_key: str, result_key: str) -> list[dict]:
    """
    Win Probability Curve: bucket games by |edge| and compute win rate per bucket.
    Returns list of { "edge_min", "edge_max", "avg_edge", "win_rate", "count", "wins" }.
    """
    eligible = []
    for g in games:
        edge = _pick_edge(g, edge_key)
        res = _pick_result(g, result_key)
        if edge is None or res not in ("WIN", "LOSS", "PUSH"):
            continue
        eligible.append({"edge": abs(edge), "win": 1 if res == "WIN" else 0})
    if not eligible:
        return []
    eligible.sort(key=lambda x: x["edge"])
    n = len(eligible)
    curve = []
    for i in range(len(EDGE_BUCKETS) - 1):
        lo, hi = EDGE_BUCKETS[i], EDGE_BUCKETS[i + 1]
        bucket = [x for x in eligible if lo <= x["edge"] < hi]
        if not bucket:
            curve.append({"edge_min": lo, "edge_max": hi, "avg_edge": None, "win_rate": None, "count": 0, "wins": 0})
            continue
        wins = sum(x["win"] for x in bucket)
        avg_edge = sum(x["edge"] for x in bucket) / len(bucket)
        curve.append({
            "edge_min": lo,
            "edge_max": hi,
            "avg_edge": round(avg_edge, 3),
            "win_rate": round(wins / len(bucket), 4),
            "count": len(bucket),
            "wins": wins,
        })
    # catch-all bucket for edge >= last
    last = EDGE_BUCKETS[-1]
    bucket = [x for x in eligible if x["edge"] >= last]
    if bucket:
        wins = sum(x["win"] for x in bucket)
        avg_edge = sum(x["edge"] for x in bucket) / len(bucket)
        curve.append({
            "edge_min": last,
            "edge_max": None,
            "avg_edge": round(avg_edge, 3),
            "win_rate": round(wins / len(bucket), 4),
            "count": len(bucket),
            "wins": wins,
        })
    return curve


def identify_sweet_spots(
    bias: dict,
    edge_curve_spread: list[dict],
    edge_curve_total: list[dict],
) -> list[dict]:
    """
    Sweet Spots: scenarios where Win Rate > 55% and (bucket) edge > 5.0.
    """
    sweet = []
    for bucket in edge_curve_spread:
        if bucket.get("count", 0) < 5:
            continue
        wr = bucket.get("win_rate")
        edge_lo = bucket.get("edge_min")
        if wr is not None and edge_lo is not None and wr >= SWEET_SPOT_WIN_RATE_MIN and edge_lo >= SWEET_SPOT_EDGE_MIN:
            sweet.append({
                "scenario": f"spread_edge_{bucket['edge_min']}_{bucket['edge_max'] or 'inf'}",
                "type": "spread_edge_bucket",
                "win_rate": wr,
                "min_edge": edge_lo,
                "count": bucket["count"],
                "wins": bucket["wins"],
            })
    for bucket in edge_curve_total:
        if bucket.get("count", 0) < 5:
            continue
        wr = bucket.get("win_rate")
        edge_lo = bucket.get("edge_min")
        if wr is not None and edge_lo is not None and wr >= SWEET_SPOT_WIN_RATE_MIN and edge_lo >= SWEET_SPOT_EDGE_MIN:
            sweet.append({
                "scenario": f"total_edge_{bucket['edge_min']}_{bucket['edge_max'] or 'inf'}",
                "type": "total_edge_bucket",
                "win_rate": wr,
                "min_edge": edge_lo,
                "count": bucket["count"],
                "wins": bucket["wins"],
            })
    # Bias-based sweet spots (win rate > 55%, count >= 10; edge N/A for bias segments)
    bias_checks = [
        ("home_dog", "home_dog", "win_rate", "count"),
        ("home_favorite", "home_favorite", "win_rate", "count"),
        ("away_dog", "away_dog", "win_rate", "count"),
        ("away_favorite", "away_favorite", "win_rate", "count"),
        ("favorite_pick", "favorite_vs_dog", "favorite_win_rate", "favorite_count"),
        ("dog_pick", "favorite_vs_dog", "dog_win_rate", "dog_count"),
        ("home_pick", "home_vs_away_pick", "home_pick_win_rate", "home_pick_count"),
        ("away_pick", "home_vs_away_pick", "away_pick_win_rate", "away_pick_count"),
    ]
    for scenario, key, rate_key, count_key in bias_checks:
        blk = bias.get(key)
        if not isinstance(blk, dict):
            continue
        wr = blk.get(rate_key)
        cnt = blk.get(count_key, 0)
        if wr is not None and cnt >= 10 and wr >= SWEET_SPOT_WIN_RATE_MIN:
            sweet.append({
                "scenario": scenario,
                "type": "bias",
                "win_rate": wr,
                "min_edge": None,
                "count": cnt,
                "wins": int(round(wr * cnt)),
            })
    return sweet


def run_analysis(league: str, backtest_path: Path | None = None) -> dict:
    """Run full analysis: load backtest games, bias detection, edge curves, sweet spots. Return report dict."""
    games = load_backtest_games(league, backtest_path)
    bias = run_bias_detection(games, league)
    edge_curve_spread = run_edge_calibration(games, "spread_edge", "spread_result")
    edge_curve_total = run_edge_calibration(games, "total_edge", "total_result")
    sweet_spots = identify_sweet_spots(bias, edge_curve_spread, edge_curve_total)
    return {
        "league": league,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "graded_game_count": len(games),
        "bias": bias,
        "edge_curve_spread": edge_curve_spread,
        "edge_curve_total": edge_curve_total,
        "sweet_spots": sweet_spots,
        "sweet_spot_def": {"win_rate_min": SWEET_SPOT_WIN_RATE_MIN, "edge_min": SWEET_SPOT_EDGE_MIN},
    }


def write_bias_report(league: str, report: dict, out_path: Path | None = None) -> Path:
    if out_path is None:
        reports_dir = PROJECT_ROOT / "data" / league / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        out_path = reports_dir / f"bias_report_{league}.json"
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return out_path


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Unified analysis: bias detection + edge calibration + sweet spots")
    p.add_argument("--league", choices=["nba", "ncaam"], required=True)
    p.add_argument("--output", default=None, help="Output JSON path (default: data/{league}/reports/bias_report_{league}.json)")
    args = p.parse_args()
    league = args.league.strip().lower()
    report = run_analysis(league)
    out = write_bias_report(league, report, Path(args.output) if args.output else None)
    print(f"Bias report written: {out}")
    print(f"  Graded games: {report['graded_game_count']}")
    print(f"  Sweet spots: {len(report['sweet_spots'])}")
    for s in report["sweet_spots"][:15]:
        print(f"    - {s['scenario']}: win_rate={s['win_rate']}, count={s['count']}")


if __name__ == "__main__":
    main()
