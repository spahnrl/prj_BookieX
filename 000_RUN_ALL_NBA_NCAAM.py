"""
000_RUN_ALL_NBA_NCAA.py

Purpose
-------
Run both the NBA and NCAAM pipelines in sequence. Single Executive Summary at end.

Design goals
------------
- One consolidated table: League | Step | Duration | Integrity
- One block: OUTPUT LOCATIONS (final_game_view.json per league)
- Odds date range + Model Pulse (active games count) in clean tables
- No redundant STARTING headers between NBA and NCAAM

Usage
-----
  python 000_RUN_ALL_NBA_NCAA.py
  python 000_RUN_ALL_NBA_NCAA.py --start-date 20260301 --end-date 20260308
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter


PROJECT_ROOT = Path(__file__).resolve().parent

NBA_RUNNER = PROJECT_ROOT / "000_RUN_ALL.py"
NCAAM_RUNNER = PROJECT_ROOT / "000_RUN_ALL_NCAAM.py"


def parse_args():
    parser = argparse.ArgumentParser(description="Run both NBA and NCAAM pipelines")
    parser.add_argument("--mode", choices=["LIVE", "LAB"], default="LIVE", help="NBA mode only")
    parser.add_argument("--analysis", action="store_true", help="NBA only")
    parser.add_argument("--analysis-only", action="store_true", help="NBA only")
    parser.add_argument("--start-date", dest="start_date", type=str, help="NCAAM schedule start YYYYMMDD")
    parser.add_argument("--end-date", dest="end_date", type=str, help="NCAAM schedule end YYYYMMDD")
    parser.add_argument("--watch", action="store_true", help="Run pipelines then start live monitor loop (Timing Agent EXECUTE alerts every 30 min)")
    return parser.parse_args()


def build_nba_command(args) -> list[str]:
    cmd = [sys.executable, str(NBA_RUNNER), "--mode", args.mode, "--quiet"]
    if args.analysis:
        cmd.append("--analysis")
    if args.analysis_only:
        cmd.append("--analysis-only")
    return cmd


def build_ncaam_command(args) -> list[str]:
    cmd = [sys.executable, str(NCAAM_RUNNER), "--quiet"]
    if (args.start_date and not args.end_date) or (args.end_date and not args.start_date):
        raise ValueError("Both --start-date and --end-date must be provided together for NCAAM.")
    if args.start_date and args.end_date:
        cmd.extend(["--start-date", args.start_date, "--end-date", args.end_date])
    return cmd


def run_step(label: str, cmd: list[str], silent: bool = False) -> float:
    if not silent:
        print("\n" + "=" * 90)
        print(f"RUNNING: {label}")
        print(f"COMMAND: {' '.join(cmd)}")
        print("=" * 90)
    start = perf_counter()
    env = os.environ.copy()
    root_str = str(PROJECT_ROOT)
    env["PYTHONPATH"] = root_str + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run(cmd, cwd=root_str, check=True, capture_output=silent, env=env)
    elapsed = perf_counter() - start
    if not silent:
        print(f"SUCCESS: {label} | {elapsed:.2f}s")
    return elapsed


def run_data_integrity_audit():
    """NCAAM integrity checks; return list of result dicts."""
    from configs.leagues.league_ncaam import (
        INTERIM_DIR,
        SCHEDULE_RAW_JSON_PATH,
        SCHEDULE_RAW_PATH,
        CANONICAL_GAMES_PATH,
        GAME_LEVEL_PATH,
    )
    from utils.audit_helpers import audit_file_consistency, audit_csv_consistency

    results = []
    if SCHEDULE_RAW_JSON_PATH.exists() and SCHEDULE_RAW_PATH.exists():
        results.append(audit_file_consistency(
            SCHEDULE_RAW_JSON_PATH, SCHEDULE_RAW_PATH, "NCAAM Ingest (schedule)"
        ))
    else:
        results.append({"label": "NCAAM Ingest (schedule)", "match_status": "skipped"})
    box_json = INTERIM_DIR / "ncaam_boxscores_raw.json"
    box_csv = INTERIM_DIR / "ncaam_boxscores_raw.csv"
    if box_json.exists() and box_csv.exists():
        results.append(audit_file_consistency(box_json, box_csv, "NCAAM Boxscores"))
    else:
        results.append({"label": "NCAAM Boxscores", "match_status": "skipped"})
    if CANONICAL_GAMES_PATH.exists() and GAME_LEVEL_PATH.exists():
        results.append(audit_csv_consistency(
            CANONICAL_GAMES_PATH, GAME_LEVEL_PATH, "NCAAM Canonical (021 vs 022)", expected_derived_per_primary=1.0
        ))
    else:
        results.append({"label": "NCAAM Canonical (021 vs 022)", "match_status": "skipped"})
    return results


def _parse_commence(commence_time):
    if not commence_time:
        return None
    try:
        s = str(commence_time).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _odds_summary_data():
    """Load NBA and NCAAM odds; return first/last dates and counts (active=future, past=commence<=now, total=all)."""
    now = datetime.now(timezone.utc)
    out = {"nba": {"first": None, "last": None, "active": 0, "past": 0, "total": 0}, "ncaam": {"first": None, "last": None, "active": 0, "past": 0, "total": 0}}

    # NBA: try data/nba/raw/odds_master_nba.json (list of snapshots) then data/external/odds_api_raw.json
    nba_paths = [PROJECT_ROOT / "data" / "nba" / "raw" / "odds_master_nba.json", PROJECT_ROOT / "data" / "external" / "odds_api_raw.json"]
    for nba_path in nba_paths:
        if not nba_path.exists():
            continue
        try:
            with open(nba_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            games = []
            if isinstance(data, list) and data:
                for snap in data:
                    if isinstance(snap, dict):
                        games.extend(snap.get("data") or [])
                if not games and isinstance(data[-1], dict):
                    games = data[-1].get("data") or []
            out["nba"]["total"] = len(games)
            with_dt = [(_parse_commence(g.get("commence_time")), g) for g in games if isinstance(g, dict)]
            with_dt = [(dt, g) for dt, g in with_dt if dt is not None]
            out["nba"]["active"] = sum(1 for dt, _ in with_dt if dt > now)
            out["nba"]["past"] = sum(1 for dt, _ in with_dt if dt <= now)
            if with_dt:
                with_dt.sort(key=lambda x: x[0])
                out["nba"]["first"] = with_dt[0][0].strftime("%Y-%m-%d %H:%M UTC")
                out["nba"]["last"] = with_dt[-1][0].strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            pass
        break

    try:
        from configs.leagues.league_ncaam import ODDS_RAW_LATEST_PATH, MARKET_RAW_DIR
        all_ncaam_games = []
        if ODDS_RAW_LATEST_PATH.exists():
            with open(ODDS_RAW_LATEST_PATH, "r", encoding="utf-8") as f:
                snap = json.load(f)
            all_ncaam_games.extend(snap.get("data", []) if isinstance(snap, dict) else [])
        if MARKET_RAW_DIR.exists():
            for p in sorted(MARKET_RAW_DIR.glob("ncaam_odds_raw_*.json")):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        s = json.load(f)
                    if isinstance(s, dict):
                        all_ncaam_games.extend(s.get("data") or [])
                except Exception:
                    pass
        seen = set()
        deduped = []
        for g in all_ncaam_games:
            if not isinstance(g, dict):
                continue
            k = (g.get("id"), g.get("commence_time"))
            if k in seen:
                continue
            seen.add(k)
            deduped.append(g)
        games = deduped
        out["ncaam"]["total"] = len(games)
        with_dt = [(_parse_commence(g.get("commence_time")), g) for g in games]
        with_dt = [(dt, g) for dt, g in with_dt if dt is not None]
        out["ncaam"]["active"] = sum(1 for dt, _ in with_dt if dt > now)
        out["ncaam"]["past"] = sum(1 for dt, _ in with_dt if dt <= now)
        if with_dt:
            with_dt.sort(key=lambda x: x[0])
            out["ncaam"]["first"] = with_dt[0][0].strftime("%Y-%m-%d %H:%M UTC")
            out["ncaam"]["last"] = with_dt[-1][0].strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        pass

    return out


def _top_agent_picks(edge_min: float = 10.0):
    """Load NBA and NCAAM final views; return list of games with Edge > edge_min and their reasoning."""
    from utils.io_helpers import get_final_view_json_path

    def _safe_float(x):
        if x is None or x == "":
            return None
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    picks = []
    for league in ("nba", "ncaam"):
        path = get_final_view_json_path(league)
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                games = json.load(f)
        except Exception:
            continue
        if not isinstance(games, list):
            continue
        for g in games:
            se = _safe_float(g.get("Spread Edge"))
            te = _safe_float(g.get("Total Edge"))
            best = max((abs(x) for x in (se, te) if x is not None), default=0)
            if best <= edge_min:
                continue
            reasoning = (g.get("agent_reasoning") or g.get("Explanation") or "").strip()
            if not reasoning:
                reasoning = "(No reasoning string)"
            picks.append({
                "league": league.upper(),
                "game_id": g.get("game_id") or g.get("canonical_game_id") or "",
                "game_date": g.get("game_date") or "",
                "away_team": g.get("away_team") or g.get("away_team_display") or "",
                "home_team": g.get("home_team") or g.get("home_team_display") or "",
                "spread_edge": se,
                "total_edge": te,
                "line_bet": g.get("Line Bet") or "",
                "total_bet": g.get("Total Bet") or "",
                "reasoning": reasoning,
            })
    return picks


def print_executive_summary(execution_log, audit_results):
    """Single consolidated summary: table (League | Step | Duration | Integrity) + odds table + Model Pulse + OUTPUT LOCATIONS + Top Agent Picks."""
    from utils.io_helpers import get_final_view_json_path

    # Integrity: aggregate NCAAM (PASS if all match, else FAIL)
    ncaam_integrity = "PASS"
    for r in audit_results:
        if r.get("match_status") == "mismatch":
            ncaam_integrity = "FAIL"
            break
        if r.get("match_status") == "skipped":
            ncaam_integrity = "skipped"

    print("\n" + "=" * 90)
    print("EXECUTIVE SUMMARY")
    print("=" * 90)

    # Table: League | Step | Duration | Integrity
    print("\n  League | Step            | Duration  | Integrity")
    print("  -------+-----------------+-----------+----------")
    for entry in execution_log:
        league = "NBA" if "NBA" in entry["label"] else "NCAAM"
        step = entry["label"]
        dur = f"{entry['duration_sec']:.1f}s"
        integrity = "-" if league == "NBA" else ncaam_integrity
        print(f"  {league:<6} | {step:<15} | {dur:>9} | {integrity}")
    total = sum(e["duration_sec"] for e in execution_log)
    print("  -------+-----------------+-----------+----------")
    print(f"  {'Total':<6} |                 | {total:>8.1f}s |")

    # Odds date range (clean table)
    odds = _odds_summary_data()
    print("\n  Odds date range (first / last record):")
    print("  -------+---------------------+---------------------")
    print("  League | First               | Last                ")
    print("  -------+---------------------+---------------------")
    for league in ("nba", "ncaam"):
        lab = league.upper()
        first = odds[league]["first"] or "-"
        last = odds[league]["last"] or "-"
        print(f"  {lab:<6} | {first:<19} | {last:<19}")
    print("  -------+---------------------+---------------------")

    # Odds counts: Active (future) + Past (commence <= now) = all games with valid odds
    print("\n  Odds game counts (all games with valid odds in raw files):")
    print("  -------+--------+--------+--------")
    print("  League | Active | Past   | Total  ")
    print("  -------+--------+--------+--------")
    for league in ("nba", "ncaam"):
        lab = league.upper()
        a, p, t = odds[league]["active"], odds[league]["past"], odds[league]["total"]
        print(f"  {lab:<6} | {a:>6} | {p:>6} | {t:>6}")
    print("  -------+--------+--------+--------")
    print("  (Active = commence_time > now; Past = historical; Total = all in odds raw)")

    # OUTPUT LOCATIONS (one block)
    print("\n  OUTPUT LOCATIONS")
    print("  -" * 40)
    for league in ("nba", "ncaam"):
        p = get_final_view_json_path(league)
        print(f"  {league.upper()}: {p}")
    print("  -" * 40)

    # Top Agent Picks (Edge > 10.0): show Reasoning String
    top_picks = _top_agent_picks(edge_min=10.0)
    if top_picks:
        print("\n  TOP AGENT PICKS (Edge > 10.0)")
        print("  -" * 40)
        for i, p in enumerate(top_picks[:25], 1):
            print(f"  [{i}] {p['league']} {p['game_date']} | {p['away_team']} @ {p['home_team']}")
            print(f"      Spread Edge: {p['spread_edge']} | Total Edge: {p['total_edge']} | Line: {p['line_bet']} | Total: {p['total_bet']}")
            # Show first 2 lines of reasoning (truncate if very long)
            reason = (p["reasoning"] or "").replace("\n", " ").strip()
            if len(reason) > 120:
                reason = reason[:117] + "..."
            print(f"      Reasoning: {reason}")
        if len(top_picks) > 25:
            print(f"  ... and {len(top_picks) - 25} more.")
        print("  -" * 40)
    print("=" * 90 + "\n")


def run_all(args=None):
    if args is None:
        args = parse_args()
    if not NBA_RUNNER.exists():
        raise FileNotFoundError(f"Missing NBA runner: {NBA_RUNNER}")
    if not NCAAM_RUNNER.exists():
        raise FileNotFoundError(f"Missing NCAAM runner: {NCAAM_RUNNER}")

    execution_log = []

    print("\n" + "#" * 90)
    print("COMBINED BOOKIEX RUN")
    print("#" * 90)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python:       {sys.executable}")
    print(f"NBA mode:     {args.mode}")
    print(f"NCAAM window: {args.start_date or 'default'} / {args.end_date or 'default'}")

    t1 = run_step("NBA PIPELINE", build_nba_command(args))
    execution_log.append({"label": "NBA PIPELINE", "duration_sec": t1})

    t2 = run_step("NCAAM PIPELINE", build_ncaam_command(args))
    execution_log.append({"label": "NCAAM PIPELINE", "duration_sec": t2})

    audit_results = run_data_integrity_audit()
    print_executive_summary(execution_log, audit_results)

    if getattr(args, "watch", False):
        from eng.execution.live_monitor_agent import run_loop
        print("\nStarting live monitor (--watch). Alerts written to logs/active_alerts.log. Ctrl+C to stop.")
        run_loop(interval_minutes=30)


if __name__ == "__main__":
    run_all(parse_args())
