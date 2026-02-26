# prj_BookieX/eng/backtest_summary.py

from collections import defaultdict
from typing import List, Dict, Any


RESULTS = ("WIN", "LOSS", "PUSH")


def _init_counter():
    return {"bets": 0, "WIN": 0, "LOSS": 0, "PUSH": 0}


def _pct(wins: int, bets: int) -> float:
    return round((wins / bets) * 100, 2) if bets else 0.0


def build_summary(games: List[Dict], skipped: List[Dict]) -> Dict[str, Any]:
    """
    Aggregates backtest results. Read-only over graded rows.
    """
    summary: Dict[str, Any] = {}

    # ---------- Counts ----------
    summary["counts"] = {
        "games_total": len(games) + len(skipped),
        "games_graded": len(games),
        "games_skipped": len(skipped),
        "skipped_reasons": _count_skipped(skipped),
    }

    # ---------- Actionability split ----------
    by_action = defaultdict(list)
    for g in games:
        by_action[g.get("actionability")].append(g)

    summary["by_actionability"] = {
        k: _aggregate_group(v)
        for k, v in by_action.items()
    }

    # ---------- Overall ----------
    summary["overall"] = _aggregate_group(games)

    # ---------- Edge sanity ----------
    summary["edge_checks"] = _edge_checks(games)

    return summary


def _count_skipped(skipped: List[Dict]) -> Dict[str, int]:
    out = defaultdict(int)
    for s in skipped:
        out[s.get("reason", "UNKNOWN")] += 1
    return dict(out)


def _aggregate_group(rows: List[Dict]) -> Dict[str, Any]:
    """
    Aggregates spread, total, and parlay performance for a group.
    """
    spread = _init_counter()
    total = _init_counter()
    parlay = _init_counter()

    spread_edges_win = []
    spread_edges_loss = []
    total_edges_win = []
    total_edges_loss = []

    for g in rows:
        # ----- Spread -----
        sr = g.get("spread_result")
        if sr in RESULTS:
            spread["bets"] += 1
            spread[sr] += 1
            edge = g.get("Spread Edge")
            if edge is not None:
                (spread_edges_win if sr == "WIN" else spread_edges_loss if sr == "LOSS" else []).append(edge)

        # ----- Total -----
        tr = g.get("total_result")
        if tr in RESULTS:
            total["bets"] += 1
            total[tr] += 1
            edge = g.get("Total Edge")
            if edge is not None:
                (total_edges_win if tr == "WIN" else total_edges_loss if tr == "LOSS" else []).append(edge)

        # ----- Parlay -----
        pr = g.get("parlay_result")
        if pr in RESULTS:
            parlay["bets"] += 1
            parlay[pr] += 1

    return {
        "spread": _finalize(spread, spread_edges_win, spread_edges_loss),
        "total": _finalize(total, total_edges_win, total_edges_loss),
        "parlay": _finalize(parlay, None, None),
    }


def _finalize(counter: Dict, edges_win, edges_loss) -> Dict[str, Any]:
    out = dict(counter)
    out["win_pct"] = _pct(counter["WIN"], counter["bets"])
    if edges_win is not None:
        out["avg_edge_win"] = round(sum(edges_win) / len(edges_win), 3) if edges_win else None
        out["avg_edge_loss"] = round(sum(edges_loss) / len(edges_loss), 3) if edges_loss else None
    return out


def _edge_checks(games: List[Dict]) -> Dict[str, Any]:
    """
    Light sanity checks: higher edges should not lose more than lower edges.
    Non-binding; informational only.
    """
    buckets = defaultdict(lambda: {"WIN": 0, "LOSS": 0, "bets": 0})

    for g in games:
        for label, edge_key, result_key in (
            ("spread", "Spread Edge", "spread_result"),
            ("total", "Total Edge", "total_result"),
        ):
            edge = g.get(edge_key)
            res = g.get(result_key)
            if edge is None or res not in ("WIN", "LOSS"):
                continue

            # simple deciles by magnitude
            decile = int(min(edge // 1, 9))  # 0–9
            key = f"{label}_edge_decile_{decile}"
            buckets[key]["bets"] += 1
            buckets[key][res] += 1

    # finalize
    out = {}
    for k, v in buckets.items():
        out[k] = {
            "bets": v["bets"],
            "win_pct": _pct(v["WIN"], v["bets"]),
        }
    return out