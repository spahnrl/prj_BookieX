"""
xxx_ncaam_slate_match_report.py

NCAAM slate diagnostics in a chosen timezone (default America/Chicago):

  • Full ESPN schedule rows (003 mapped CSV) for a date window around the slate.
  • Schedule rows that are partial / unmatched / missing a team id.
  • Unresolved diagnostics JSON (named_unresolved / tbd) in that window.
  • Canonical + lines (041): unmatched line_join in that window.
  • Odds API flat (latest): distinct events whose commence falls on a local date
    in the window, plus a coarse odds↔schedule pairing diff.

Edit CONFIG below for defaults; CLI overrides CONFIG.

Usage (from project root):
  python tools/diagnostics/xxx_ncaam_slate_match_report.py
  python tools/diagnostics/xxx_ncaam_slate_match_report.py --date 2026-03-22
  python tools/diagnostics/xxx_ncaam_slate_match_report.py --date 2026-03-22 --window-days 1
  python tools/diagnostics/xxx_ncaam_slate_match_report.py --no-full-schedule
  python tools/diagnostics/xxx_ncaam_slate_match_report.py --no-odds-flat

Read-only; does not modify pipeline artifacts.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# =============================================================================
# CONFIG — change these instead of typing CLI every time (CLI overrides when set)
# =============================================================================
SLATE_DATE: str | None = None  # None = today in SLATE_TIMEZONE
SLATE_TIMEZONE: str = "America/Chicago"
# Include center date ± WINDOW_DAYS (e.g. 1 => three calendar days).
WINDOW_DAYS: int = 1
# Print every schedule row in the window (ESPN raw + mapped ids + status).
FULL_SCHEDULE_DEFAULT: bool = True


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _resolve_target_date(explicit: str | None, tz_name: str) -> str:
    if explicit and len(explicit.strip()) >= 10:
        return explicit.strip()[:10]
    z = ZoneInfo(tz_name)
    return datetime.now(z).date().isoformat()


def _window_dates(center_iso: str, window_days: int) -> set[str]:
    c = datetime.strptime(center_iso[:10], "%Y-%m-%d").date()
    out: set[str] = set()
    for d in range(-window_days, window_days + 1):
        out.add((c + timedelta(days=d)).isoformat())
    return out


def _norm_game_date(cell: str) -> str:
    s = (cell or "").strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s[:10] if len(s) >= 10 else s, fmt).date().isoformat()
        except ValueError:
            continue
    return s[:10] if s else ""


def _commence_to_local_date(iso: str | None, tz_name: str) -> str | None:
    if not (iso or "").strip():
        return None
    raw = iso.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(ZoneInfo(tz_name)).date().isoformat()
    except Exception:
        return None


def _cst_field_date(cst_iso: str | None) -> str | None:
    s = (cst_iso or "").strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


def _fold(s: str) -> str:
    return (s or "").strip().casefold()


def _alnum_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _fold(s))


def _pair_sigs(home: str, away: str) -> tuple[tuple[str, str], tuple[str, str]]:
    hf, af = _fold(home), _fold(away)
    ordered = (hf, af)
    unordered = tuple(sorted((hf, af)))
    return ordered, unordered


def report_schedule_full(dates: set[str]) -> None:
    path = PROJECT_ROOT / "data" / "ncaam" / "interim" / "ncaam_schedule_mapped.csv"
    print("\n" + "=" * 72)
    print("FULL SCHEDULE (b_gen_003) — all rows with game_date in window")
    print(f"  dates: {', '.join(sorted(dates))}")
    print(f"  file: {path}")
    print("=" * 72)
    if not path.exists():
        print("  (missing file)\n")
        return

    rows_out: list[dict[str, str]] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            gd = _norm_game_date(row.get("game_date") or "")
            if gd in dates:
                rows_out.append(row)

    rows_out.sort(key=lambda r: (_norm_game_date(r.get("game_date") or ""), r.get("espn_game_id") or r.get("game_id") or ""))

    if not rows_out:
        print("  (no rows in this file for those dates)\n")
        return

    print(
        f"\n  {'game_date':<12} {'espn_id':<12} {'mapping':<10} "
        f"{'home_raw -> id':<42} {'away_raw -> id':<42} game_time_utc"
    )
    print("  " + "-" * 140)
    for row in rows_out:
        gid = row.get("espn_game_id") or row.get("game_id") or ""
        gd = _norm_game_date(row.get("game_date") or "")
        ms = (row.get("mapping_status") or "").strip()
        hr = (row.get("home_team_raw") or "")[:38]
        ar = (row.get("away_team_raw") or "")[:38]
        hi = (row.get("home_team_id") or "")[:12]
        ai = (row.get("away_team_id") or "")[:12]
        gt = (row.get("game_time_utc") or "")[:19]
        hcol = f"{hr} -> {hi or '∅'}"
        acol = f"{ar} -> {ai or '∅'}"
        print(f"  {gd:<12} {str(gid):<12} {ms:<10} {hcol:<42} {acol:<42} {gt}")
    print(f"\n  Total rows in window: {len(rows_out)}\n")


def report_schedule_problems(dates: set[str]) -> None:
    path = PROJECT_ROOT / "data" / "ncaam" / "interim" / "ncaam_schedule_mapped.csv"
    print("\n" + "=" * 72)
    print("SCHEDULE JOIN ISSUES ONLY — partial / unmatched / missing team_id")
    print(f"  dates: {', '.join(sorted(dates))}")
    print(f"  file: {path}")
    print("=" * 72)
    if not path.exists():
        print("  (missing file)\n")
        return

    bad: list[dict[str, str]] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            gd = _norm_game_date(row.get("game_date") or "")
            if gd not in dates:
                continue
            hid = (row.get("home_team_id") or "").strip()
            aid = (row.get("away_team_id") or "").strip()
            ms = (row.get("mapping_status") or "").strip().lower()
            if ms in ("partial", "unmatched") or not hid or not aid:
                bad.append(row)

    if not bad:
        print("  None in this window.\n")
        return

    for row in bad:
        gid = row.get("espn_game_id") or row.get("game_id") or ""
        print(f"\n  game_id: {gid} | game_date: {row.get('game_date')}")
        print(f"  mapping_status: {row.get('mapping_status')}")
        print(f"  home_raw: {row.get('home_team_raw')} | home_id: {row.get('home_team_id')!r} | src: {row.get('home_lookup_source')}")
        print(f"  away_raw: {row.get('away_team_raw')} | away_id: {row.get('away_team_id')!r} | src: {row.get('away_lookup_source')}")
        print(f"  event_name: {row.get('event_name')}")


def report_unresolved_json(dates: set[str]) -> None:
    path = PROJECT_ROOT / "data" / "ncaam" / "interim" / "ncaam_schedule_unresolved_diagnostics.json"
    print("\n" + "=" * 72)
    print("UNRESOLVED DIAGNOSTICS (003) — game_date in window")
    print(f"  dates: {', '.join(sorted(dates))}")
    print(f"  file: {path}")
    print("=" * 72)
    if not path.exists():
        print("  (missing file — run b_gen_003)\n")
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for key in ("named_unresolved_rows", "tbd_rows"):
        rows = data.get(key) or []
        hit = [r for r in rows if _norm_game_date(r.get("game_date") or "") in dates]
        if not hit:
            print(f"  {key}: (none in window)")
            continue
        print(f"\n  --- {key} ({len(hit)}) ---")
        for r in hit:
            print(f"\n    game_id: {r.get('game_id')}")
            print(f"    game_date: {r.get('game_date')}")
            print(f"    home_raw: {r.get('home_team_raw')}")
            print(f"    away_raw: {r.get('away_team_raw')}")
            print(f"    exclusion_class: {r.get('exclusion_class')}")


def report_with_lines(dates: set[str], tz_name: str) -> None:
    path = PROJECT_ROOT / "data" / "ncaam" / "model" / "ncaam_canonical_games_with_lines.csv"
    print("\n" + "=" * 72)
    print("ODDS JOIN (f_gen_041) — line_join_status == unmatched, window filter")
    print(f"  dates ({tz_name} / ESPN game_date): {', '.join(sorted(dates))}")
    print(f"  include if game_date in window OR commence local date in window")
    print(f"  file: {path}")
    print("=" * 72)
    if not path.exists():
        print("  (missing file)\n")
        return

    bad: list[dict[str, str]] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("line_join_status") or "").strip().lower() != "unmatched":
                continue
            gd = _norm_game_date(row.get("game_date") or "")
            comm_utc = row.get("odds_commence_time_utc") or ""
            comm_cst_field = row.get("odds_commence_time_cst") or ""
            d_comm = _cst_field_date(comm_cst_field) or _commence_to_local_date(comm_utc, tz_name)
            if gd in dates or (d_comm is not None and d_comm in dates):
                bad.append(row)

    if not bad:
        print("  None in this window.\n")
        return

    for row in bad:
        cid = row.get("canonical_game_id") or ""
        print(f"\n  {cid}")
        print(f"    game_date: {row.get('game_date')}")
        print(f"    status: {row.get('status_name')} | mapping: {row.get('mapping_status')}")
        print(f"    home: {row.get('home_team_display')} ({row.get('home_team_id')})")
        print(f"    away: {row.get('away_team_display')} ({row.get('away_team_id')})")
        print(f"    odds_commence_utc: {row.get('odds_commence_time_utc')}")
        print(f"    odds_commence_cst: {row.get('odds_commence_time_cst')}")
        print(f"    line_join_method: {row.get('line_join_method')}")


def _load_odds_distinct_events(path: Path, dates: set[str], tz_name: str) -> list[dict[str, str]]:
    """One record per Odds-API game_id (first row wins for home/away/commence)."""
    by_key: dict[str, dict[str, str]] = {}
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            oid = (row.get("game_id") or "").strip()
            if not oid:
                continue
            if oid in by_key:
                continue
            comm = (row.get("commence_time") or "").strip()
            ld = _commence_to_local_date(comm, tz_name)
            if ld not in dates:
                continue
            by_key[oid] = {
                "odds_game_id": oid,
                "commence_time": comm,
                "commence_local_date": ld or "",
                "home_team": row.get("home_team") or "",
                "away_team": row.get("away_team") or "",
            }
    out = list(by_key.values())
    out.sort(key=lambda r: (r["commence_local_date"], r["home_team"], r["away_team"]))
    return out


def report_odds_flat_and_diff(dates: set[str], tz_name: str) -> None:
    flat_path = PROJECT_ROOT / "data" / "ncaam" / "market" / "flat" / "ncaam_odds_flat_latest.csv"
    sched_path = PROJECT_ROOT / "data" / "ncaam" / "interim" / "ncaam_schedule_mapped.csv"

    print("\n" + "=" * 72)
    print("ODDS FLAT (latest) — distinct events with commence local date in window")
    print(f"  dates ({tz_name}): {', '.join(sorted(dates))}")
    print(f"  file: {flat_path}")
    print("=" * 72)

    events = _load_odds_distinct_events(flat_path, dates, tz_name)
    if not events:
        print("  (no events or missing file)\n")
    else:
        print(f"\n  {'local_date':<12} {'odds_game_id':<34} {'home (book)':<36} {'away (book)':<36} commence_utc")
        print("  " + "-" * 130)
        for e in events:
            cu = (e.get("commence_time") or "")[:22]
            print(
                f"  {e.get('commence_local_date',''):<12} {e.get('odds_game_id',''):<34} "
                f"{(e.get('home_team') or '')[:34]:<36} {(e.get('away_team') or '')[:34]:<36} {cu}"
            )
        print(f"\n  Distinct odds events in window: {len(events)}\n")

    if not sched_path.exists():
        print("(skip diff: schedule mapped missing)\n")
        return

    schedule_pairs: list[tuple[str, str, str, str, str]] = []
    with open(sched_path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            gd = _norm_game_date(row.get("game_date") or "")
            if gd not in dates:
                continue
            hr = row.get("home_team_raw") or ""
            ar = row.get("away_team_raw") or ""
            eid = row.get("espn_game_id") or row.get("game_id") or ""
            schedule_pairs.append((gd, eid, hr, ar, _norm_game_date(row.get("game_date") or "")))

    sched_unordered: set[tuple[str, str]] = set()
    for _gd, _eid, hr, ar, _ in schedule_pairs:
        _, uns = _pair_sigs(hr, ar)
        sched_unordered.add(uns)

    def _odds_matches_schedule(ev: dict[str, str]) -> bool:
        oh, oa = ev.get("home_team") or "", ev.get("away_team") or ""
        _, uns_o = _pair_sigs(oh, oa)
        if uns_o in sched_unordered:
            return True
        ko = (_alnum_key(oh), _alnum_key(oa))
        krev = (ko[1], ko[0])
        for _gd, _eid, hr, ar, __ in schedule_pairs:
            ks = (_alnum_key(hr), _alnum_key(ar))
            if ko == ks or krev == ks:
                return True
        for _gd, _eid, hr, ar, __ in schedule_pairs:
            hr_f, ar_f = _fold(hr), _fold(ar)
            ho_f, ao_f = _fold(oh), _fold(oa)
            if (ho_f in hr_f or hr_f in ho_f) and (ao_f in ar_f or ar_f in ao_f):
                return True
            if (ho_f in ar_f or ar_f in ho_f) and (ao_f in hr_f or hr_f in ao_f):
                return True
        return False

    odds_orphans = [e for e in events if not _odds_matches_schedule(e)]

    sched_no_odds: list[tuple[str, str, str, str]] = []
    for gd, eid, hr, ar, _ in schedule_pairs:
        matched = False
        for e in events:
            oh, oa = e.get("home_team") or "", e.get("away_team") or ""
            _, uns_o = _pair_sigs(oh, oa)
            _, uns_s = _pair_sigs(hr, ar)
            if uns_o == uns_s:
                matched = True
                break
            ko = (_alnum_key(oh), _alnum_key(oa))
            krev = (ko[1], ko[0])
            ks = (_alnum_key(hr), _alnum_key(ar))
            if ko == ks or krev == ks:
                matched = True
                break
        if not matched:
            sched_no_odds.append((gd, eid, hr, ar))

    print("\n" + "=" * 72)
    print("COARSE DIFF — book names vs ESPN raw (same window; heuristic, not join logic)")
    print("=" * 72)

    print(f"\n  Odds events with no heuristic schedule match ({len(odds_orphans)}):")
    if not odds_orphans:
        print("    (none)")
    else:
        for e in odds_orphans:
            print(
                f"    {e.get('commence_local_date')} | {e.get('home_team')} vs {e.get('away_team')} | "
                f"id={e.get('odds_game_id')}"
            )

    print(f"\n  Schedule rows with no heuristic odds-flat match ({len(sched_no_odds)}):")
    if not sched_no_odds:
        print("    (none)")
    else:
        for gd, eid, hr, ar in sched_no_odds:
            print(f"    {gd} | espn={eid} | {hr} vs {ar}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NCAAM schedule + odds diagnostics with optional ±day window.",
    )
    parser.add_argument("--date", type=str, default=None, help="Center slate YYYY-MM-DD")
    parser.add_argument("--tz", type=str, default=None, help=f"IANA tz (default CONFIG: {SLATE_TIMEZONE})")
    parser.add_argument(
        "--window-days",
        type=int,
        default=None,
        help=f"Include center ± N calendar days (default CONFIG: {WINDOW_DAYS})",
    )
    parser.add_argument(
        "--no-full-schedule",
        action="store_true",
        help="Skip printing the full schedule listing",
    )
    parser.add_argument(
        "--no-odds-flat",
        action="store_true",
        help="Skip odds-flat events + heuristic diff",
    )
    args = parser.parse_args()

    tz = (args.tz or SLATE_TIMEZONE).strip()
    w = args.window_days if args.window_days is not None else WINDOW_DAYS
    explicit_date = args.date if args.date else SLATE_DATE
    center = _resolve_target_date(explicit_date, tz)
    dates = _window_dates(center, max(0, w))
    full_sched = FULL_SCHEDULE_DEFAULT and not args.no_full_schedule

    print(f"Project root:      {PROJECT_ROOT}")
    print(f"Center slate date: {center}")
    print(f"Date window:       {', '.join(sorted(dates))}  (±{w} day(s))")
    print(f"Timezone:          {tz}")

    if full_sched:
        report_schedule_full(dates)
    report_schedule_problems(dates)
    report_unresolved_json(dates)
    report_with_lines(dates, tz)
    if not args.no_odds_flat:
        report_odds_flat_and_diff(dates, tz)

    print("=" * 72)
    print("Done.")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()