"""
utils/run_log.py

Centralized audit logging and silent mode for _gen_ scripts.

- When --silent: only critical errors go to stdout; all other messages go to logs/audit.log.
- When not silent: info/debug also go to stdout and are appended to logs/audit.log.
- Critical errors always go to both stdout and audit.log.

Usage in scripts:
  from utils.run_log import set_silent, log_info, log_debug, log_error
  parser.add_argument("--silent", action="store_true", help="Only print critical errors")
  args = parser.parse_args()
  set_silent(getattr(args, "silent", False))
  log_info("Writing X games...")   # stdout + file unless silent
  log_debug("Path = ...")           # file only (or stdout+file when not silent - treat as info)
  log_error("Failed to open file")  # always stdout + file
"""

from pathlib import Path
from datetime import datetime, timezone

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_LOG_DIR = _PROJECT_ROOT / "logs"
_AUDIT_LOG = _LOG_DIR / "audit.log"
_silent = False


def set_silent(flag: bool) -> None:
    global _silent
    _silent = flag


def _ensure_log_dir() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _write_audit(level: str, msg: str) -> None:
    _ensure_log_dir()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} [{level}] {msg}\n"
    with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(line)


def log_info(msg: str) -> None:
    """Info: audit.log always; stdout only when not silent."""
    _write_audit("INFO", msg)
    if not _silent:
        print(msg)


def log_debug(msg: str) -> None:
    """Debug/detail: audit.log always; stdout only when not silent (same as info for visibility)."""
    _write_audit("DEBUG", msg)
    if not _silent:
        print(msg)


def log_error(msg: str) -> None:
    """Critical error: always stdout and audit.log."""
    _write_audit("ERROR", msg)
    print(msg)
