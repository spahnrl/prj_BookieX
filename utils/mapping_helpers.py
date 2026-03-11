"""
utils/mapping_helpers.py

Shared odds ↔ game mapping: ±window fuzzy date match and team normalization.
Used by f_gen_041 (NBA and NCAAM) for joining market rows to games.
"""

import re
from datetime import datetime, timedelta
from typing import Any

# -----------------------------------------------------------------------------
# NCAAM alias master: odds/schedule display names -> canonical for matching
# -----------------------------------------------------------------------------

NCAAM_ALIAS_MAP = {
    "Ole Miss": "Mississippi",
    "NC State": "North Carolina State",
    "UConn": "Connecticut",
    "UNC": "North Carolina",
    "Penn St": "Pennsylvania State",
}


def _normalize_name(value: str) -> str:
    text = (value or "").strip().lower()
    text = text.replace("&", " and ").replace("'", "").replace(".", " ").replace("-", " ").replace("/", " ").replace(",", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_ncaam_team_for_match(raw_name: str) -> str:
    """
    Standardize NCAAM team name for matching (Odds API vs ESPN).
    Applies NCAAM_ALIAS_MAP first, then normalization and abbreviation handling.
    """
    s = (raw_name or "").strip()
    if not s:
        return ""
    s = NCAAM_ALIAS_MAP.get(s) or s
    n = _normalize_name(s)
    if n.startswith("nc ") or n == "nc":
        n = ("north carolina " + n[3:].strip()).strip()
    if n.startswith("st "):
        n = n[3:].strip()
    if n.endswith(" state"):
        n = n[:-6].strip()
    for suffix in (" university", " univ", " college"):
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
    return n.replace(" ", "")


def build_ncaam_team_normalization_key(value: str) -> str:
    """Key for team map / display name normalization (no alias; used for map rows)."""
    return _normalize_name(value or "").replace(" ", "")


# -----------------------------------------------------------------------------
# Date / time parsing (shared)
# -----------------------------------------------------------------------------

def parse_utc(ts: str) -> datetime | None:
    """Parse ISO UTC timestamp to naive datetime (strip tz for comparison)."""
    raw = (ts or "").strip()
    if not raw:
        return None
    try:
        odt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return odt.replace(tzinfo=None) if odt.tzinfo else odt
    except Exception:
        return None


def parse_date(s: str) -> datetime | None:
    """Parse game_date (YYYY-MM-DD) or commence_time (ISO) to naive datetime."""
    raw = (s or "").strip()
    if not raw:
        return None
    try:
        if len(raw) <= 10:
            return datetime.strptime(raw[:10], "%Y-%m-%d")
        s_clean = raw.replace("Z", "").replace("+00:00", "")[:19]
        return datetime.strptime(s_clean, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError:
            return None


def _game_day_to_dt(s: str) -> datetime | None:
    """Game day string YYYY-MM-DD -> midnight naive datetime."""
    s = (s or "").strip()[:10]
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


# -----------------------------------------------------------------------------
# Generic best market match (NBA + NCAAM)
# -----------------------------------------------------------------------------

def _window_nba(game_day_str: str, window_hours: int) -> tuple[datetime | None, datetime | None]:
    """Low/high naive datetimes for NBA: game_day midnight ± window_hours."""
    game_dt = _game_day_to_dt(game_day_str)
    if not game_dt:
        return None, None
    delta = timedelta(hours=window_hours)
    return game_dt - delta, game_dt + delta


def _window_ncaam(game_date_str: str, window_hours: int) -> tuple[datetime | None, datetime | None]:
    """
    Low/high naive datetimes for NCAAM so game_date (often local) matches
    commence_time (UTC). E.g. game tips 11 PM Monday local -> Tuesday early UTC.
    Window: game_date midnight UTC - 12h to game_date midnight UTC + 36h.
    """
    game_dt = _game_day_to_dt(game_date_str)
    if not game_dt:
        return None, None
    low = game_dt - timedelta(hours=12)
    high = game_dt + timedelta(hours=36)
    return low, high


def _get_market_commence_dt(row: dict, league: str) -> datetime | None:
    """Extract commence datetime from a market/odds row."""
    if league == "nba":
        raw = row.get("odds_commence_time_utc") or row.get("odds_commence_time_raw") or ""
        return parse_utc(raw)
    if league == "ncaam":
        raw = row.get("commence_time") or ""
        dt = parse_date(raw)
        if dt and dt.tzinfo:
            dt = dt.replace(tzinfo=None)
        return dt
    return None


def _teams_match(game: dict, market_row: dict, league: str) -> bool:
    if league == "nba":
        return (
            (game.get("home_team") or "").strip() == (market_row.get("home_team") or "").strip()
            and (game.get("away_team") or "").strip() == (market_row.get("away_team") or "").strip()
        )
    if league == "ncaam":
        return (
            (game.get("home_team_id") or "").strip() == (market_row.get("home_team_id") or "").strip()
            and (game.get("away_team_id") or "").strip() == (market_row.get("away_team_id") or "").strip()
        )
    return False


def _ncaam_row_has_odds(row: dict) -> bool:
    return any(
        row.get(col) not in (None, "")
        for col in ("spread_home", "spread_away", "market_total", "home_moneyline", "away_moneyline")
    )


def find_best_market_match(
    game: dict,
    market_rows: list[dict],
    league: str,
    window_hours: int = 24,
) -> dict | None:
    """
    Find the single best market row for this game: same teams and commence time
    within a league-appropriate window.

    - NBA: (home_team, away_team) exact, commence within ±window_hours of
      game's nba_game_day_local (midnight).
    - NCAAM: (home_team_id, away_team_id) exact, commence within
      [game_date UTC midnight - 12h, game_date UTC midnight + 36h] so that
      a game tipping 11 PM Monday local (early Tuesday UTC) matches game_date Monday.
    """
    league = (league or "").strip().lower()
    if league not in ("nba", "ncaam"):
        return None

    if league == "nba":
        home = (game.get("home_team") or "").strip()
        away = (game.get("away_team") or "").strip()
        game_day = (game.get("nba_game_day_local") or "").strip()[:10]
        if not home or not away or not game_day:
            return None
        low, high = _window_nba(game_day, window_hours)
    else:
        game_date_s = (game.get("game_date") or "").strip()[:10]
        home_id = (game.get("home_team_id") or "").strip()
        away_id = (game.get("away_team_id") or "").strip()
        if not game_date_s or not home_id or not away_id:
            return None
        low, high = _window_ncaam(game_date_s, window_hours)

    if low is None or high is None:
        return None

    best = None
    best_diff: float | None = None
    game_dt = _game_day_to_dt((game.get("nba_game_day_local") or game.get("game_date") or "").strip()[:10])

    for row in market_rows:
        if not _teams_match(game, row, league):
            continue
        if league == "ncaam" and not _ncaam_row_has_odds(row):
            continue
        comm = _get_market_commence_dt(row, league)
        if not comm:
            continue
        if comm.tzinfo:
            comm = comm.replace(tzinfo=None)
        if not (low <= comm <= high):
            continue
        ref = game_dt or comm
        diff = abs((comm - ref).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best = row
    return best
