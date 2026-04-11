#!/usr/bin/env python3
"""Custom git merge driver for .pearls/issues.jsonl.

Understands the JSONL issue schema and auto-resolves conflicts when changes
are compatible (e.g., independent estimate appends, dep additions, one-side
scalar changes).

Git merge driver interface:
    merge-driver.py %O %A %B
    - %O = base (ancestor)
    - %A = ours (also where result is written)
    - %B = theirs
    - Exit 0 on success, non-zero on unresolvable conflict.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from prl import Issue


# ── Array field identity keys ────────────────────────────────────────────────

ARRAY_FIELDS = ("estimates", "deps", "references")


def estimate_key(e: dict[str, Any]) -> tuple[str, str]:
    """Identity key for an estimate: (estimator, implementer)."""
    return (e["estimator"], e["implementer"])


def dep_key(d: dict[str, Any]) -> tuple[str, str]:
    """Identity key for a dependency: (id, type)."""
    return (d["id"], d["type"])


def ref_subsumes(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True if reference `a` subsumes `b`.

    A subsumes B when every field in B exists in A with the same value,
    and A has at least one additional field.
    """
    if len(a) <= len(b):
        return False
    return all(a.get(k) == v for k, v in b.items())


# ── I/O ──────────────────────────────────────────────────────────────────────

def read_jsonl(path: Path) -> list[Issue]:
    """Read a JSONL file into a list of dicts."""
    issues: list[Issue] = []
    if not path.exists():
        return issues
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                issues.append(json.loads(line))
    return issues


def write_jsonl(path: Path, issues: list[Issue]) -> None:
    """Write issues to a JSONL file (compact JSON, matching prl.py format)."""
    with open(path, "w") as f:
        for issue in issues:
            f.write(json.dumps(issue, separators=(",", ":")) + "\n")


# ── Three-way merge logic ───────────────────────────────────────────────────

def merge_estimates(base: list[Any], ours: list[Any], theirs: list[Any]) -> list[Any] | None:
    """Merge estimate arrays. Returns merged list or None on conflict."""
    base_by_key = {estimate_key(e): e for e in base}
    ours_by_key = {estimate_key(e): e for e in ours}
    theirs_by_key = {estimate_key(e): e for e in theirs}

    all_keys = list(base_by_key.keys())
    for k in ours_by_key:
        if k not in base_by_key:
            all_keys.append(k)
    for k in theirs_by_key:
        if k not in base_by_key and k not in ours_by_key:
            all_keys.append(k)

    merged = []
    for key in all_keys:
        in_base = key in base_by_key
        in_ours = key in ours_by_key
        in_theirs = key in theirs_by_key

        if in_base and not in_ours and not in_theirs:
            # Both sides removed — omit
            continue
        if in_base and not in_ours:
            # Ours removed — omit
            continue
        if in_base and not in_theirs:
            # Theirs removed — omit
            continue

        if in_ours and in_theirs:
            # Both have it — check if cost values match
            if ours_by_key[key] != theirs_by_key[key]:
                # Same key, different cost — conflict
                return None
            merged.append(ours_by_key[key])
        elif in_ours:
            merged.append(ours_by_key[key])
        elif in_theirs:
            merged.append(theirs_by_key[key])

    return merged


def merge_deps(base: list[Any], ours: list[Any], theirs: list[Any]) -> list[Any] | None:
    """Merge dep arrays via three-way set diff. Returns merged list or None."""
    base_set = {dep_key(d): d for d in base}
    ours_set = {dep_key(d): d for d in ours}
    theirs_set = {dep_key(d): d for d in theirs}

    # Compute diffs from base
    ours_added = {k for k in ours_set if k not in base_set}
    ours_removed = {k for k in base_set if k not in ours_set}
    theirs_added = {k for k in theirs_set if k not in base_set}
    theirs_removed = {k for k in base_set if k not in theirs_set}

    # Conflict: one side adds, other removes same dep
    if (ours_added & theirs_removed) or (theirs_added & ours_removed):
        return None

    # Start from base, apply both diffs
    result_keys = set(base_set.keys())
    result_keys -= ours_removed
    result_keys -= theirs_removed
    result_keys |= ours_added
    result_keys |= theirs_added

    # Build merged list preserving order: base items first, then ours adds, then theirs adds
    merged = []
    seen = set()

    # Base items that survived
    for d in base:
        k = dep_key(d)
        if k in result_keys and k not in seen:
            merged.append(d)
            seen.add(k)

    # Ours additions (in ours order)
    for d in ours:
        k = dep_key(d)
        if k in ours_added and k not in seen:
            merged.append(d)
            seen.add(k)

    # Theirs additions (in theirs order)
    for d in theirs:
        k = dep_key(d)
        if k in theirs_added and k not in seen:
            merged.append(d)
            seen.add(k)

    return merged


def apply_specificity(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove references that are subsumed by more-specific ones."""
    result = []
    for i, ref in enumerate(refs):
        subsumed = False
        for j, other in enumerate(refs):
            if i != j and ref_subsumes(other, ref):
                subsumed = True
                break
        if not subsumed:
            result.append(ref)
    return result


def merge_references(base: list[Any], ours: list[Any], theirs: list[Any]) -> list[Any] | None:
    """Merge reference arrays with specificity subsumption."""
    def ref_to_tuple(r: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
        # Convert lists to tuples for hashability
        return tuple(
            (k, tuple(v) if isinstance(v, list) else v)
            for k, v in sorted(r.items())
        )

    def tuple_to_dict(t: tuple[tuple[str, Any], ...]) -> dict[str, Any]:
        return {k: list(v) if isinstance(v, tuple) else v for k, v in t}

    base_tuples = {ref_to_tuple(r) for r in base}
    ours_tuples = {ref_to_tuple(r) for r in ours}
    theirs_tuples = {ref_to_tuple(r) for r in theirs}

    # Three-way set diff
    ours_added = ours_tuples - base_tuples
    ours_removed = base_tuples - ours_tuples
    theirs_added = theirs_tuples - base_tuples
    theirs_removed = base_tuples - theirs_tuples

    # Conflict: one side adds, other removes same exact ref
    if (ours_added & theirs_removed) or (theirs_added & ours_removed):
        return None

    # Build union result
    result_tuples = (base_tuples - ours_removed - theirs_removed) | ours_added | theirs_added

    # Convert to dicts and apply specificity subsumption
    all_refs = apply_specificity([tuple_to_dict(t) for t in result_tuples])
    surviving = {ref_to_tuple(r) for r in all_refs}

    # Stable ordering: base survivors, then ours additions, then theirs additions
    merged = []
    seen = set()

    for source in (base, ours, theirs):
        for r in source:
            t = ref_to_tuple(r)
            if t in surviving and t not in seen:
                merged.append(r)
                seen.add(t)

    return merged


def merge_issue(base: Issue, ours: Issue, theirs: Issue) -> Issue | None:
    """Three-way merge of a single issue. Returns merged dict or None on conflict."""
    merged: dict[str, Any] = {}

    # Collect all keys across all three versions
    all_keys = list(base.keys())
    for k in ours:
        if k not in base:
            all_keys.append(k)
    for k in theirs:
        if k not in base and k not in ours:
            all_keys.append(k)

    for key in all_keys:
        base_val: Any = base.get(key)
        ours_val: Any = ours.get(key)
        theirs_val: Any = theirs.get(key)

        if key in ARRAY_FIELDS:
            # Array field — use specialized merge
            b: list[Any] = base_val if base_val is not None else []
            o: list[Any] = ours_val if ours_val is not None else []
            t: list[Any] = theirs_val if theirs_val is not None else []

            if key == "estimates":
                result = merge_estimates(b, o, t)
            elif key == "deps":
                result = merge_deps(b, o, t)
            elif key == "references":
                result = merge_references(b, o, t)
            else:
                result = None

            if result is None:
                return None
            if result:  # Only include non-empty arrays
                merged[key] = result
        else:
            # Scalar field — three-way merge
            if ours_val == theirs_val:
                # Both sides agree (or both unchanged) — use either
                if ours_val is not None:
                    merged[key] = ours_val
            elif ours_val == base_val:
                # Only theirs changed — take theirs
                if theirs_val is not None:
                    merged[key] = theirs_val
            elif theirs_val == base_val:
                # Only ours changed — take ours
                if ours_val is not None:
                    merged[key] = ours_val
            else:
                # Both sides changed to different values — conflict
                return None

    return cast("Issue", merged)


def merge_jsonl(base_path: Path, ours_path: Path, theirs_path: Path) -> bool:
    """Three-way merge of JSONL issue files.

    Writes merged result to ours_path.
    Returns True on success, False on unresolvable conflict.
    """
    base_issues = read_jsonl(base_path)
    ours_issues = read_jsonl(ours_path)
    theirs_issues = read_jsonl(theirs_path)

    base_by_id = {i["id"]: i for i in base_issues}
    ours_by_id = {i["id"]: i for i in ours_issues}
    theirs_by_id = {i["id"]: i for i in theirs_issues}

    # Determine ordering: base order first, then new issues in ours order, then theirs order
    ordered_ids = []
    seen = set()

    for issue in base_issues:
        ordered_ids.append(issue["id"])
        seen.add(issue["id"])

    for issue in ours_issues:
        if issue["id"] not in seen:
            ordered_ids.append(issue["id"])
            seen.add(issue["id"])

    for issue in theirs_issues:
        if issue["id"] not in seen:
            ordered_ids.append(issue["id"])
            seen.add(issue["id"])

    merged = []
    for issue_id in ordered_ids:
        in_base = issue_id in base_by_id
        in_ours = issue_id in ours_by_id
        in_theirs = issue_id in theirs_by_id

        if in_base and not in_ours and not in_theirs:
            # Both sides deleted — omit
            continue
        if in_base and not in_ours:
            # Ours deleted, theirs unchanged or also modified
            if theirs_by_id[issue_id] == base_by_id[issue_id]:
                # Theirs unchanged — honor ours deletion
                continue
            else:
                # Theirs modified something ours deleted — conflict
                return False
        if in_base and not in_theirs:
            # Theirs deleted, ours unchanged or also modified
            if ours_by_id[issue_id] == base_by_id[issue_id]:
                # Ours unchanged — honor theirs deletion
                continue
            else:
                # Ours modified something theirs deleted — conflict
                return False

        if not in_base:
            # New issue — include from whichever side has it (or both if same)
            if in_ours and in_theirs:
                if ours_by_id[issue_id] == theirs_by_id[issue_id]:
                    merged.append(ours_by_id[issue_id])
                else:
                    # Both sides created same ID with different content — conflict
                    return False
            elif in_ours:
                merged.append(ours_by_id[issue_id])
            else:
                merged.append(theirs_by_id[issue_id])
            continue

        # Issue exists in all three — check for changes
        base_issue = base_by_id[issue_id]
        ours_issue = ours_by_id[issue_id]
        theirs_issue = theirs_by_id[issue_id]

        if ours_issue == theirs_issue:
            # Identical changes — use either
            merged.append(ours_issue)
            continue

        if ours_issue == base_issue:
            # Only theirs changed — take theirs
            merged.append(theirs_issue)
            continue

        if theirs_issue == base_issue:
            # Only ours changed — take ours
            merged.append(ours_issue)
            continue

        # Both sides changed — attempt field-level merge
        result = merge_issue(base_issue, ours_issue, theirs_issue)
        if result is None:
            return False
        merged.append(result)

    write_jsonl(ours_path, merged)
    return True


def main() -> int:
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <base> <ours> <theirs>", file=sys.stderr)
        return 1

    base_path = Path(sys.argv[1])
    ours_path = Path(sys.argv[2])
    theirs_path = Path(sys.argv[3])

    if merge_jsonl(base_path, ours_path, theirs_path):
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
