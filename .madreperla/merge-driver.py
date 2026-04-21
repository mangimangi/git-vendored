#!/usr/bin/env python3
"""Append-only JSONL merge driver for .madreperla/sessions.jsonl.

Git merge driver interface:
    merge-driver.py %O %A %B
    - %O = base (ancestor)
    - %A = ours (also where result is written)
    - %B = theirs
    - Exit 0 on success, non-zero on conflict.

Strategy: keep all unique lines from both sides, ordered by the line's
JSON ``created_at`` field (falls back to insertion order).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _read_lines(path: Path) -> list[str]:
    """Read non-empty lines from a JSONL file."""
    if not path.exists():
        return []
    return [ln for ln in path.read_text().splitlines() if ln.strip()]


def _line_id(line: str) -> str:
    """Extract a stable identity key from a JSONL line."""
    try:
        obj = json.loads(line)
        if "id" in obj:
            return str(obj["id"])
    except (json.JSONDecodeError, TypeError):
        pass
    return line


def _sort_key(line: str) -> str:
    """Sort key: created_at timestamp, or empty string as fallback."""
    try:
        return str(json.loads(line).get("created_at", ""))
    except (json.JSONDecodeError, TypeError):
        return ""


def merge(base_path: Path, ours_path: Path, theirs_path: Path) -> int:
    """Three-way append-only merge. Result is written to *ours_path*."""
    ours_lines = _read_lines(ours_path)
    theirs_lines = _read_lines(theirs_path)

    seen: set[str] = set()
    merged: list[str] = []

    for line in ours_lines:
        lid = _line_id(line)
        if lid not in seen:
            seen.add(lid)
            merged.append(line)

    for line in theirs_lines:
        lid = _line_id(line)
        if lid not in seen:
            seen.add(lid)
            merged.append(line)

    merged.sort(key=_sort_key)

    ours_path.write_text("\n".join(merged) + "\n" if merged else "")
    return 0


def main() -> int:
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <base> <ours> <theirs>", file=sys.stderr)
        return 1
    return merge(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))


if __name__ == "__main__":
    sys.exit(main())
