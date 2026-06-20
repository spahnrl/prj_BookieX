"""
d_gen_020_build_odds_only_canonical.py

Build minimal WNBA/NHL/MLB canonical game artifacts from flattened Odds API rows.
Schedule rows are used only as an optional match signal; odds-only games are kept.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils.io_helpers import get_schedule_raw_path
from utils.run_log import set_silent, log_info


SUPPORTED = ("wnba", "nhl", "mlb")


def _league_config(league: str):
    if league == "wnba":
        from configs.leagues import league_wnba as cfg
    elif league == "nhl":
        from configs.leagues import league_nhl as cfg
    elif league == "mlb":
        from configs.leagues import league_mlb as cfg
    else:
        raise ValueError(f"Unsupported league: {league!r}")
    return cfg


def _normalization_config_path(league: str) -> Path:
    names = {
        "wnba": "basketball_wnba.json",
        "nhl": "icehockey_nhl.json",
        "mlb": "baseball_mlb.json",
    }
    name = names[league]
    return _PROJECT_ROOT / "configs" / "normalization" / "leagues" / name


def _load_normalization_config(league: str) -> dict:
    path = _normalization_config_path(league)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_name(value: str) -> str:
    text = (value or "").strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def _key_from_name(name: str, used: set[str]) -> str:
    tokens = [t for t in _normalize_name(name).split() if t]
    if not tokens:
        base = "UNK"
    elif len(tokens) == 1:
        base = tokens[0][:3].upper()
    else:
        base = "".join(t[0] for t in tokens[:3]).upper()
    key = base or "UNK"
    i = 2
    while key in used:
        key = f"{base}{i}"
        i += 1
    return key


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fieldnames or (list(rows[0].keys()) if rows else [])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        if rows:
            w.writerows(rows)


def _load_schedule_rows(league: str) -> list[dict]:
    path = get_schedule_raw_path(league)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _load_flat_odds(league: str) -> list[dict]:
    cfg = _league_config(league)
    path = cfg.BETLINES_FLATTENED_CSV_PATH
    rows = _read_csv(path)
    if not rows:
        raise FileNotFoundError(f"Missing or empty flattened odds CSV: {path}")
    return rows


def _collect_team_names(odds_rows: list[dict], schedule_rows: list[dict]) -> set[str]:
    names: set[str] = set()
    for row in odds_rows:
        for key in ("home_team", "away_team"):
            v = (row.get(key) or "").strip()
            if v:
                names.add(v)
    for row in schedule_rows:
        for key in ("home_team_raw", "away_team_raw"):
            v = (row.get(key) or "").strip()
            if v:
                names.add(v)
    return names


def _build_team_map(league: str, odds_rows: list[dict], schedule_rows: list[dict]) -> tuple[list[dict], dict[str, str], list[dict]]:
    config = _load_normalization_config(league)
    mappings = config.get("team_mappings") or {}
    aliases = {str(k).strip(): str(v).strip() for k, v in (mappings.get("aliases") or {}).items()}
    configured_keys = {str(k).strip(): str(v).strip() for k, v in (mappings.get("keys") or {}).items()}
    used = {v for v in configured_keys.values() if v}
    names = sorted(_collect_team_names(odds_rows, schedule_rows))

    rows: list[dict] = []
    name_to_key: dict[str, str] = {}
    unmatched: list[dict] = []

    canonical_to_aliases: dict[str, list[str]] = defaultdict(list)
    for raw, canonical in aliases.items():
        canonical_to_aliases[canonical].append(raw)

    for name in names:
        canonical = aliases.get(name, name)
        team_key = configured_keys.get(canonical) or configured_keys.get(name)
        source = "normalization_config"
        if not team_key:
            team_key = _key_from_name(canonical, used)
            used.add(team_key)
            source = "generated_from_real_team_name"
            unmatched.append({
                "team_name": name,
                "canonical_name": canonical,
                "generated_team_key": team_key,
                "reason": "missing from normalization config keys",
            })
        alias_values = sorted(set(canonical_to_aliases.get(canonical, []) + ([name] if name != canonical else [])))
        row = {
            "team_key": team_key,
            "team_name": canonical,
            "normalized_name": _normalize_name(canonical),
            "aliases": ";".join(alias_values),
            "source_system": source,
        }
        rows.append(row)
        for label in {name, canonical, *alias_values}:
            name_to_key[_normalize_name(label)] = team_key

    rows.sort(key=lambda r: (r["team_name"], r["team_key"]))
    return rows, name_to_key, unmatched


def _parse_dt(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _schedule_match(odds_group: list[dict], schedule_rows: list[dict]) -> bool:
    if not schedule_rows or not odds_group:
        return False
    sample = odds_group[0]
    home = _normalize_name(sample.get("home_team") or "")
    away = _normalize_name(sample.get("away_team") or "")
    comm = _parse_dt(sample.get("commence_time") or "")
    if not home or not away or comm is None:
        return False
    low = comm - timedelta(hours=24)
    high = comm + timedelta(hours=24)
    for row in schedule_rows:
        if _normalize_name(row.get("home_team_raw") or "") != home:
            continue
        if _normalize_name(row.get("away_team_raw") or "") != away:
            continue
        sched_dt = _parse_dt(row.get("game_time_utc") or "")
        if sched_dt is None:
            continue
        if low <= sched_dt <= high:
            return True
    return False


def _build_canonical_rows(league: str, odds_rows: list[dict], schedule_rows: list[dict], name_to_key: dict[str, str]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in odds_rows:
        gid = (row.get("game_id") or "").strip()
        if gid:
            grouped[gid].append(row)

    out: list[dict] = []
    for game_id, rows in sorted(grouped.items(), key=lambda x: ((x[1][0].get("commence_time") or ""), x[0])):
        sample = rows[0]
        commence = (sample.get("commence_time") or "").strip()
        markets = {r.get("market_key") for r in rows if r.get("market_key")}
        books = {r.get("bookmaker_key") for r in rows if r.get("bookmaker_key")}
        home = (sample.get("home_team") or "").strip()
        away = (sample.get("away_team") or "").strip()
        out.append({
            "league": league,
            "game_id": game_id,
            "game_date": commence[:10],
            "commence_time": commence,
            "home_team": home,
            "away_team": away,
            "home_team_key": name_to_key.get(_normalize_name(home), ""),
            "away_team_key": name_to_key.get(_normalize_name(away), ""),
            "status": "",
            "completed": "0",
            "source_system": "odds_api_flattened",
            "has_schedule_match": str(_schedule_match(rows, schedule_rows)).lower(),
            "odds_event_count": str(len(rows)),
            "bookmaker_count": str(len(books)),
            "market_count": str(len(markets)),
            "has_h2h": str("h2h" in markets).lower(),
            "has_spreads": str("spreads" in markets).lower(),
            "has_totals": str("totals" in markets).lower(),
        })
    return out


def _write_join_audit(league: str, canonical_rows: list[dict]) -> None:
    cfg = _league_config(league)
    path = cfg.INTERIM_DIR / f"{league}_schedule_odds_join_audit.csv"
    rows = [
        {
            "game_id": r["game_id"],
            "commence_time": r["commence_time"],
            "away_team": r["away_team"],
            "home_team": r["home_team"],
            "has_schedule_match": r["has_schedule_match"],
        }
        for r in canonical_rows
    ]
    _write_csv(path, rows, ["game_id", "commence_time", "away_team", "home_team", "has_schedule_match"])


def run(league: str) -> None:
    league = (league or "").strip().lower()
    if league not in SUPPORTED:
        raise ValueError(f"Unsupported league: {league!r}. Use one of: {', '.join(SUPPORTED)}")
    cfg = _league_config(league)
    cfg.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    cfg.INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    cfg.CANONICAL_DIR.mkdir(parents=True, exist_ok=True)

    odds_rows = _load_flat_odds(league)
    schedule_rows = _load_schedule_rows(league)
    team_rows, name_to_key, unmatched = _build_team_map(league, odds_rows, schedule_rows)

    team_map_path = cfg.TEAM_MAP_PATH
    _write_csv(team_map_path, team_rows, ["team_key", "team_name", "normalized_name", "aliases", "source_system"])

    unmatched_path = cfg.INTERIM_DIR / f"{league}_unmatched_teams.csv"
    _write_csv(unmatched_path, unmatched, ["team_name", "canonical_name", "generated_team_key", "reason"])

    canonical_rows = _build_canonical_rows(league, odds_rows, schedule_rows, name_to_key)
    if not canonical_rows:
        raise ValueError(f"No canonical rows produced for {league}")

    blank_keys = [
        r for r in canonical_rows
        if not (r.get("home_team_key") or "").strip() or not (r.get("away_team_key") or "").strip()
    ]
    if blank_keys:
        raise ValueError(f"{league.upper()} canonical rows have blank team keys: {len(blank_keys)}")

    _write_csv(cfg.CANONICAL_GAMES_PATH, canonical_rows)
    if cfg.CANONICAL_JSON_PATH:
        cfg.CANONICAL_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg.CANONICAL_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(canonical_rows, f, indent=2)

    _write_join_audit(league, canonical_rows)

    schedule_matched = sum(1 for r in canonical_rows if r.get("has_schedule_match") == "true")
    log_info(f"{league.upper()} team map -> {team_map_path} ({len(team_rows)} teams)")
    log_info(f"{league.upper()} unmatched team audit -> {unmatched_path} ({len(unmatched)} generated keys)")
    log_info(f"{league.upper()} canonical CSV -> {cfg.CANONICAL_GAMES_PATH}")
    log_info(f"{league.upper()} canonical JSON -> {cfg.CANONICAL_JSON_PATH}")
    log_info(f"{league.upper()} canonical rows: {len(canonical_rows)}; schedule matched: {schedule_matched}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build odds-only canonical games for WNBA/NHL/MLB")
    parser.add_argument("--league", required=True, choices=list(SUPPORTED))
    parser.add_argument("--silent", action="store_true", help="Only print critical errors")
    args = parser.parse_args()
    set_silent(args.silent)
    run(args.league)


if __name__ == "__main__":
    main()
