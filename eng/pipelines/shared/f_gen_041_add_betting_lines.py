"""
f_gen_041_add_betting_lines.py

Unified add-betting-lines step for NBA and NCAAM.

Behavior (same for both leagues):
- Join flattened odds onto games. Preserve all existing fields.
- Odds drift: when a game already has odds, append new snapshots to odds_history
  (with timestamp) instead of overwriting.
- Finalized protection: if a game is final, do not change closing odds or
  odds_history on subsequent runs.
- Uses utils.io_helpers for load/save game state.

Usage:
  python f_gen_041_add_betting_lines.py --league nba
  python f_gen_041_add_betting_lines.py --league ncaam
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils.io_helpers import (
    get_game_state_path,
    load_previous_game_state_by_id,
    save_game_state,
)
from utils.mapping_helpers import (
    find_best_market_match,
    normalize_ncaam_team_for_match,
    build_ncaam_team_normalization_key,
)
from utils.run_log import set_silent, log_info


# =============================================================================
# SHARED: JOIN WITH DRIFT + FINALIZED PROTECTION (identical logic for both leagues)
# =============================================================================

def join_odds_with_drift_and_finalized(
    games: list[dict],
    odds_index: dict[tuple, dict],
    previous_by_id: dict[str, dict],
    *,
    get_game_id: Callable[[dict], str],
    get_join_key: Callable[[dict], tuple],
    is_finalized: Callable[[dict], bool],
    snapshot_from_odds: Callable[[dict], dict],
    previous_odds_keys: list[str],
    apply_odds: Callable[[dict, dict], None],
    set_missing_odds: Callable[[dict], None] | None = None,
) -> list[dict]:
    """
    Attach odds to games. If game already has odds, append new snapshot to
    odds_history. If game is finalized, do not update market data or odds_history.
    """
    result = []

    for g in games:
        join_key = get_join_key(g)
        game_id = (get_game_id(g) or "").strip()
        odds = odds_index.get(join_key)
        previous = previous_by_id.get(game_id) if game_id else None
        finalized = is_finalized(g)

        out = dict(g)

        # Finalized protection: keep previous odds and odds_history
        if previous and finalized:
            for key in previous_odds_keys:
                if key in previous:
                    out[key] = previous[key]
            out["odds_history"] = list(previous.get("odds_history") or [])
            result.append(out)
            continue

        # Not finalized (or no previous): apply current odds, update odds_history
        if odds:
            apply_odds(out, odds)
            new_snapshot = snapshot_from_odds(odds)
            existing_history = list(previous.get("odds_history", [])) if previous else []
            if existing_history and existing_history[-1].get("captured_at_utc") == new_snapshot.get("captured_at_utc"):
                out["odds_history"] = existing_history
            else:
                out["odds_history"] = existing_history + [new_snapshot]
        else:
            if set_missing_odds:
                set_missing_odds(out)
            out["odds_history"] = list(previous.get("odds_history", [])) if previous else []

        result.append(out)

    return result


def write_csv(games: list[dict], path: Path, *, exclude_keys: set | None = None) -> None:
    """Write CSV; omit odds_history and any other exclude_keys (list not CSV-friendly)."""
    if not games:
        return
    exclude = (exclude_keys or set()) | {"odds_history"}
    all_fields = set()
    for g in games:
        for k in g.keys():
            if k not in exclude:
                all_fields.add(k)
    fieldnames = sorted(all_fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(games)


# =============================================================================
# NBA: INPUTS, JOIN KEY, FINALIZED, SNAPSHOT, PATHS (data/nba/view, data/nba/raw)
# =============================================================================

def _nba_paths():
    from configs.leagues.league_nba import (
        DERIVED_DIR,
        VIEW_DIR,
        GAME_LEVEL_JSON_PATH,
        ODDS_MASTER_PATH,
        BETLINES_FLATTENED_JSON_PATH,
    )
    from pathlib import Path
    legacy_external = Path("data/external")
    return {
        "games_in": GAME_LEVEL_JSON_PATH,
        "odds_in": BETLINES_FLATTENED_JSON_PATH if BETLINES_FLATTENED_JSON_PATH.exists() else DERIVED_DIR / "nba_betlines_flattened.json",
        "odds_master": ODDS_MASTER_PATH if ODDS_MASTER_PATH.exists() else legacy_external / "odds_api_raw.json",
        "csv_out": VIEW_DIR / "nba_games_game_level_with_odds.csv",
    }

NBA_BOOK_PRIORITY = [
    "pinnacle", "circa", "lowvig", "fanduel", "draftkings",
    "betmgm", "betrivers", "bovada", "betus", "betonlineag", "mybookieag",
]
NBA_VALID_MARKETS = {"spreads", "totals", "h2h"}
# Wider window for historical backtest: match odds across UTC/local date boundaries
NBA_JOIN_WINDOW_HOURS = 48


def _nba_is_finalized(game: dict) -> bool:
    home_pts = game.get("home_points")
    away_pts = game.get("away_points")
    if home_pts is None or away_pts is None:
        return False
    if isinstance(home_pts, str) and home_pts.strip() == "":
        return False
    if isinstance(away_pts, str) and away_pts.strip() == "":
        return False
    # Placeholder 0-0 (unplayed/future) must not be treated as finalized so fresh odds can attach.
    try:
        if (float(home_pts) == 0 and float(away_pts) == 0):
            return False
    except (TypeError, ValueError):
        pass
    return True


def _nba_snapshot(odds_row: dict) -> dict:
    return {
        "captured_at_utc": (odds_row.get("odds_snapshot_last_utc") or "").strip(),
        "market_spread_home": odds_row.get("spread_home_last"),
        "market_spread_away": odds_row.get("spread_away_last"),
        "market_total": odds_row.get("total_last"),
        "market_home_moneyline": odds_row.get("moneyline_home_last"),
        "market_away_moneyline": odds_row.get("moneyline_away_last"),
        "bookmaker_key": "consensus",
        "bookmaker_title": "",
    }


def _nba_parse_utc(ts: str) -> datetime:
    return datetime.fromisoformat((ts or "").replace("Z", "+00:00"))

def _nba_pick_last(game_rows: list, market: str, outcome: str) -> float | None:
    candidates = [
        r for r in game_rows
        if r.get("market") == market and r.get("outcome") == outcome
        and ((market == "h2h" and r.get("price") is not None) or (market != "h2h" and r.get("point") is not None))
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda r: (
            _nba_parse_utc(r.get("odds_snapshot_utc") or ""),
            -NBA_BOOK_PRIORITY.index(r["bookmaker_key"]) if r.get("bookmaker_key") in NBA_BOOK_PRIORITY else -999,
        ),
        reverse=True,
    )
    return candidates[0].get("price") if market == "h2h" else candidates[0].get("point")

def _nba_consensus(rows: list, market: str, outcome: str) -> float | None:
    from statistics import mean
    vals = [
        (r.get("price") if market == "h2h" else r.get("point"))
        for r in rows
        if r.get("market") == market and r.get("outcome") == outcome
        and ((market == "h2h" and r.get("price") is not None) or (market != "h2h" and r.get("point") is not None))
    ]
    return round(mean(vals), 3) if vals else None

def _nba_latest_per_bookmaker(game_rows: list) -> list:
    latest = {}
    for r in game_rows:
        key = (r.get("bookmaker_key"), r.get("market"), r.get("outcome"))
        ts = _nba_parse_utc(r.get("odds_snapshot_utc") or "")
        if key not in latest or ts > _nba_parse_utc(latest[key].get("odds_snapshot_utc") or ""):
            latest[key] = r
    return list(latest.values())

def _nba_flatten_master(snapshots: list) -> list[dict]:
    """Flatten odds_api_raw.json (list of snapshots) to one row per game. Same schema as 032 output."""
    from utils.datetime_bridge import derive_game_day_local
    rows = []
    for snap in snapshots:
        captured = snap.get("captured_at_utc")
        if not captured:
            continue
        for game in snap.get("data", []):
            home = game.get("home_team")
            away = game.get("away_team")
            commence = game.get("commence_time")
            if not (home and away and commence):
                continue
            odds_id = (game.get("id") or "")
            odds_id = (odds_id.strip() if isinstance(odds_id, str) else str(odds_id).strip()) if odds_id else ""
            for book in game.get("bookmakers", []):
                for market in book.get("markets", []):
                    if market.get("key") not in NBA_VALID_MARKETS:
                        continue
                    for o in market.get("outcomes", []):
                        rows.append({
                            "home_team": home, "away_team": away,
                            "odds_commence_time_raw": commence, "odds_snapshot_utc": captured,
                            "odds_id": odds_id,
                            "bookmaker_key": book.get("key"), "market": market.get("key"),
                            "outcome": o.get("name"), "point": o.get("point"), "price": o.get("price"),
                        })
    games_grouped = defaultdict(list)
    for r in rows:
        key = (r["home_team"], r["away_team"], r["odds_commence_time_raw"])
        games_grouped[key].append(r)
    final = []
    for (home, away, commence), g_rows in games_grouped.items():
        g_latest = _nba_latest_per_bookmaker(g_rows)
        odds_id = (g_rows[0].get("odds_id") or "") if g_rows else ""
        final.append({
            "home_team": home, "away_team": away,
            "odds_commence_time_utc": commence,
            "nba_game_day_local": derive_game_day_local(commence_time_utc=commence, league="NBA"),
            "odds_id": odds_id,
            "odds_snapshot_last_utc": max(r.get("odds_snapshot_utc") or "" for r in g_rows),
            "spread_home_last": _nba_pick_last(g_rows, "spreads", home),
            "spread_away_last": _nba_pick_last(g_rows, "spreads", away),
            "total_last": _nba_pick_last(g_rows, "totals", "Over"),
            "moneyline_home_last": _nba_pick_last(g_rows, "h2h", home),
            "moneyline_away_last": _nba_pick_last(g_rows, "h2h", away),
        })
    return final

def _nba_game_day_to_dt(s: str) -> datetime | None:
    s = (s or "").strip()[:10]
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None

def _nba_find_best_odds_for_game(game: dict, odds_rows: list[dict], window_hours: int = 24) -> dict | None:
    """Find odds row with same home/away and commence within ±window_hours of game's nba_game_day_local."""
    return find_best_market_match(game, odds_rows, "nba", window_hours)

def _nba_build_odds_index(odds_rows: list[dict]) -> dict[tuple, dict]:
    return {
        (
            (o.get("home_team") or "").strip(),
            (o.get("away_team") or "").strip(),
            (o.get("nba_game_day_local") or "").strip(),
        ): o
        for o in odds_rows
    }

def _nba_build_odds_index_fuzzy(games: list[dict], odds_rows: list[dict], window_hours: int = 24) -> dict[tuple, dict]:
    """Build (home_team, away_team, nba_game_day_local) -> best odds row using ±window_hours for UTC/local drift."""
    index = {}
    for g in games:
        key = (
            (g.get("home_team") or "").strip(),
            (g.get("away_team") or "").strip(),
            (g.get("nba_game_day_local") or "").strip(),
        )
        if not key[0] or not key[1] or not key[2]:
            continue
        row = _nba_find_best_odds_for_game(g, odds_rows, window_hours)
        if row and key not in index:
            index[key] = row
    return index


def _nba_apply_odds(game: dict, odds: dict) -> None:
    for k, v in odds.items():
        if k not in game:
            game[k] = v
    if "odds_join_method" not in game:
        game["odds_join_method"] = "home_away_nba_game_day_local"


NBA_PREVIOUS_ODDS_KEYS = [
    "spread_home_last", "spread_away_last", "total_last",
    "moneyline_home_last", "moneyline_away_last",
    "odds_snapshot_last_utc", "odds_join_method",
    "odds_id",
]


def run_nba() -> None:
    from configs.leagues.league_nba import ensure_nba_dirs
    ensure_nba_dirs()
    paths = _nba_paths()

    with open(paths["games_in"], "r", encoding="utf-8") as f:
        games = json.load(f)

    # Authoritative NBA odds source: flattened artifact from 032 (avoids bloat, single join-ready format).
    odds_rows = []
    if paths["odds_in"].exists():
        with open(paths["odds_in"], "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            odds_rows = data
    if odds_rows:
        log_info(f"Loaded NBA odds from flattened: {paths['odds_in']} ({len(odds_rows)} rows)")
    elif paths["odds_master"].exists():
        with open(paths["odds_master"], "r", encoding="utf-8") as f:
            raw = json.load(f)
        odds_rows = _nba_flatten_master(raw) if isinstance(raw, list) else []
        log_info(f"Loaded NBA odds from master: {paths['odds_master']} ({len(odds_rows)} flattened rows)")

    previous_by_id = load_previous_game_state_by_id("nba", "game_id")
    # ±24h fuzzy join for UTC/local drift
    odds_index = _nba_build_odds_index_fuzzy(games, odds_rows, window_hours=NBA_JOIN_WINDOW_HOURS)
    result = join_odds_with_drift_and_finalized(
        games,
        odds_index,
        previous_by_id,
        get_game_id=lambda g: g.get("game_id") or "",
        get_join_key=lambda g: (g.get("home_team"), g.get("away_team"), g.get("nba_game_day_local")),
        is_finalized=_nba_is_finalized,
        snapshot_from_odds=_nba_snapshot,
        previous_odds_keys=NBA_PREVIOUS_ODDS_KEYS,
        apply_odds=_nba_apply_odds,
        set_missing_odds=None,
    )

    save_game_state("nba", result)
    write_csv(result, paths["csv_out"])

    attached = sum(1 for g in result if g.get("spread_home_last") is not None or g.get("total_last") is not None)
    missing = len(result) - attached
    with_history = sum(1 for g in result if len(g.get("odds_history") or []) > 0)
    finalized_locked = sum(1 for g in result if _nba_is_finalized(g) and previous_by_id.get((g.get("game_id") or "").strip()))

    log_info("Non-destructive odds enrichment complete (with drift + finalized protection)")
    log_info(f"Joined rows:             {attached}")
    log_info(f"Missing odds:           {missing}")
    if missing >= 100:
        log_info(f"Validation:              WARNING — missing odds >= 100 (target: < 100)")
    else:
        log_info(f"Validation:              OK — missing odds < 100")
    log_info(f"Rows with odds_history: {with_history}")
    log_info(f"Finalized (locked):      {finalized_locked}")
    log_info(f"JSON written to:         {get_game_state_path('nba')}")
    log_info(f"CSV written to:         {paths['csv_out']}")


# =============================================================================
# NCAAM: INPUTS, NORMALIZATION, COLLAPSE, JOIN KEY, FINALIZED, SNAPSHOT, PATHS
# =============================================================================

def _ncaam_has_state_suffix_semantics(norm_key: str) -> bool:
    value = (norm_key or "").strip().lower()
    return value.endswith("state") or value.endswith("st")


def _ncaam_team_name_for_match(value: str) -> str:
    """Standardize for Odds API vs ESPN; uses NCAAM_ALIAS_MAP and common suffixes."""
    return normalize_ncaam_team_for_match(value)


def _ncaam_build_team_normalization_key(value: str) -> str:
    return build_ncaam_team_normalization_key(value)


def _ncaam_resolve_team_name(raw_name: str, team_lookup: list[dict]) -> dict | None:
    raw_match_key = _ncaam_team_name_for_match(raw_name)
    if raw_match_key:
        for candidate in team_lookup:
            if candidate.get("match_key") == raw_match_key:
                return candidate
    raw_norm_key = _ncaam_build_team_normalization_key(raw_name)
    if not raw_norm_key:
        return None
    raw_has_state = _ncaam_has_state_suffix_semantics(raw_norm_key)
    matches = []
    for candidate in team_lookup:
        map_norm_key = candidate["team_name_norm_key"]
        map_has_state = _ncaam_has_state_suffix_semantics(map_norm_key)
        if map_has_state != raw_has_state:
            continue
        if map_norm_key in raw_norm_key:
            matches.append(candidate)
    if not matches:
        return None
    exact_matches = [m for m in matches if m["team_name_norm_key"] == raw_norm_key]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        return None
    top_len = len(matches[0]["team_name_norm_key"])
    top_matches = [m for m in matches if len(m["team_name_norm_key"]) == top_len]
    if len(top_matches) == 1:
        return top_matches[0]
    return None


def _ncaam_safe_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _ncaam_build_team_lookup(team_map_rows: list[dict]) -> list[dict]:
    lookup_rows = []
    for row in team_map_rows:
        team_id = (row.get("team_id") or "").strip()
        team_display = (row.get("team_display") or "").strip()
        team_name_norm_key = (row.get("team_name_norm_key") or "").strip().lower()
        if not team_id:
            continue
        if not team_name_norm_key and team_display:
            team_name_norm_key = _ncaam_build_team_normalization_key(team_display)
        if not team_name_norm_key:
            continue
        match_key = _ncaam_team_name_for_match(team_display or team_name_norm_key)
        lookup_rows.append({
            "mapped_team_id": team_id,
            "mapped_team_display": team_display,
            "team_name_norm_key": team_name_norm_key,
            "match_key": match_key,
        })
    lookup_rows.sort(key=lambda r: len(r["team_name_norm_key"]), reverse=True)
    return lookup_rows


def _ncaam_flatten_single_snapshot(snapshot: dict) -> list[dict]:
    """Flatten one raw NCAAM odds JSON (data list of games) to outcome-level rows. Same schema as 032 flat CSV."""
    raw_data = snapshot.get("data", [])
    if not isinstance(raw_data, list):
        return []
    captured_at = snapshot.get("captured_at_utc")
    sport = snapshot.get("sport")
    source = snapshot.get("source")
    rows = []
    for game in raw_data:
        game_id = game.get("id")
        commence_time = game.get("commence_time")
        home_team = game.get("home_team")
        away_team = game.get("away_team")
        last_update_game = game.get("last_update")
        for bookmaker in game.get("bookmakers", []):
            bookmaker_key = bookmaker.get("key")
            bookmaker_title = bookmaker.get("title")
            bookmaker_last_update = bookmaker.get("last_update")
            for market in bookmaker.get("markets", []):
                market_key = market.get("key")
                market_last_update = market.get("last_update")
                for outcome in market.get("outcomes", []):
                    rows.append({
                        "captured_at_utc": captured_at,
                        "source": source,
                        "sport": sport,
                        "game_id": game_id,
                        "commence_time": commence_time,
                        "game_last_update": last_update_game,
                        "home_team": home_team,
                        "away_team": away_team,
                        "bookmaker_key": bookmaker_key,
                        "bookmaker_title": bookmaker_title,
                        "bookmaker_last_update": bookmaker_last_update,
                        "market_key": market_key,
                        "market_last_update": market_last_update,
                        "outcome_name": outcome.get("name"),
                        "price": outcome.get("price"),
                        "point": outcome.get("point"),
                    })
    return rows


def _ncaam_collapse_odds_rows(odds_rows: list[dict], team_lookup: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for row in odds_rows:
        game_id = (row.get("game_id") or "").strip()
        bookmaker_key = (row.get("bookmaker_key") or "").strip()
        if not game_id or not bookmaker_key:
            continue
        grouped[(game_id, bookmaker_key)].append(row)
    out = []
    for (game_id, bookmaker_key), rows in grouped.items():
        sample = rows[0]
        home_team_raw = (sample.get("home_team") or "").strip()
        away_team_raw = (sample.get("away_team") or "").strip()
        home_lookup = _ncaam_resolve_team_name(home_team_raw, team_lookup)
        away_lookup = _ncaam_resolve_team_name(away_team_raw, team_lookup)
        event_row = {
            "odds_game_id": game_id,
            "commence_time": (sample.get("commence_time") or "").strip(),
            "home_team_raw": home_team_raw,
            "away_team_raw": away_team_raw,
            "home_team_id": home_lookup["mapped_team_id"] if home_lookup else "",
            "away_team_id": away_lookup["mapped_team_id"] if away_lookup else "",
            "home_team_display": home_lookup["mapped_team_display"] if home_lookup else "",
            "away_team_display": away_lookup["mapped_team_display"] if away_lookup else "",
            "bookmaker_key": bookmaker_key,
            "bookmaker_title": (sample.get("bookmaker_title") or "").strip(),
            "captured_at_utc": (sample.get("captured_at_utc") or "").strip(),
            "spread_home": None,
            "spread_away": None,
            "market_total": None,
            "home_moneyline": None,
            "away_moneyline": None,
        }
        for row in rows:
            market_key = (row.get("market_key") or "").strip()
            outcome_name = (row.get("outcome_name") or "").strip()
            price = _ncaam_safe_float(row.get("price"))
            point = _ncaam_safe_float(row.get("point"))
            if market_key == "spreads":
                if outcome_name == home_team_raw:
                    event_row["spread_home"] = point
                elif outcome_name == away_team_raw:
                    event_row["spread_away"] = point
            elif market_key == "totals":
                if outcome_name.lower() in {"over", "under"} and point is not None:
                    event_row["market_total"] = point
            elif market_key == "h2h":
                if outcome_name == home_team_raw:
                    event_row["home_moneyline"] = price
                elif outcome_name == away_team_raw:
                    event_row["away_moneyline"] = price
        out.append(event_row)
    out.sort(key=lambda r: (r["commence_time"], r["home_team_id"], r["away_team_id"], r["bookmaker_key"]))
    return out


def _ncaam_find_best_odds_for_game(game: dict, collapsed_rows: list[dict], window_hours: int = 24) -> dict | None:
    """
    Find best odds row for game. Uses shared find_best_market_match with NCAAM window:
    game_date (often local) vs commence_time (UTC) — e.g. 11 PM Monday local matches
    early Tuesday UTC (window: game_date midnight UTC -12h to +36h).
    """
    return find_best_market_match(game, collapsed_rows, "ncaam", window_hours)


def _ncaam_build_event_lookup(collapsed_rows: list[dict], base_rows: list[dict]) -> dict[tuple[str, str, str], dict]:
    """Build (game_date, home_team_id, away_team_id) -> odds row using ±24h fuzzy date match per game."""
    lookup = {}
    for game in base_rows:
        key = (
            (game.get("game_date") or "").strip()[:10],
            (game.get("home_team_id") or "").strip(),
            (game.get("away_team_id") or "").strip(),
        )
        if not key[0] or not key[1] or not key[2]:
            continue
        row = _ncaam_find_best_odds_for_game(game, collapsed_rows)
        if row and key not in lookup:
            lookup[key] = row
    return lookup


def _ncaam_is_finalized(row: dict) -> bool:
    completed = row.get("completed_flag")
    if completed is not None and completed != "":
        try:
            if int(completed) == 1:
                return True
        except (TypeError, ValueError):
            pass
    status_name = (row.get("status_name") or "").strip().upper()
    if status_name == "STATUS_FINAL":
        return True
    status_state = (row.get("status_state") or "").strip().lower()
    if status_state == "post":
        return True
    return False


def _ncaam_snapshot(market_row: dict) -> dict:
    return {
        "captured_at_utc": (market_row.get("captured_at_utc") or "").strip(),
        "market_spread_home": market_row.get("spread_home"),
        "market_spread_away": market_row.get("spread_away"),
        "market_total": market_row.get("market_total"),
        "market_home_moneyline": market_row.get("home_moneyline"),
        "market_away_moneyline": market_row.get("away_moneyline"),
        "bookmaker_key": (market_row.get("bookmaker_key") or "").strip(),
        "bookmaker_title": (market_row.get("bookmaker_title") or "").strip(),
    }


def _ncaam_apply_odds(game: dict, market: dict) -> None:
    game["line_join_status"] = "matched"
    game["bookmaker_key"] = market.get("bookmaker_key", "")
    game["bookmaker_title"] = market.get("bookmaker_title", "")
    game["captured_at_utc"] = market.get("captured_at_utc", "")
    game["market_spread_home"] = market.get("spread_home", "")
    game["market_spread_away"] = market.get("spread_away", "")
    game["market_total"] = market.get("market_total", "")
    game["market_home_moneyline"] = market.get("home_moneyline", "")
    game["market_away_moneyline"] = market.get("away_moneyline", "")


def _ncaam_set_missing_odds(game: dict) -> None:
    game["line_join_status"] = "unmatched"
    game["bookmaker_key"] = ""
    game["bookmaker_title"] = ""
    game["captured_at_utc"] = ""
    game["market_spread_home"] = ""
    game["market_spread_away"] = ""
    game["market_total"] = ""
    game["market_home_moneyline"] = ""
    game["market_away_moneyline"] = ""


NCAAM_PREVIOUS_ODDS_KEYS = [
    "line_join_status", "bookmaker_key", "bookmaker_title", "captured_at_utc",
    "market_spread_home", "market_spread_away", "market_total",
    "market_home_moneyline", "market_away_moneyline",
]


def run_ncaam() -> None:
    from configs.leagues.league_ncaam import (
        ODDS_FLAT_LATEST_PATH,
        MARKET_RAW_DIR,
        MODEL_DIR,
        RAW_DIR,
        ensure_ncaam_dirs,
    )
    MODEL_INPUT_V1_PATH = MODEL_DIR / "ncaam_model_input_v1.csv"
    TEAM_MAP_PATH = RAW_DIR / "ncaam_team_map.csv"
    OUTPUT_CSV_PATH = MODEL_DIR / "ncaam_canonical_games_with_lines.csv"

    ensure_ncaam_dirs()

    with open(MODEL_INPUT_V1_PATH, "r", encoding="utf-8", newline="") as f:
        base_rows = list(csv.DictReader(f))
    with open(TEAM_MAP_PATH, "r", encoding="utf-8", newline="") as f:
        team_map_rows = list(csv.DictReader(f))

    # Multi-file historical: glob all ncaam_odds_raw_*.json and merge (latest per game x bookmaker)
    raw_files = sorted(MARKET_RAW_DIR.glob("ncaam_odds_raw_*.json"))
    if raw_files:
        all_flat = []
        for path in raw_files:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    snap = json.load(f)
                if isinstance(snap, dict):
                    all_flat.extend(_ncaam_flatten_single_snapshot(snap))
            except Exception:
                continue
        if all_flat:
            # Keep latest captured_at_utc per (game_id, bookmaker_key); retain all outcome rows for that snapshot
            by_key = defaultdict(list)
            for r in all_flat:
                gid = (r.get("game_id") or "").strip()
                bk = (r.get("bookmaker_key") or "").strip()
                if gid and bk:
                    by_key[(gid, bk)].append(r)
            latest_rows = []
            for _key, group in by_key.items():
                cap = max((r.get("captured_at_utc") or "" for r in group), default="")
                latest_rows.extend(r for r in group if (r.get("captured_at_utc") or "") == cap)
            odds_rows = latest_rows
        else:
            odds_rows = []
        if not odds_rows and ODDS_FLAT_LATEST_PATH.exists():
            with open(ODDS_FLAT_LATEST_PATH, "r", encoding="utf-8", newline="") as f:
                odds_rows = list(csv.DictReader(f))
    else:
        odds_rows = []
        if ODDS_FLAT_LATEST_PATH.exists():
            with open(ODDS_FLAT_LATEST_PATH, "r", encoding="utf-8", newline="") as f:
                odds_rows = list(csv.DictReader(f))

    team_lookup = _ncaam_build_team_lookup(team_map_rows)
    collapsed_rows = _ncaam_collapse_odds_rows(odds_rows, team_lookup)
    odds_index = _ncaam_build_event_lookup(collapsed_rows, base_rows)
    previous_by_id = load_previous_game_state_by_id("ncaam", "canonical_game_id")

    result = join_odds_with_drift_and_finalized(
        base_rows,
        odds_index,
        previous_by_id,
        get_game_id=lambda r: r.get("canonical_game_id") or "",
        get_join_key=lambda r: (
            (r.get("game_date") or "").strip(),
            (r.get("home_team_id") or "").strip(),
            (r.get("away_team_id") or "").strip(),
        ),
        is_finalized=_ncaam_is_finalized,
        snapshot_from_odds=_ncaam_snapshot,
        previous_odds_keys=NCAAM_PREVIOUS_ODDS_KEYS,
        apply_odds=_ncaam_apply_odds,
        set_missing_odds=_ncaam_set_missing_odds,
    )

    save_game_state("ncaam", result)
    write_csv(result, OUTPUT_CSV_PATH)

    matched_count = sum(1 for r in result if (r.get("line_join_status") or "") == "matched")
    unmatched_count = sum(1 for r in result if (r.get("line_join_status") or "") == "unmatched")
    with_history = sum(1 for r in result if len(r.get("odds_history") or []) > 0)
    finalized_locked = sum(1 for r in result if _ncaam_is_finalized(r) and previous_by_id.get((r.get("canonical_game_id") or "").strip()))

    if matched_count <= 3000:
        log_info(f"Validation:                 WARNING — line-matched rows = {matched_count} (target: > 3,000)")
    else:
        log_info(f"Validation:                 OK — line-matched rows > 3,000 ({matched_count})")

    log_info(f"Loaded model input rows:     {len(base_rows)}")
    log_info(f"Loaded flat odds rows:       {len(odds_rows)}")
    log_info(f"Previous output games:       {len(previous_by_id)}")
    log_info(f"Collapsed market rows:      {len(collapsed_rows)}")
    log_info(f"JSON written to:            {get_game_state_path('ncaam')}")
    log_info(f"CSV written to:             {OUTPUT_CSV_PATH}")
    log_info(f"Line-matched rows:          {matched_count}")
    log_info(f"Line-unmatched rows:        {unmatched_count}")
    log_info(f"Rows with odds_history:     {with_history}")
    log_info(f"Finalized (locked):         {finalized_locked}")


# =============================================================================
# ENTRYPOINT
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Add betting lines to games (NBA or NCAAM)")
    parser.add_argument("--league", required=True, choices=["nba", "ncaam"], help="League to process")
    parser.add_argument("--silent", action="store_true", help="Only print critical errors")
    args = parser.parse_args()
    set_silent(args.silent)

    if args.league == "nba":
        run_nba()
    else:
        run_ncaam()


if __name__ == "__main__":
    main()
