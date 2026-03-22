"""
utils/mapping_helpers.py

Shared odds ↔ game mapping: ±window fuzzy date match and team normalization.
Used by f_gen_041 (NBA and NCAAM) for joining market rows to games.

NCAAM name alignment (single workflow)
--------------------------------------
1. **Editable overrides (preferred for new fixes):**
   ``data/ncaam/static/ncaam_match_overrides.csv``

   **How matching works (one substitution table, two feeds):** ``b_gen_003`` and
   ``f_gen_041`` both replace ``raw_name`` with ``maps_to`` *before* team-map
   lookup. So ``raw_name`` must be the **exact** string you see in the broken
   place (copy-paste). ``maps_to`` is **not** "from Odds or ESPN" — it is the
   **replacement text** that should then resolve via ``ncaam_team_map.csv``
   (often you copy ESPN wording or a ``team_display`` cell from the map).

   **Columns (loader uses only ``raw_name`` + ``maps_to``; rest is for you):**

   - ``raw_source`` — where you copied ``raw_name`` from: ``odds`` (flat/API),
     ``schedule`` (ESPN scoreboard / ``ncaam_schedule_mapped`` raw columns),
     or ``both`` if the same spelling appears on both sides and one row is enough.
   - ``raw_name`` — exact label to rewrite.
   - ``maps_to_basis`` — what you used to type ``maps_to``: ``espn`` (scoreboard
     string), ``team_map`` (``team_display`` / map row), or ``other``.
   - ``maps_to`` — the substitute string.
   - ``notes`` — freeform.

   If Odds says "A" and ESPN says "B" and only **A** fails to map, one row
   ``raw_name=A``, ``maps_to=B`` (or team_map wording) is enough. If **both**
   strings are wrong vs the map, use **two rows** (same ``maps_to``, two
   ``raw_name`` values) or fix ``ncaam_team_map.csv``.

   Rows in the CSV **override** the same ``raw_name`` key in ``NCAAM_ALIAS_BASE``.

2. **Shipped defaults:** ``NCAAM_ALIAS_BASE`` (merged into ``NCAAM_ALIAS_MAP`` at import).

3. **Team universe:** ``ncaam_team_map.csv`` — add schools / norm_keys when the school
   is missing entirely (overrides only rename; they do not create new team_ids).

b_gen_003 and f_gen_041 both consult the merged ``NCAAM_ALIAS_MAP`` so one CSV update
propagates after you re-run schedule join and betting-lines steps.

**Optional fuzzy tier (off by default):** set environment variable
``BOOKIEX_NCAAM_FUZZY_MATCH=1`` to allow a second-pass token overlap match when
the strict norm_key contains logic finds nothing. Requires at least two
significant tokens (length ≥ 4, not stopwords like *state* / *st* alone) to
appear as substrings of the candidate map norm_key, at least one token not in a
generic-mascot list, the same state-school semantics filter as 003/041, and a
**unique** top score (no ties). Mis-joins are still possible for common words;
prefer CSV overrides for recurring cases.
"""

import csv
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_NCAAM_MATCH_OVERRIDES_CSV = _PROJECT_ROOT / "data" / "ncaam" / "static" / "ncaam_match_overrides.csv"


def _load_ncaam_match_overrides_csv() -> dict[str, str]:
    """Load raw_name -> maps_to from CSV; skip blanks and #-prefixed raw_name.

    Optional columns raw_source, maps_to_basis, notes are ignored by the loader
    (documentation for operators).
    """
    path = _NCAAM_MATCH_OVERRIDES_CSV
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return {}
            for row in reader:
                raw = (row.get("raw_name") or "").strip()
                maps_to = (row.get("maps_to") or "").strip()
                if not raw or raw.startswith("#") or not maps_to:
                    continue
                out[raw] = maps_to
    except OSError:
        return {}
    return out


# -----------------------------------------------------------------------------
# NCAAM alias defaults (merged with CSV overrides → NCAAM_ALIAS_MAP)
# -----------------------------------------------------------------------------

NCAAM_ALIAS_BASE = {
    "Ole Miss": "Mississippi",
    "NC State": "North Carolina State",
    "UConn": "Connecticut",
    "UNC": "North Carolina",
    "Penn St": "Pennsylvania State",
    # Odds/schedule raw -> canonical display for join (diagnostic 2026-03)
    "IUPUI Jaguars": "Indiana",  # IU Indianapolis
    "Queens University Royals": "Queens (NC)",  # Queens (Charlotte); do not map to UNI
    # ESPN scoreboard display variants (mascot/campus qualifier) -> team-map display
    # so schedule rows resolve via substring contains rules in b_gen_003.
    "Saint Mary's Gaels": "Saint Mary's (CA)",
    # 003 resolution hardening: ESPN display names -> map-friendly (team_map norm_key)
    "Southern Jaguars": "Southern U.",
    "Arkansas-Pine Bluff Golden Lions": "Ark.-Pine Bluff",
    "Western Kentucky Hilltoppers": "Western Ky.",
    "Kennesaw State Owls": "Kennesaw St.",
    "California Baptist": "California Baptist",
    "CBU Lancers": "California Baptist",
    "Cal Baptist Lancers": "California Baptist",
    "California Baptist Lancers": "California Baptist",
    # Book vs ESPN wording fixes: prefer data/ncaam/static/ncaam_match_overrides.csv
}

NCAAM_ALIAS_MAP = {**NCAAM_ALIAS_BASE, **_load_ncaam_match_overrides_csv()}


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
# NCAAM fuzzy name resolution (optional; env-gated)
# -----------------------------------------------------------------------------

_NCAAM_FUZZY_TOKEN_STOP = frozenset({
    "state",
    "st",
    "the",
    "of",
    "at",
    "and",
    "a",
    "an",
    "college",
    "university",
    "univ",
    "tech",
    "national",
    "ncaa",
})

# If *every* matched token is in this set, reject (mascot-only collisions).
_NCAAM_FUZZY_GENERIC_MASCOTS = frozenset({
    "wildcats", "tigers", "bulldogs", "eagles", "bears", "lions", "panthers", "cougars",
    "cardinals", "knights", "raiders", "warriors", "crimson", "longhorns", "sooners",
    "hoosiers", "terrapins", "jayhawks", "bluejays", "huskies", "cowboys", "mountaineers",
    "spartans", "badgers", "boilermakers", "hawkeyes", "gophers", "scarlet", "gray",
    "orange", "blue", "gold", "green", "red", "black", "white", "devils", "saints",
    "dukes", "tar", "heels", "vols", "aggies", "utes", "lobos", "frogs",
})


def ncaam_fuzzy_match_enabled() -> bool:
    return os.environ.get("BOOKIEX_NCAAM_FUZZY_MATCH", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _ncaam_state_school_semantics(norm_key: str) -> bool:
    """Match b_gen_003 / f_gen_041: treat some keys as 'State' schools for pairing."""
    v = (norm_key or "").strip().lower()
    return v.endswith("state") or v.endswith("st") or ("state" in v)


def _ncaam_fuzzy_token_list(raw_name: str) -> list[str]:
    """Spaced, normalized tokens; drop short and stopwords (state/st excluded from scoring)."""
    parts = _normalize_name(raw_name).split()
    out: list[str] = []
    for t in parts:
        if len(t) < 4:
            continue
        if t in _NCAAM_FUZZY_TOKEN_STOP:
            continue
        out.append(t)
    return out


def ncaam_fuzzy_resolve_team(raw_name: str, team_lookup: list[dict]) -> dict | None:
    """
    Last-resort resolver: score candidates by how many raw tokens appear as substrings
    of team_name_norm_key. Requires a unique winner and at least two matching tokens,
    with at least one non-generic token match. Respects the same state-school filter
    as strict resolution.
    """
    if not raw_name or not team_lookup:
        return None
    tokens = _ncaam_fuzzy_token_list(raw_name)
    if len(tokens) < 2:
        return None

    raw_norm = build_ncaam_team_normalization_key(raw_name)
    if not raw_norm:
        return None
    raw_state = _ncaam_state_school_semantics(raw_norm)

    scored: list[tuple[int, dict]] = []
    for cand in team_lookup:
        map_norm_key = (cand.get("team_name_norm_key") or "").strip().lower()
        if not map_norm_key:
            continue
        if _ncaam_state_school_semantics(map_norm_key) != raw_state:
            continue
        matched = [t for t in tokens if t in map_norm_key]
        if len(matched) < 2:
            continue
        non_generic = [t for t in matched if t not in _NCAAM_FUZZY_GENERIC_MASCOTS]
        if not non_generic:
            continue
        scored.append((len(matched), cand))

    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], (x[1].get("team_name_norm_key") or "")))
    best_score, best_cand = scored[0]
    if best_score < 2:
        return None
    if len(scored) > 1 and scored[1][0] == best_score:
        return None

    out = dict(best_cand)
    out["lookup_source"] = "ncaam_team_map_fuzzy_tokens"
    return out


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


def _ncaam_row_completeness_score(row: dict) -> tuple[int, int, int]:
    """
    Prefer more complete odds coverage when multiple rows match a game.

    Score is lexicographically compared:
    - spread coverage (home+away) first
    - then total
    - then moneyline coverage
    """
    def _present(v: Any) -> bool:
        return v not in (None, "")

    spread_score = int(_present(row.get("spread_home"))) + int(_present(row.get("spread_away")))
    total_score = int(_present(row.get("market_total")))
    moneyline_score = int(_present(row.get("home_moneyline"))) + int(_present(row.get("away_moneyline")))
    return (spread_score, total_score, moneyline_score)


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
        game_date_s = (game.get("slate_date_cst") or game.get("game_date") or "").strip()[:10]
        home_id = (game.get("home_team_id") or "").strip()
        away_id = (game.get("away_team_id") or "").strip()
        if not game_date_s or not home_id or not away_id:
            return None
        low, high = _window_ncaam(game_date_s, window_hours)

    if low is None or high is None:
        return None

    best = None
    best_diff: float | None = None
    game_dt = _game_day_to_dt((game.get("slate_date_cst") or game.get("nba_game_day_local") or game.get("game_date") or "").strip()[:10])

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
        elif league == "ncaam" and best_diff is not None and diff == best_diff:
            # Tie-break: when time closeness is equal, prefer rows with spreads populated.
            if _ncaam_row_completeness_score(row) > _ncaam_row_completeness_score(best):
                best = row
    return best
