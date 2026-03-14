import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


DEFAULT_SPORT = "basketball"
DEFAULT_LEAGUE = "mens-college-basketball"
DEFAULT_TIMEOUT = 20


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def fetch_json(session: requests.Session, url: str, timeout: int) -> Tuple[int, Optional[Any], str]:
    try:
        resp = session.get(url, timeout=timeout)
        status = resp.status_code
        text = resp.text
        try:
            data = resp.json()
        except Exception:
            data = None
        return status, data, text
    except Exception as exc:
        return -1, None, f"{type(exc).__name__}: {exc}"


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pull ESPN endpoint data for one event/game id and save all successful payloads."
    )
    parser.add_argument(
        "--game-id",
        required=True,
        help="ESPN event/game id, e.g. 401851567",
    )
    parser.add_argument(
        "--sport",
        default=DEFAULT_SPORT,
        help=f"ESPN sport path segment (default: {DEFAULT_SPORT})",
    )
    parser.add_argument(
        "--league",
        default=DEFAULT_LEAGUE,
        help=f"ESPN league path segment (default: {DEFAULT_LEAGUE})",
    )
    parser.add_argument(
        "--date",
        default="",
        help="Optional YYYYMMDD date for scoreboard endpoint, if you want to inspect the event on a specific scoreboard date.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP timeout seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--out-dir",
        default="",
        help="Optional output directory. Default: tools/diagnostics/espn_event_dumps/<game_id>_<timestamp>",
    )
    return parser.parse_args()


def build_endpoint_catalog(game_id: str, sport: str, league: str, date_yyyymmdd: str) -> List[Dict[str, str]]:
    base_site = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}"
    base_core = f"https://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}"
    base_cdn = f"https://cdn.espn.com/core/{sport}/{league}"

    endpoints: List[Dict[str, str]] = [
        {
            "name": "site_summary",
            "url": f"{base_site}/summary?event={game_id}",
            "note": "Best all-in-one site summary payload.",
        },
        {
            "name": "site_gamecast",
            "url": f"{base_site}/gamecast?event={game_id}",
            "note": "Gamecast payload, if available.",
        },
        {
            "name": "site_playbyplay",
            "url": f"{base_site}/playbyplay?event={game_id}",
            "note": "Play-by-play payload, if available.",
        },
        {
            "name": "site_boxscore",
            "url": f"{base_site}/boxscore?event={game_id}",
            "note": "Boxscore payload, if available.",
        },
        {
            "name": "site_event",
            "url": f"{base_site}/events/{game_id}",
            "note": "Single event object from site api.",
        },
        {
            "name": "core_event_ref",
            "url": f"{base_core}/events/{game_id}",
            "note": "Core API event ref object, often contains links to child resources.",
        },
        {
            "name": "cdn_game",
            "url": f"{base_cdn}/game?gameId={game_id}",
            "note": "CDN game object, if available for this league.",
        },
        {
            "name": "cdn_boxscore",
            "url": f"{base_cdn}/boxscore?gameId={game_id}",
            "note": "CDN boxscore object, if available for this league.",
        },
    ]

    if date_yyyymmdd:
        endpoints.append(
            {
                "name": "site_scoreboard_for_date",
                "url": f"{base_site}/scoreboard?dates={date_yyyymmdd}&groups=50&limit=1000",
                "note": "Scoreboard payload for the supplied date so you can verify event presence there.",
            }
        )

    return endpoints


def print_header(args: argparse.Namespace, out_dir: Path) -> None:
    print("=" * 100)
    print("ESPN EVENT ENDPOINT CHECK")
    print("=" * 100)
    print(f"Game ID   : {args.game_id}")
    print(f"Sport     : {args.sport}")
    print(f"League    : {args.league}")
    print(f"Date arg  : {args.date or '-'}")
    print(f"Output dir: {out_dir}")
    print("=" * 100)


def summarize_summary_payload(payload: Dict[str, Any]) -> None:
    header = payload.get("header") or {}
    competitions = payload.get("competitions") or []
    comp = competitions[0] if competitions else {}

    print("\nSUMMARY SNAPSHOT")
    print("-" * 100)
    print(f"Header shortName : {header.get('shortName')}")
    print(f"Header state     : {header.get('competitions', [{}])[0].get('status', {}).get('type', {}).get('state') if header.get('competitions') else None}")
    print(f"Date             : {comp.get('date')}")
    print(f"Venue            : {(comp.get('venue') or {}).get('fullName')}")
    competitors = comp.get("competitors") or []
    for idx, team in enumerate(competitors, start=1):
        t = team.get("team") or {}
        print(
            f"Competitor {idx}: "
            f"homeAway={team.get('homeAway')} "
            f"id={t.get('id')} "
            f"displayName={t.get('displayName')} "
            f"score={team.get('score')}"
        )


def main() -> int:
    args = parse_args()

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        out_dir = Path("tools") / "diagnostics" / "espn_event_dumps" / f"{safe_filename(args.game_id)}_{timestamp}"
    ensure_dir(out_dir)

    print_header(args, out_dir)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ESPN Endpoint Checker",
            "Accept": "application/json,text/plain,*/*",
        }
    )

    endpoints = build_endpoint_catalog(
        game_id=args.game_id,
        sport=args.sport,
        league=args.league,
        date_yyyymmdd=args.date,
    )

    results: List[Dict[str, Any]] = []

    for item in endpoints:
        name = item["name"]
        url = item["url"]
        note = item["note"]

        status, data, raw_text = fetch_json(session, url, timeout=args.timeout)

        result = {
            "name": name,
            "url": url,
            "note": note,
            "status_code": status,
            "json_ok": data is not None,
        }
        results.append(result)

        print(f"[{name}] status={status} json_ok={data is not None}")
        print(f"  url : {url}")
        print(f"  note: {note}")

        if data is not None:
            write_json(out_dir / f"{name}.json", data)
        else:
            with (out_dir / f"{name}.txt").open("w", encoding="utf-8") as f:
                f.write(raw_text)

    summary_manifest = {
        "game_id": args.game_id,
        "sport": args.sport,
        "league": args.league,
        "date_arg": args.date,
        "generated_utc": datetime.utcnow().isoformat() + "Z",
        "results": results,
    }
    write_json(out_dir / "manifest.json", summary_manifest)

    # Try to summarize the main summary payload if present.
    summary_path = out_dir / "site_summary.json"
    if summary_path.exists():
        try:
            with summary_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                summarize_summary_payload(payload)
        except Exception as exc:
            print(f"\nCould not summarize site_summary.json: {exc}")

    print("\nDONE")
    print("-" * 100)
    print(f"Manifest written: {out_dir / 'manifest.json'}")
    print(f"Payload directory: {out_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())