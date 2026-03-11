#!/usr/bin/env python3
"""
Print the BookieX project directory tree with file count per directory (direct children only).
Root is the project directory that contains 'tools/'. Excludes .venv and optionally dot-prefixed dirs.
"""
from pathlib import Path
import argparse


def get_bookiex_root() -> Path:
    """Project root: directory containing 'tools/' (two levels up from this script)."""
    return Path(__file__).resolve().parent.parent.parent


def count_entries(
    dir_path: Path, exclude_dirs: set[str], exclude_dot: bool
) -> tuple[int, list[Path]]:
    """Return (file_count, sorted_list_of_subdirs). Skips excluded dirs."""
    try:
        entries = list(dir_path.iterdir())
    except PermissionError:
        return 0, []
    files = [e for e in entries if e.is_file()]
    dirs = [
        e
        for e in entries
        if e.is_dir()
        and e.name not in exclude_dirs
        and (not exclude_dot or not e.name.startswith("."))
    ]
    return len(files), sorted(dirs, key=lambda x: x.name.lower())


def walk(
    prefix: str, path: Path, root: Path, exclude_dirs: set[str], exclude_dot: bool
) -> None:
    nfiles, subdirs = count_entries(path, exclude_dirs, exclude_dot)
    if path == root:
        line = f".  ({nfiles} files)"
    else:
        line = f"{prefix}{path.name}/  ({nfiles} files)"
    print(line)
    for i, d in enumerate(subdirs):
        is_last = i == len(subdirs) - 1
        ext = "    " if is_last else "    "
        branch = "\\-- " if is_last else "+-- "
        walk(prefix + ext + branch, d, root, exclude_dirs, exclude_dot)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print BookieX project directory tree with file count per directory."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=None,
        type=Path,
        help="Override root (default: BookieX project root from script location)",
    )
    parser.add_argument(
        "--no-exclude-dot",
        action="store_true",
        help="Include dot-prefixed directories (default: exclude them)",
    )
    parser.add_argument(
        "--include-venv",
        action="store_true",
        help="Include .venv in the tree",
    )
    args = parser.parse_args()
    root = (args.root.resolve() if args.root is not None else get_bookiex_root())
    if not root.is_dir():
        print(f"Not a directory: {root}")
        return
    exclude_dirs = set() if args.include_venv else {".venv"}
    exclude_dot = not args.no_exclude_dot
    print("BookieX directory tree (file count per directory)")
    print(f"Root: {root}")
    if exclude_dirs:
        print(f"Excluded dirs: {exclude_dirs}")
    if exclude_dot:
        print("Excluding dot-prefixed directories.")
    print()
    walk("", root, root, exclude_dirs, exclude_dot)


if __name__ == "__main__":
    main()
