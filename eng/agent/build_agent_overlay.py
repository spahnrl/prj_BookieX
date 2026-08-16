#!/usr/bin/env python3
"""
Canonical BookieX agent overlay builder (MVP).

Reads the league daily-view artifact, builds a canonical agent overlay JSON
per dev_31 / dev_32 / dev_33, and writes to data/<league>/view/<league>_agent_overlay.json.

Usage:
  python eng/agent/build_agent_overlay.py --league nba
  python eng/agent/build_agent_overlay.py --league ncaam
  python eng/agent/build_agent_overlay.py --league nfl
  python eng/agent/build_agent_overlay.py --league ncaaf
  python eng/agent/build_agent_overlay.py --league all
  python eng/agent/build_agent_overlay.py --league nba --dry-run

Does not mutate baseline artifacts. Stdlib + safe path/io helpers only.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Project root: eng/agent/build_agent_overlay.py -> parents[2] = project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OVERLAY_SCHEMA_VERSION = "1.0"
AGENT_VERSION_MVP = "mvp_v1"

# Allowed agent_recommended_action (dev_32)
ACTION_EXECUTE = "EXECUTE"
ACTION_HOLD = "HOLD"
ACTION_AVOID = "AVOID"

# Pick types
PICK_TYPE_SPREAD = "SPREAD"
PICK_TYPE_TOTAL = "TOTAL"
PICK_TYPE_NO_BET = "NO_BET"


def resolve_paths_for_league(league: str, date_str: str | None) -> dict[str, Path | str]:
    """Resolve input (daily view) and output (overlay) paths for a league.

    Uses existing io_helpers for daily dir only; output path is canonical per dev_32.
    """
    league = (league or "").strip().lower()
    if league not in ("nba", "ncaam", "nfl", "ncaaf"):
        raise ValueError(f"Unknown league: {league!r}. Use nba, ncaam, nfl, or ncaaf.")

    from utils.io_helpers import get_daily_view_output_dir

    daily_dir = get_daily_view_output_dir(league)
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if league == "nba":
        source_path = daily_dir / f"daily_view_{date_str}_v1.json"
    elif league == "ncaam":
        source_path = daily_dir / f"daily_view_ncaam_{date_str}_v1.json"
    else:
        source_path = daily_dir / f"daily_view_{league}_{date_str}_v1.json"

    output_path = PROJECT_ROOT / "data" / league / "view" / f"{league}_agent_overlay.json"

    return {
        "league": league,
        "date_str": date_str,
        "source_path": source_path,
        "output_path": output_path,
    }


def load_daily_view(path: Path) -> dict | list:
    """Load daily view JSON from path. Returns raw parsed value (dict or list)."""
    if not path.exists():
        raise FileNotFoundError(f"Daily view not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, (dict, list)):
        raise ValueError(f"Daily view must be JSON object or array: {path}")
    return data


def extract_games_from_daily_view(data: dict | list) -> list[dict]:
    """Extract list of game objects from daily view (dict with 'games' or list of games)."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        games = data.get("games")
        if games is not None and isinstance(games, list):
            return games
        raise ValueError("Daily view object has no 'games' array")
    raise ValueError("Daily view must be dict or list")


def _get_identity(game: dict) -> dict:
    return game.get("identity") or game


def _get_model_output(game: dict) -> dict:
    return game.get("model_output") or {}


def _get_agent_overrides(game: dict) -> dict:
    overrides = game.get("agent_overrides") or {}
    if isinstance(overrides, dict):
        return overrides
    return {}


def _game_id(game: dict) -> str | None:
    """Extract game_id from identity or top-level. Returns None if missing."""
    identity = _get_identity(game)
    gid = identity.get("game_id") or game.get("game_id")
    if gid is not None and str(gid).strip():
        return str(gid).strip()
    return None


def _baseline_pick_and_type(game: dict) -> tuple[str | None, str | None]:
    """Derive baseline_pick and baseline_pick_type from model_output (Line Bet / Total Bet)."""
    mo = _get_model_output(game)
    spread = (mo.get("spread_pick") or mo.get("Line Bet") or "").strip()
    total = (mo.get("total_pick") or mo.get("Total Bet") or "").strip()
    if spread:
        return (spread, PICK_TYPE_SPREAD)
    if total:
        return (total, PICK_TYPE_TOTAL)
    return (None, None)


def _agent_pick_from_source(game: dict, baseline_pick: str | None) -> tuple[str | None, str | None]:
    """Get agent pick from override or baseline. Returns (pick, pick_type)."""
    overrides = _get_agent_overrides(game)
    override_pick = overrides.get("override_pick")
    if override_pick is not None and str(override_pick).strip():
        pick = str(override_pick).strip().upper()
        if pick in ("OVER", "UNDER"):
            return (pick, PICK_TYPE_TOTAL)
        if pick in ("HOME", "AWAY"):
            return (pick, PICK_TYPE_SPREAD)
        if pick in ("NO_BET", "NO BET", "NONE", ""):
            return (PICK_TYPE_NO_BET, PICK_TYPE_NO_BET)
        return (pick, PICK_TYPE_SPREAD)
    if baseline_pick:
        if baseline_pick in ("OVER", "UNDER"):
            return (baseline_pick, PICK_TYPE_TOTAL)
        return (baseline_pick, PICK_TYPE_SPREAD)
    return (None, None)


# Generic confidence_reason strings we replace with a grounded fallback when no Sweet Spot reasoning exists.
_GENERIC_CONFIDENCE_REASONS = frozenset({
    "No model signal yet",
    "NCAAM MVP placeholder confidence",
    "No agent override; baseline used.",
    "No model signal",
    "Signal present but edge below threshold",
})


def _fallback_reasoning_from_game(game: dict) -> str:
    """Build a short, factual fallback when no richer reasoning exists. Uses only fields on the row."""
    mo = _get_model_output(game)
    edges = game.get("edge_metrics") or {}
    spread_edge = edges.get("spread_edge")
    total_edge = edges.get("total_edge")
    spread_pick = (mo.get("spread_pick") or mo.get("Line Bet") or "").strip()
    total_pick = (mo.get("total_pick") or mo.get("Total Bet") or "").strip()

    if spread_pick and spread_edge is not None:
        return f"Selecting {spread_pick} against the spread based on a spread edge of {spread_edge:.1f}; no Sweet Spot matched."
    if total_pick and total_edge is not None:
        return f"Selecting {total_pick} based on a total edge of {total_edge:.1f}; no Sweet Spot matched."
    if spread_pick or total_pick:
        pick = spread_pick or total_pick
        return f"Selecting {pick}; no edge data available; no Sweet Spot matched."
    return "No model edge cleared the threshold; baseline used."


def _agent_reasoning_from_source(game: dict) -> str:
    """Canonical agent_reasoning: prefer agent_reasoning, then override_reason, then confidence_reason (migration)."""
    # Prefer canonical agent_reasoning; never write @agent_reasoning (deprecated).
    reason = game.get("agent_reasoning") or game.get("@agent_reasoning")
    if reason is not None and str(reason).strip():
        return str(reason).strip()
    # Richer source: when agent applied an override, use its reason for agent_reasoning (NBA daily view has this).
    overrides = _get_agent_overrides(game)
    reason = overrides.get("override_reason")
    if reason is not None and str(reason).strip():
        return str(reason).strip()
    mo = _get_model_output(game)
    reason = mo.get("agent_reasoning") or mo.get("confidence_reason")
    if reason is not None and str(reason).strip() and str(reason).strip() not in _GENERIC_CONFIDENCE_REASONS:
        return str(reason).strip()
    # Migration fallback: use baseline confidence_reason unless it is generic, then use grounded fallback.
    reason = game.get("confidence_reason") or mo.get("confidence_reason")
    if reason is not None and str(reason).strip() and str(reason).strip() not in _GENERIC_CONFIDENCE_REASONS:
        return str(reason).strip()
    return _fallback_reasoning_from_game(game)


def derive_agent_fields_from_game(game: dict, baseline_pick: str | None, baseline_type: str | None) -> dict:
    """Build the agent-derived fields for one game (no game_id / baseline_pick here; caller adds)."""
    overrides = _get_agent_overrides(game)
    agent_pick, agent_pick_type = _agent_pick_from_source(game, baseline_pick)

    override_pick = overrides.get("override_pick")
    override_reason = overrides.get("override_reason")
    override_delta = overrides.get("override_confidence_delta")

    # agent_override_applied: true iff we have an override that changed the pick
    override_applied = False
    if override_pick is not None and str(override_pick).strip():
        if baseline_pick and str(override_pick).strip().upper() != str(baseline_pick).strip().upper():
            override_applied = True
        elif not baseline_pick:
            override_applied = True

    # agent_agrees_with_baseline
    agrees = False
    if agent_pick and baseline_pick:
        agrees = str(agent_pick).strip().upper() == str(baseline_pick).strip().upper()
    elif not agent_pick and not baseline_pick:
        agrees = True

    # agent_no_bet: explicit no-bet or veto
    no_bet = agent_pick == PICK_TYPE_NO_BET or (agent_pick or "").upper() in ("NO_BET", "NO BET", "NONE")
    no_bet_reason = None
    if no_bet and override_reason:
        no_bet_reason = str(override_reason).strip()

    # agent_recommended_action: EXECUTE / HOLD / AVOID per schema
    if no_bet:
        recommended_action = ACTION_AVOID
    elif agent_pick and agrees:
        recommended_action = ACTION_EXECUTE
    elif agent_pick:
        recommended_action = ACTION_EXECUTE
    else:
        recommended_action = ACTION_HOLD

    # agent_confidence: from model_output or null
    mo = _get_model_output(game)
    confidence = mo.get("confidence_tier") or mo.get("actionability") or game.get("actionability")
    if confidence is not None and str(confidence).strip():
        confidence = str(confidence).strip()
    else:
        confidence = None

    return {
        "agent_pick": agent_pick or PICK_TYPE_NO_BET,
        "agent_pick_type": agent_pick_type or PICK_TYPE_NO_BET,
        "agent_confidence": confidence,
        "agent_confidence_delta": override_delta if override_delta is not None else None,
        "agent_agrees_with_baseline": agrees,
        "agent_recommended_action": recommended_action,
        "agent_no_bet": no_bet,
        "agent_no_bet_reason": no_bet_reason,
        "agent_reasoning": _agent_reasoning_from_source(game),
        "agent_model_preference": None,
        "agent_supporting_signals": [],
        "agent_risk_flags": [],
        "agent_override_applied": override_applied,
        "agent_override_reason": str(override_reason).strip() if override_reason else None,
        "agent_rank": None,
    }


def build_game_overlay(
    game: dict,
    build_ts: str,
    agent_version: str,
) -> dict:
    """Build one game-level overlay object per dev_32."""
    game_id = _game_id(game)
    baseline_pick, baseline_type = _baseline_pick_and_type(game)
    derived = derive_agent_fields_from_game(game, baseline_pick, baseline_type)

    return {
        "game_id": game_id,
        "baseline_pick": baseline_pick,
        "baseline_pick_type": baseline_type,
        **derived,
        "agent_version": agent_version,
        "agent_timestamp": build_ts,
    }


def build_slate_object(games: list[dict], build_ts: str, agent_version: str) -> dict:
    """Build minimal slate object for MVP."""
    return {
        "agent_summary": "MVP overlay generated from daily view; baseline vs agent comparison available.",
        "agent_strategy_note": "Overlay MVP; not a learned model.",
        "agent_top_picks": [],
        "agent_status": "mvp_overlay",
        "agent_last_updated": build_ts,
    }


def build_top_level_overlay(
    league: str,
    source_path: Path,
    source_build_ts: str | None,
    games: list[dict],
    build_ts: str,
    agent_version: str,
) -> dict:
    """Build full overlay root with slate and games array."""
    slate = build_slate_object(games, build_ts, agent_version)
    game_overlays = []
    for g in games:
        game_id = _game_id(g)
        if not game_id:
            continue
        game_overlays.append(build_game_overlay(g, build_ts, agent_version))

    return {
        "league": league,
        "build_timestamp": build_ts,
        "agent_version": agent_version,
        "overlay_schema_version": OVERLAY_SCHEMA_VERSION,
        "source_artifact": str(source_path),
        "source_build_timestamp": source_build_ts,
        "run_mode": "daily",
        "game_count": len(game_overlays),
        "slate": slate,
        "games": game_overlays,
    }


def validate_overlay(overlay: dict) -> list[str]:
    """Run lightweight validation; return list of error messages (empty if valid)."""
    errors = []
    if not overlay.get("league"):
        errors.append("Missing league")
    if overlay.get("game_count") is not None and overlay.get("games") is not None:
        if overlay["game_count"] != len(overlay["games"]):
            errors.append(f"game_count ({overlay['game_count']}) != len(games) ({len(overlay['games'])})")
    games = overlay.get("games") or []
    seen = set()
    for i, g in enumerate(games):
        gid = g.get("game_id")
        if not gid:
            errors.append(f"Game index {i} missing game_id")
        elif gid in seen:
            errors.append(f"Duplicate game_id: {gid}")
        else:
            seen.add(gid)
        for key in ("agent_pick", "agent_agrees_with_baseline", "agent_reasoning"):
            if key not in g:
                errors.append(f"Game {gid or i} missing required field: {key}")
    if "build_timestamp" not in overlay:
        errors.append("Missing build_timestamp")
    if "overlay_schema_version" not in overlay:
        errors.append("Missing overlay_schema_version")
    if "source_artifact" not in overlay:
        errors.append("Missing source_artifact")
    return errors


def safe_write_json(path: Path, payload: dict, pretty: bool = True) -> None:
    """Write JSON to path; create parent dirs; deterministic key order for top-level and games."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sort keys for deterministic output
    def sort_keys(obj):
        if isinstance(obj, dict):
            return {k: sort_keys(obj[k]) for k in sorted(obj.keys())}
        if isinstance(obj, list):
            return [sort_keys(i) for i in obj]
        return obj
    ordered = sort_keys(payload)
    with path.open("w", encoding="utf-8") as f:
        if pretty:
            json.dump(ordered, f, indent=2, ensure_ascii=False)
        else:
            json.dump(ordered, f, ensure_ascii=False)
        f.write("\n")


def build_agent_overlay(
    league: str,
    date_str: str | None = None,
    dry_run: bool = False,
    pretty: bool = True,
) -> dict:
    """
    Build canonical agent overlay for one league.

    Returns summary dict: source_path, output_path, games_read, games_written, skipped, warnings.
    """
    paths = resolve_paths_for_league(league, date_str)
    source_path = paths["source_path"]
    output_path = paths["output_path"]
    league_key = paths["league"]

    summary = {
        "league": league_key,
        "source_path": str(source_path),
        "output_path": str(output_path),
        "games_read": 0,
        "games_written": 0,
        "skipped": 0,
        "warnings": [],
    }

    data = load_daily_view(source_path)
    games = extract_games_from_daily_view(data)
    summary["games_read"] = len(games)

    source_build_ts = None
    if isinstance(data, dict):
        source_build_ts = data.get("build_timestamp_utc") or data.get("build_timestamp")

    build_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    overlay = build_top_level_overlay(
        league_key,
        source_path,
        source_build_ts,
        games,
        build_ts,
        AGENT_VERSION_MVP,
    )

    # Skip games without game_id (already done in build_top_level_overlay)
    written = overlay.get("games") or []
    summary["games_written"] = len(written)
    summary["skipped"] = summary["games_read"] - summary["games_written"]
    if summary["skipped"] > 0:
        summary["warnings"].append(f"Skipped {summary['skipped']} game(s) missing game_id")

    errs = validate_overlay(overlay)
    if errs:
        raise ValueError("Overlay validation failed: " + "; ".join(errs))

    if not dry_run:
        safe_write_json(output_path, overlay, pretty=pretty)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build canonical BookieX agent overlay (MVP)")
    parser.add_argument("--league", type=str, default="nba", choices=["nba", "ncaam", "nfl", "ncaaf", "all"],
                        help="League: nba, ncaam, nfl, ncaaf, or all")
    parser.add_argument("--date", type=str, default=None,
                        help="Date YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--dry-run", action="store_true", help="Build and validate but do not write")
    parser.add_argument("--pretty", action="store_true", default=True, help="Pretty-print JSON (default: True)")
    args = parser.parse_args()

    leagues = ["nba", "ncaam", "nfl", "ncaaf"] if args.league == "all" else [args.league]
    if args.league == "all":
        leagues = ["nba", "ncaam", "nfl", "ncaaf"]

    total_warnings = 0
    for league in leagues:
        try:
            summary = build_agent_overlay(
                league,
                date_str=args.date,
                dry_run=args.dry_run,
                pretty=args.pretty,
            )
            w = len(summary.get("warnings") or [])
            total_warnings += w
            print(f"[{league}] source: {summary['source_path']}")
            print(f"[{league}] output: {summary['output_path']}")
            print(f"[{league}] games read: {summary['games_read']}  written: {summary['games_written']}  skipped: {summary['skipped']}")
            if summary.get("warnings"):
                for msg in summary["warnings"]:
                    print(f"[{league}] WARN: {msg}")
            if args.dry_run:
                print(f"[{league}] (dry-run; no file written)")
            else:
                print(f"[{league}] Overlay written.")
        except FileNotFoundError as e:
            print(f"[{league}] FAIL: {e}", file=sys.stderr)
            return 1
        except ValueError as e:
            print(f"[{league}] FAIL: {e}", file=sys.stderr)
            return 1

    if args.league == "all":
        print(f"Done. Total warnings: {total_warnings}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
