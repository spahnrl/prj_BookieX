"""
datetime_bridge.py

Authoritative calendar ↔ market alignment utilities.
DO NOT inline or duplicate this logic elsewhere.

All functions must be:
- deterministic
- explicit
- league-scoped
"""

from datetime import datetime
from zoneinfo import ZoneInfo

# -----------------------------
# League Timezones
# -----------------------------

LEAGUE_TIMEZONES = {
    "NBA": ZoneInfo("America/New_York"),
    # future:
    # "NCAAB": ZoneInfo("America/New_York"),
    # "NHL": ZoneInfo("America/New_York"),
}

# -----------------------------
# Public API
# -----------------------------

def derive_game_day_local(
    commence_time_utc: str,
    league: str,
) -> str:
    """
    Convert a UTC commence_time into a league-local calendar day.

    Parameters
    ----------
    commence_time_utc : str
        ISO-8601 UTC timestamp from market data
    league : str
        League code (e.g., 'NBA')

    Returns
    -------
    str
        YYYY-MM-DD league-local game day
    """

    if league not in LEAGUE_TIMEZONES:
        raise ValueError(f"Unsupported league: {league}")

    tz = LEAGUE_TIMEZONES[league]

    dt_utc = datetime.fromisoformat(
        commence_time_utc.replace("Z", "+00:00")
    )

    dt_local = dt_utc.astimezone(tz)

    return dt_local.date().isoformat()