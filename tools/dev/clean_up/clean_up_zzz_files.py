#!/usr/bin/env python3
"""
clean_up_zzz_files.py

Move any files/directories whose basename starts with zzz_ or ZZZ_
into legacy/root while preserving the original project-relative path.

Example:
    utils/zzz_temp.py
becomes:
    legacy/root/utils/zzz_temp.py

Recommended usage:
    python clean_up_zzz_files.py --dry-run
    python clean_up_zzz_files.py

Notes:
- Skips anything already under legacy/root
- Preserves relative schema under legacy/root
- Writes a move log CSV under legacy/root/_move_logs
- Handles name collisions by appending a timestamp suffix
"""

from __future__ import annotations

import argparse
import csv
import shutil
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import List


ZZZ_PREFIXES = ("zzz_", "ZZZ_")
DEFAULT_LEGACY_ROOT = Path("legacy") / "root"
MOVE_LOG_DIRNAME = "_move_logs"


@dataclass
class MoveItem:
    kind: str           # "file" or "dir"
    src: Path
    dst: Path
    collision: bool


def is_zzz_name(path: Path) -> bool:
    """Return True if the basename starts with zzz_ or ZZZ_."""
    return path.name.startswith(ZZZ_PREFIXES)


def is_under(path: Path, parent: Path) -> bool:
    """Return True if path is inside parent."""
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def unique_destination(dst: Path) -> tuple[Path, bool]:
    """
    If dst already exists, return a collision-safe destination by
    appending a timestamp suffix before the extension (files) or to the
    directory name (dirs).
    """
    if not dst.exists():
        return dst, False

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if dst.is_dir() or dst.suffix == "":
        candidate = dst.with_name(f"{dst.name}__moved_{ts}")
    else:
        candidate = dst.with_name(f"{dst.stem}__moved_{ts}{dst.suffix}")

    counter = 1
    while candidate.exists():
        if dst.is_dir() or dst.suffix == "":
            candidate = dst.with_name(f"{dst.name}__moved_{ts}_{counter}")
        else:
            candidate = dst.with_name(f"{dst.stem}__moved_{ts}_{counter}{dst.suffix}")
        counter += 1

    return candidate, True


def collect_items(repo_root: Path, legacy_root: Path) -> List[MoveItem]:
    """
    Collect zzz_* items to move.

    Strategy:
    - walk top-down
    - if a matching directory is found, collect the directory and prune it
      so children are not collected separately
    - collect matching files not inside already-collected zzz dirs
    """
    items: List[MoveItem] = []

    for current_root, dirnames, filenames in repo_root.walk(top_down=True):
        current_root = Path(current_root)

        # Never scan inside legacy/root
        if is_under(current_root, legacy_root):
            dirnames[:] = []
            continue

        # Prune .git and common virtual/cache dirs
        dirnames[:] = [
            d for d in dirnames
            if d not in {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache"}
        ]

        # Collect zzz_* directories and prune them
        matched_dirs = [d for d in dirnames if d.startswith(ZZZ_PREFIXES)]
        for d in matched_dirs:
            src = current_root / d
            rel = src.relative_to(repo_root)
            raw_dst = legacy_root / rel
            dst, collision = unique_destination(raw_dst)
            items.append(MoveItem(kind="dir", src=src, dst=dst, collision=collision))

        # Remove matched dirs from traversal so we don't also collect children
        dirnames[:] = [d for d in dirnames if d not in matched_dirs]

        # Collect zzz_* files
        for fname in filenames:
            if not fname.startswith(ZZZ_PREFIXES):
                continue
            src = current_root / fname
            rel = src.relative_to(repo_root)
            raw_dst = legacy_root / rel
            dst, collision = unique_destination(raw_dst)
            items.append(MoveItem(kind="file", src=src, dst=dst, collision=collision))

    # Move deeper paths first for files is not necessary, but for dirs it's clean to
    # move deepest first if there is any odd overlap.
    items.sort(key=lambda x: (x.kind != "dir", -len(x.src.parts), str(x.src)))
    return items


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_log(repo_root: Path, legacy_root: Path, items: List[MoveItem], dry_run: bool) -> Path:
    """
    Write a CSV log under legacy/root/_move_logs.
    """
    log_dir = legacy_root / MOVE_LOG_DIRNAME
    log_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "dry_run" if dry_run else "moved"
    log_path = log_dir / f"clean_up_zzz_files_{mode}_{ts}.csv"

    with log_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp_utc", "kind", "src", "dst", "collision_adjusted", "status"])
        now_utc = datetime.now(UTC).isoformat()
        for item in items:
            writer.writerow([
                now_utc,
                item.kind,
                item.src.relative_to(repo_root).as_posix(),
                item.dst.relative_to(repo_root).as_posix(),
                str(item.collision),
                "planned" if dry_run else "moved",
            ])

    return log_path


def execute_moves(items: List[MoveItem]) -> None:
    for item in items:
        ensure_parent(item.dst)
        shutil.move(str(item.src), str(item.dst))


def print_summary(repo_root: Path, items: List[MoveItem], dry_run: bool, log_path: Path) -> None:
    mode = "DRY RUN" if dry_run else "MOVE COMPLETE"
    print(f"\n=== {mode} ===")
    print(f"Items found: {len(items)}")

    dir_count = sum(1 for i in items if i.kind == "dir")
    file_count = sum(1 for i in items if i.kind == "file")
    collision_count = sum(1 for i in items if i.collision)

    print(f"Directories: {dir_count}")
    print(f"Files:       {file_count}")
    print(f"Collisions:  {collision_count}")
    print(f"Log:         {log_path.relative_to(repo_root).as_posix()}")

    if items:
        print("\nSample moves:")
        for item in items[:20]:
            src_rel = item.src.relative_to(repo_root).as_posix()
            dst_rel = item.dst.relative_to(repo_root).as_posix()
            suffix = " [collision-adjusted]" if item.collision else ""
            print(f" - {item.kind}: {src_rel} -> {dst_rel}{suffix}")
        if len(items) > 20:
            print(f" ... and {len(items) - 20} more")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Move zzz_/ZZZ_ files and directories into legacy/root while preserving relative schema."
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Path to repository root. Default: current directory",
    )
    parser.add_argument(
        "--legacy-root",
        default=str(DEFAULT_LEGACY_ROOT),
        help="Legacy root destination relative to repo root. Default: legacy/root",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show/log what would move without moving anything.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    repo_root = Path(args.repo_root).resolve()
    legacy_root = (repo_root / args.legacy_root).resolve()

    if not repo_root.exists():
        print(f"ERROR: repo root does not exist: {repo_root}")
        return 1

    legacy_root.mkdir(parents=True, exist_ok=True)

    items = collect_items(repo_root=repo_root, legacy_root=legacy_root)
    log_path = write_log(repo_root=repo_root, legacy_root=legacy_root, items=items, dry_run=args.dry_run)

    if not args.dry_run and items:
        execute_moves(items)

    print_summary(repo_root=repo_root, items=items, dry_run=args.dry_run, log_path=log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())