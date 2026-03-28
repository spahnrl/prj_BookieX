"""
build_ncaam_pocket_leaderboard_validation.py — NCAAM only.

Writes ncaam_pocket_leaderboard_validation.json into a given backtest directory.
Uses the same backtest_games.json plus pocket artifacts from that run (no retuning).

Forward-only: reads prior artifacts; writes one new JSON.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eng.execution.build_execution_overlay import determine_band
from utils.io_helpers import get_backtest_output_root

LEAGUE = "ncaam"
EXCLUDED_MODELS: frozenset[str] = frozenset()
PAYOUT_MULTIPLIER = 100 / 110
MIN_SAMPLE_NOTE = 30


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _safe_float(v: Any) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _result_leg(res: Any) -> Optional[str]:
    if res is None:
        return None
    s = str(res).strip().upper()
    if s in ("WIN", "LOSS", "PUSH"):
        return s
    return None


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


def _cluster_alignment_score(align: dict) -> float:
    if not isinstance(align, dict):
        return 0.0
    h = int(align.get("hot") or 0)
    w = int(align.get("warm") or 0)
    c = int(align.get("cold") or 0)
    ins = int(align.get("insufficient") or 0)
    return 3.0 * h + 1.0 * w - 0.5 * c - 0.25 * ins


def _warning_score_spread(spa: dict) -> float:
    if not isinstance(spa, dict):
        return 0.0
    return (
        5 * int(spa.get("cold") or 0)
        + 2 * int(spa.get("insufficient") or 0)
        - 3 * int(spa.get("hot") or 0)
        - int(spa.get("warm") or 0)
    )


def _combo_leaderboard_score(combo: dict | None) -> Optional[float]:
    if not combo or not isinstance(combo, dict):
        return None
    roi = combo.get("roi")
    graded = int(combo.get("graded_games") or 0)
    cst = str(combo.get("state") or "insufficient").lower()
    sw = {"hot": 400, "warm": 150, "cold": 0, "insufficient": 0}.get(cst, 0)
    rv = float(roi) if roi is not None else -1.0
    return 10000.0 * rv + 3 * graded + sw


def _state_lookup_from_pockets(pockets: list[dict]) -> dict[tuple[str, str, str], str]:
    lu: dict[tuple[str, str, str], str] = {}
    for r in pockets:
        if not isinstance(r, dict):
            continue
        lu[(r["model"], r["market_type"], r["edge_bucket"])] = r.get("state") or "insufficient"
    return lu


def _combo_by_key_from_rows(combo_rows: list[dict]) -> dict[tuple[str, str, str], dict]:
    out: dict[tuple[str, str, str], dict] = {}
    for r in combo_rows:
        if not isinstance(r, dict):
            continue
        k = (r.get("market_type"), r.get("models_key"), r.get("state_signature"))
        if all(x is not None for x in k):
            out[k] = r
    return out


def _best_combo(
    per_model: dict,
    market: str,
    size: int,
    combo_by_key: dict[tuple[str, str, str], dict],
) -> Optional[dict]:
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


def _slate_row_from_game(
    game: dict,
    state_lookup: dict[tuple[str, str, str], str],
    combo_by_key: dict[tuple[str, str, str], dict],
) -> Optional[dict]:
    models_blob = game.get("models") or {}
    if not isinstance(models_blob, dict) or not models_blob:
        return None
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

    gid = str(
        game.get("canonical_game_id") or game.get("game_id") or game.get("espn_game_id") or ""
    ).strip()

    return {
        "game_id": gid,
        "spread_pocket_alignment": spread_summary,
        "total_pocket_alignment": total_summary,
        "best_pair_spread": _best_combo(per_model, "spread", 2, combo_by_key),
        "best_triple_spread": _best_combo(per_model, "spread", 3, combo_by_key),
        "best_pair_total": _best_combo(per_model, "total", 2, combo_by_key),
        "best_triple_total": _best_combo(per_model, "total", 3, combo_by_key),
    }


def _pair_combo_outcome(game: dict, models_key: str, market: str) -> Optional[str]:
    parts = models_key.split("|")
    if len(parts) != 2:
        return None
    mr = game.get("model_results") or {}
    rk = "spread_result" if market == "spread" else "total_result"
    r1 = _result_leg((mr.get(parts[0]) or {}).get(rk))
    r2 = _result_leg((mr.get(parts[1]) or {}).get(rk))
    if market == "spread":
        return _combo_outcome_two(r1, r2)
    return _combo_outcome_two(r1, r2)


def _triple_combo_outcome(game: dict, models_key: str, market: str) -> Optional[str]:
    parts = models_key.split("|")
    if len(parts) != 3:
        return None
    mr = game.get("model_results") or {}
    rk = "spread_result" if market == "spread" else "total_result"
    r1 = _result_leg((mr.get(parts[0]) or {}).get(rk))
    r2 = _result_leg((mr.get(parts[1]) or {}).get(rk))
    r3 = _result_leg((mr.get(parts[2]) or {}).get(rk))
    return _combo_outcome_three(r1, r2, r3)


def _summarize_results(results: list[Optional[str]]) -> dict[str, Any]:
    wins = losses = pushes = 0
    profit = 0.0
    for res in results:
        if res is None:
            continue
        if res == "WIN":
            wins += 1
            profit += PAYOUT_MULTIPLIER
        elif res == "LOSS":
            losses += 1
            profit -= 1.0
        elif res == "PUSH":
            pushes += 1
    graded = wins + losses + pushes
    notes = []
    if graded < MIN_SAMPLE_NOTE:
        notes.append(f"graded_games={graded} < {MIN_SAMPLE_NOTE} (interpret cautiously)")
    return {
        "games": graded,
        "graded_games": graded,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": round(wins / graded, 4) if graded else None,
        "roi": round(profit / graded, 4) if graded else None,
        "sample_notes": "; ".join(notes) if notes else "ok",
    }


def _tercile_top_indices(scores: list[tuple[int, float]]) -> set[int]:
    """scores: (index, score) for valid rows; return indices in top tercile by score."""
    if not scores:
        return set()
    sorted_idx = [i for i, _ in sorted(scores, key=lambda x: -x[1])]
    n = len(sorted_idx)
    k = max(1, n // 3)
    return set(sorted_idx[:k])


def _tercile_bottom_indices(scores: list[tuple[int, float]]) -> set[int]:
    if not scores:
        return set()
    sorted_idx = [i for i, _ in sorted(scores, key=lambda x: x[1])]
    n = len(sorted_idx)
    k = max(1, n // 3)
    return set(sorted_idx[:k])


def write_ncaam_pocket_leaderboard_validation(latest_dir: Path) -> Path | None:
    """
    Build validation JSON from backtest_games + ncaam_model_pockets + ncaam_model_combo_pockets.
    Returns path written, or None if skipped.
    """
    pockets_path = latest_dir / "ncaam_model_pockets.json"
    combo_path = latest_dir / "ncaam_model_combo_pockets.json"
    games_path = latest_dir / "backtest_games.json"
    if not pockets_path.exists() or not combo_path.exists() or not games_path.exists():
        return None

    pockets_doc = _load_json(pockets_path)
    combo_doc = _load_json(combo_path)
    games: list[dict] = _load_json(games_path)
    if not isinstance(games, list):
        return None

    pockets = pockets_doc.get("pockets") or []
    combo_rows = combo_doc.get("combo_pockets") or []
    state_lookup = _state_lookup_from_pockets(pockets)
    combo_by_key = _combo_by_key_from_rows(combo_rows)

    enriched: list[dict] = []
    for idx, game in enumerate(games):
        if not isinstance(game, dict):
            continue
        sr = _slate_row_from_game(game, state_lookup, combo_by_key)
        if sr is None:
            continue
        auth_sp = _result_leg(game.get("selected_spread_result"))
        auth_tot = _result_leg(game.get("selected_total_result"))
        spa = sr["spread_pocket_alignment"]
        tpa = sr["total_pocket_alignment"]
        cs = _cluster_alignment_score(spa)
        ws = _warning_score_spread(spa)
        bps = sr.get("best_pair_spread")
        bps_roi = bps.get("roi") if isinstance(bps, dict) else None
        pass_cand = cs <= 0.0 and (bps_roi is None or float(bps_roi) < 0)

        pss = _combo_leaderboard_score(bps) if bps else None
        pts = _combo_leaderboard_score(sr.get("best_triple_spread")) if sr.get("best_triple_spread") else None
        ptp = _combo_leaderboard_score(sr.get("best_pair_total")) if sr.get("best_pair_total") else None
        ptt = _combo_leaderboard_score(sr.get("best_triple_total")) if sr.get("best_triple_total") else None

        pair_sp_out = None
        if isinstance(bps, dict) and bps.get("models_key"):
            pair_sp_out = _pair_combo_outcome(game, bps["models_key"], "spread")
        trip_sp_out = None
        bts = sr.get("best_triple_spread")
        if isinstance(bts, dict) and bts.get("models_key"):
            trip_sp_out = _triple_combo_outcome(game, bts["models_key"], "spread")

        pair_tot_out = None
        bpt = sr.get("best_pair_total")
        if isinstance(bpt, dict) and bpt.get("models_key"):
            pair_tot_out = _pair_combo_outcome(game, bpt["models_key"], "total")
        trip_tot_out = None
        btt = sr.get("best_triple_total")
        if isinstance(btt, dict) and btt.get("models_key"):
            trip_tot_out = _triple_combo_outcome(game, btt["models_key"], "total")

        enriched.append(
            {
                "_idx": idx,
                "game_id": sr["game_id"],
                "auth_spread": auth_sp,
                "auth_total": auth_tot,
                "pair_spread_combo": pair_sp_out,
                "triple_spread_combo": trip_sp_out,
                "pair_total_combo": pair_tot_out,
                "triple_total_combo": trip_tot_out,
                "pair_spread_score": pss,
                "triple_spread_score": pts,
                "pair_total_score": ptp,
                "triple_total_score": ptt,
                "spread_cluster_score": cs,
                "spread_warning_score": ws,
                "pass_candidate": pass_cand,
                "has_pair_spread": bps is not None,
                "has_triple_spread": bts is not None,
                "has_pair_total": bpt is not None,
                "has_triple_total": btt is not None,
            }
        )

    def _section_pair_spread_top_vs_all() -> dict[str, Any]:
        with_pair = [(i, r) for i, r in enumerate(enriched) if r["has_pair_spread"] and r["pair_spread_combo"] is not None]
        scores = [(i, r["pair_spread_score"]) for i, r in with_pair if r["pair_spread_score"] is not None]
        top_idx = _tercile_top_indices(scores)
        all_combo = [r["pair_spread_combo"] for _, r in with_pair]
        top_combo = [r["pair_spread_combo"] for i, r in with_pair if i in top_idx]
        auth_all = [r["auth_spread"] for _, r in with_pair if r["auth_spread"] is not None]
        auth_top = [r["auth_spread"] for i, r in with_pair if i in top_idx and r["auth_spread"] is not None]
        return {
            "description": "Top tercile by live leaderboard combo score vs all games with matched pair-spread pocket; outcomes are model pair combo legs.",
            "top_tercile_pair_spread_combo": _summarize_results(top_combo),
            "all_with_pair_spread_combo": _summarize_results(all_combo),
            "authority_spread_among_pair_games": _summarize_results(auth_all),
            "authority_spread_top_pair_tercile": _summarize_results(auth_top),
            "n_games_with_pair_spread_pocket": len(with_pair),
            "n_in_top_tercile": len(top_idx),
        }

    def _section_triple_spread_top_vs_all() -> dict[str, Any]:
        with_trip = [(i, r) for i, r in enumerate(enriched) if r["has_triple_spread"] and r["triple_spread_combo"] is not None]
        scores = [(i, r["triple_spread_score"]) for i, r in with_trip if r["triple_spread_score"] is not None]
        top_idx = _tercile_top_indices(scores)
        all_combo = [r["triple_spread_combo"] for _, r in with_trip]
        top_combo = [r["triple_spread_combo"] for i, r in with_trip if i in top_idx]
        auth_all = [r["auth_spread"] for _, r in with_trip if r["auth_spread"] is not None]
        auth_top = [r["auth_spread"] for i, r in with_trip if i in top_idx and r["auth_spread"] is not None]
        return {
            "description": "Top tercile by triple spread combo leaderboard score vs all with matched triple-spread pocket.",
            "top_tercile_triple_spread_combo": _summarize_results(top_combo),
            "all_with_triple_spread_combo": _summarize_results(all_combo),
            "authority_spread_among_triple_games": _summarize_results(auth_all),
            "authority_spread_top_triple_tercile": _summarize_results(auth_top),
            "n_games_with_triple_spread_pocket": len(with_trip),
            "n_in_top_tercile": len(top_idx),
        }

    def _section_cluster_strong_vs_weak() -> dict[str, Any]:
        scores = [(i, r["spread_cluster_score"]) for i, r in enumerate(enriched)]
        top_idx = _tercile_top_indices(scores)
        bot_idx = _tercile_bottom_indices(scores)
        auth_all = [r["auth_spread"] for r in enriched if r["auth_spread"] is not None]
        auth_strong = [r["auth_spread"] for i, r in enumerate(enriched) if i in top_idx and r["auth_spread"] is not None]
        auth_weak = [r["auth_spread"] for i, r in enumerate(enriched) if i in bot_idx and r["auth_spread"] is not None]
        return {
            "description": "Strong = top tercile spread_pocket_alignment cluster_score; weak = bottom tercile. Outcomes: authority spread.",
            "strong_spread_cluster_authority_spread": _summarize_results(auth_strong),
            "weak_spread_cluster_authority_spread": _summarize_results(auth_weak),
            "all_games_authority_spread": _summarize_results(auth_all),
            "n_games": len(enriched),
        }

    def _section_pass_vs_nonpass() -> dict[str, Any]:
        pass_r = [r for r in enriched if r["pass_candidate"]]
        non = [r for r in enriched if not r["pass_candidate"]]
        return {
            "description": "Pass rule matches leaderboard: spread cluster_score<=0 and (no best_pair_spread or pair roi<0). Outcomes: authority spread.",
            "pass_candidates_authority_spread": _summarize_results([r["auth_spread"] for r in pass_r]),
            "non_pass_authority_spread": _summarize_results([r["auth_spread"] for r in non]),
            "n_pass": len(pass_r),
            "n_non_pass": len(non),
        }

    def _section_cold_warnings() -> dict[str, Any]:
        scores = [(i, r["spread_warning_score"]) for i, r in enumerate(enriched)]
        high_idx = _tercile_top_indices(scores)
        low_idx = _tercile_bottom_indices(scores)
        auth_high = [r["auth_spread"] for i, r in enumerate(enriched) if i in high_idx and r["auth_spread"] is not None]
        auth_low = [r["auth_spread"] for i, r in enumerate(enriched) if i in low_idx and r["auth_spread"] is not None]
        return {
            "description": "High warning = top tercile spread cold-warning score; low = bottom tercile. Outcomes: authority spread.",
            "high_warning_authority_spread": _summarize_results(auth_high),
            "low_warning_authority_spread": _summarize_results(auth_low),
            "n_games": len(enriched),
        }

    def _section_totals_clean() -> dict[str, Any]:
        out: dict[str, Any] = {
            "description": "Total combo legs; top tercile by leaderboard score where n>=30 on eligible games."
        }

        pt_indices = [i for i, r in enumerate(enriched) if r["has_pair_total"] and r["pair_total_combo"] is not None]
        if len(pt_indices) >= MIN_SAMPLE_NOTE:
            score_pairs = [(i, enriched[i]["pair_total_score"]) for i in pt_indices if enriched[i]["pair_total_score"] is not None]
            top_idx = _tercile_top_indices(score_pairs)
            all_c = [enriched[i]["pair_total_combo"] for i in pt_indices]
            top_c = [enriched[i]["pair_total_combo"] for i in pt_indices if i in top_idx]
            out["pair_total_top_tercile_combo"] = _summarize_results(top_c)
            out["pair_total_all_with_pocket_combo"] = _summarize_results(all_c)
        else:
            out["pair_total"] = {"skipped": True, "n": len(pt_indices), "sample_notes": f"n < {MIN_SAMPLE_NOTE}"}

        tt_indices = [i for i, r in enumerate(enriched) if r["has_triple_total"] and r["triple_total_combo"] is not None]
        if len(tt_indices) >= MIN_SAMPLE_NOTE:
            score_pairs = [(i, enriched[i]["triple_total_score"]) for i in tt_indices if enriched[i]["triple_total_score"] is not None]
            top_idx = _tercile_top_indices(score_pairs)
            all_c = [enriched[i]["triple_total_combo"] for i in tt_indices]
            top_c = [enriched[i]["triple_total_combo"] for i in tt_indices if i in top_idx]
            out["triple_total_top_tercile_combo"] = _summarize_results(top_c)
            out["triple_total_all_with_pocket_combo"] = _summarize_results(all_c)
        else:
            out["triple_total"] = {"skipped": True, "n": len(tt_indices), "sample_notes": f"n < {MIN_SAMPLE_NOTE}"}
        return out

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "league": LEAGUE,
        "source_backtest_dir": latest_dir.name,
        "source_inputs": {
            "backtest_games": str(games_path.as_posix()),
            "ncaam_model_pockets": str(pockets_path.as_posix()),
            "ncaam_model_combo_pockets": str(combo_path.as_posix()),
        },
        "n_backtest_rows": len(games),
        "n_games_with_models_blob": len(enriched),
        "methodology": {
            "tercile": "Top/bottom third by count (min 1 game per tail) on leaderboard combo scores or cluster/warning scores.",
            "roi": "Same -110 leg accounting as pocket layer (100/110 win, -1 loss, 0 push).",
            "authority_spread": "selected_spread_result on backtest row.",
            "combo_outcomes": "Pair/triple WIN/LOSS/PUSH from model_results legs using same rules as pocket combo aggregation.",
        },
        "pair_spread_top_vs_all": _section_pair_spread_top_vs_all(),
        "triple_spread_top_vs_all": _section_triple_spread_top_vs_all(),
        "spread_cluster_strong_vs_weak": _section_cluster_strong_vs_weak(),
        "pass_vs_non_pass": _section_pass_vs_nonpass(),
        "cold_warning_high_vs_low": _section_cold_warnings(),
        "totals_if_sufficient": _section_totals_clean(),
    }

    out_path = latest_dir / "ncaam_pocket_leaderboard_validation.json"
    _write_json(out_path, payload)
    print(f"Wrote {out_path}")
    return out_path


def main() -> None:
    try:
        root = get_backtest_output_root(LEAGUE)
        if not root.exists():
            raise FileNotFoundError(str(root))
        subdirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("backtest_")]
        if not subdirs:
            raise FileNotFoundError("No backtest_*")
        latest = max(subdirs, key=lambda d: d.stat().st_mtime)
        write_ncaam_pocket_leaderboard_validation(latest)
    except FileNotFoundError as e:
        print(f"Skipping validation: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
