#!/usr/bin/env python3
"""prl (pearls) — lightweight, AI-native issue tracker.

Tracks issues in your git repo with zero dependencies. Designed for AI agent workflows.
Issues stored in .pearls/issues.jsonl (JSONL, no database, git-versioned).

Commands:
    prl create --title="..." [--type=task] [--priority=2] [--parent=<id>]
    prl edit <id> [--title=...] [--body=...] [--priority=N] [--type=...]
    prl list [--status=open] [--type=task] [--implementer=...] [--parent=<id>]
    prl show <id>
    prl start <id>
    prl estimate <id> -e <model> -m <model> -i <tokens> -o <tokens>
    prl close <id>
    prl dep add <id> <other-id> [--type=blocks]
    prl dep remove <id> <other-id> [--type=blocks]
    prl dep list <id> [--type=...]
    prl ref add <id> [--commit=SHA] [--file=PATH] [--lines=L1,L2]
    prl ref list <id>
    prl ref remove <id> --index=N
    prl link <id> <other-id>           # relates_to (bidirectional)
    prl dup <id> <duplicate-id>        # mark duplicate + close
    prl ready
    prl version

Dependency types:
    blocks/blocked_by  - Hard dependency (filters prl ready)
    precedes/follows   - Soft ordering (warning in prl ready)
    relates_to         - Bidirectional loose link
    duplicates/duplicated_by - Same work (auto-closes duplicate)
    implements/implemented_by - Realization link
    causes/caused_by   - Causal chain

ID scheme (prefix from .vendored/configs/pearls.json, required):
    Top-level:  {prefix}-a3f8          (random 4-char hex, merge-safe)
    Child:      {prefix}-a3f8.1        (sequential under parent)
    Subtask:    {prefix}-a3f8.1.1      (sequential under child)
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict, NotRequired, cast

VERSION = "0.2.39"

# ── Type aliases ─────────────────────────────────────────────────────────────

Status = Literal["open", "in_progress", "implemented", "closed"]
IssueType = Literal["task", "bug", "feature", "chore", "epic"]

# ── TypedDict definitions ───────────────────────────────────────────────────

class Cost(TypedDict):
    input: int
    output: int


class Dep(TypedDict):
    id: str
    type: str


class Reference(TypedDict, total=False):
    file: str
    lines: list[str]
    commit: str


class Estimate(TypedDict):
    estimator: str
    implementer: str
    cost: Cost
    estimator_cost: NotRequired[Cost]


class Evaluation(TypedDict):
    evaluator: str
    evaluated_at: str
    scores: dict[str, int]
    score: float
    cost: NotRequired[Cost]


class Issue(TypedDict):
    id: str
    title: str
    status: Status
    issue_type: IssueType
    priority: int
    created_at: str
    parent: NotRequired[str]
    body: NotRequired[str]
    labels: NotRequired[list[str]]
    deps: NotRequired[list[Dep]]
    references: NotRequired[list[Reference]]
    estimates: NotRequired[list[Estimate]]
    evaluation: NotRequired[Evaluation]
    implementer: NotRequired[str]
    cost: NotRequired[Cost]
    commit: NotRequired[str]
    started_at: NotRequired[str]
    implemented_at: NotRequired[str]
    closed_at: NotRequired[str]
    created_by: NotRequired[str]
    started_by: NotRequired[str]
    closed_by: NotRequired[str]
    children: NotRequired[list[str]]
    merge_commit: NotRequired[str]
    archived_at: NotRequired[str]
    close_message: NotRequired[str]


class EpicEntry(TypedDict):
    slug: str
    alias: NotRequired[str]
    title: NotRequired[str]
    body: NotRequired[str]


class Config(TypedDict):
    prefix: str
    epics: NotRequired[list[str | EpicEntry]]
    install: NotRequired[dict[str, object]]
    eval: NotRequired[dict[str, Any]]
    sessions: NotRequired[dict[str, Any]]

VALID_STATUSES = ["open", "in_progress", "implemented", "closed"]
VALID_TYPES = ["task", "bug", "feature", "chore", "epic"]
VALID_MODELS = [
    "claude-sonnet-4-5-20250514",
    "claude-opus-4-5-20251101",
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
    "claude-opus-4-6",
]

# Dependency type definitions with their inverses
DEP_TYPES = {
    "blocks": "blocked_by",
    "blocked_by": "blocks",
    "precedes": "follows",
    "follows": "precedes",
    "relates_to": "relates_to",  # symmetric
    "duplicates": "duplicated_by",
    "duplicated_by": "duplicates",
    "implements": "implemented_by",
    "implemented_by": "implements",
    "causes": "caused_by",
    "caused_by": "causes",
}

# Types that affect prl ready (hard blocking)
BLOCKING_TYPES = {"blocked_by"}

# Types that show warnings in prl ready (soft ordering)
SOFT_ORDER_TYPES = {"follows"}

STATUS_ICONS = {"open": "○", "in_progress": "◐", "implemented": "◑", "closed": "●"}

CONFIG_PATH = ".vendored/configs/pearls.json"


def find_pearls_dir() -> Path:
    """Find the .pearls directory.

    Handles both dogfood layout (.pearls/prl.py) and vendored layout
    (.vendored/pkg/pearls/prl.py).
    """
    script_dir = Path(__file__).parent

    # Dogfood: prl.py in .pearls/ — parent is repo root
    repo_root = script_dir.parent
    pearls_path = repo_root / ".pearls"
    if pearls_path.is_dir():
        return pearls_path

    # Vendored: prl.py in .vendored/pkg/pearls/ — 3 levels up
    vendored_root = script_dir.parent.parent.parent
    pearls_path = vendored_root / ".pearls"
    if pearls_path.is_dir():
        return pearls_path

    # CWD fallback
    cwd_path = Path.cwd() / ".pearls"
    if cwd_path.is_dir():
        return cwd_path

    raise FileNotFoundError(
        "Could not find .pearls/ directory. "
        "Run from repository root or .pearls/ directory."
    )


def find_issues_file() -> Path:
    """Find the issues.jsonl file, creating if needed."""
    pearls_dir = find_pearls_dir()
    issues_path = pearls_dir / "issues.jsonl"
    if not issues_path.exists():
        issues_path.touch()
    return issues_path


def _config_path() -> Path:
    """Resolve config path from vendored configs."""
    return find_pearls_dir().parent / CONFIG_PATH


def load_prefix() -> str:
    """Load ID prefix from config. Tries vendored path first, legacy fallback."""
    config_path = _config_path()
    if not config_path.exists():
        print(
            f"Error: config not found at {config_path}.\n"
            'Create .vendored/configs/pearls.json with: {"prefix": "your-project"}',
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        with open(config_path, "r") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: {config_path} is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    prefix: str | None = raw.get("prefix")
    if not prefix:
        print(
            f'Error: "prefix" key missing or empty in {config_path}.',
            file=sys.stderr,
        )
        sys.exit(1)
    return str(prefix)


def load_config() -> Config:
    """Load full config. Tries vendored path first, legacy fallback.

    Returns Config with keys:
        - prefix (str, required): Issue ID prefix
        - epics (list[str | EpicEntry], optional): First-class epic slugs or
          objects with slug/alias/title/body (e.g. ["1shots", {"slug": "enhncmnts", "title": "Enhancements"}])
        - install (dict[str, object], optional): Install behavior overrides
        - eval (dict, optional): Eval config (e.g. {"threshold": 80})
        - sessions (dict, optional): Session config per mode (model, max_turns)
    """
    config_path = _config_path()
    if not config_path.exists():
        print(
            f"Error: config not found at {config_path}.\n"
            'Create .vendored/configs/pearls.json with: {"prefix": "your-project"}',
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        with open(config_path, "r") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: {config_path} is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    prefix = raw.get("prefix")
    if not prefix:
        print(
            f'Error: "prefix" key missing or empty in {config_path}.',
            file=sys.stderr,
        )
        sys.exit(1)
    return cast(Config, raw)


# Hardcoded session defaults per mode
_SESSION_DEFAULTS: dict[str, dict[str, Any]] = {
    "planning":  {"model": "claude-opus-4-6", "max_turns": 25},
    "refine":    {"model": "claude-opus-4-6", "max_turns": 30},
    "estimate":  {"model": "claude-opus-4-6", "max_turns": 15},
    "implement": {"model": "claude-opus-4-6", "max_turns": 50},
    "oneshot":   {"model": "claude-opus-4-6", "max_turns": 50},
    "eval":      {"model": "claude-opus-4-6", "max_turns": 20},
    "cleanup":   {"model": "claude-opus-4-6", "max_turns": 15},
}


def resolve_session(config: Config, mode: str) -> dict[str, Any]:
    """Resolve session config for a prompt mode.

    Resolution: sessions.<mode>.<field> → sessions.default.<field> → hardcoded fallback.
    """
    hardcoded = _SESSION_DEFAULTS.get(mode, {"model": "claude-opus-4-6", "max_turns": 25})
    sessions = config.get("sessions", {})
    default = sessions.get("default", {})
    mode_config = sessions.get(mode, {})

    return {
        "model": mode_config.get("model", default.get("model", hardcoded["model"])),
        "max_turns": mode_config.get("max_turns", default.get("max_turns", hardcoded["max_turns"])),
    }


def get_epic_slugs(config: Config) -> list[str]:
    """Extract epic slugs from config, handling both string and object entries.

    Epics can be specified as:
        - String: "1shots" (slug only)
        - Object: {"slug": "1shots", "alias": "1shot", "title": "...", "body": "..."}
    """
    epics = config.get("epics", [])
    slugs = []
    for entry in epics:
        if isinstance(entry, str):
            slugs.append(entry)
        elif isinstance(entry, dict):
            slug = entry.get("slug", "")
            if slug:
                slugs.append(slug)
    return slugs


def get_epic_entry(config: Config, slug_or_alias: str) -> EpicEntry | None:
    """Look up an epic entry by slug or alias. Returns the entry dict or None.

    For string entries, returns {"slug": <string>}.
    For object entries, returns the full dict.
    """
    epics = config.get("epics", [])
    for entry in epics:
        if isinstance(entry, str):
            if entry == slug_or_alias:
                return {"slug": entry}
        elif isinstance(entry, dict):
            if entry.get("slug") == slug_or_alias or entry.get("alias") == slug_or_alias:
                return entry
    return None


def is_first_class_epic(issue_id: str) -> bool:
    """Check if an issue ID corresponds to a first-class epic from config.

    First-class epics are listed in config.json under the "epics" key as slugs
    (e.g. ["1shots", "enhncmnts"]). Their direct children get hash-based IDs
    to prevent collisions across parallel sessions.
    """
    config = load_config()
    prefix = config.get("prefix", "")
    slugs = get_epic_slugs(config)
    return issue_id in {f"{prefix}-{slug}" for slug in slugs}


def read_issues(issues_path: Path) -> list[Issue]:
    """Read all issues from the JSONL file."""
    issues: list[Issue] = []
    if not issues_path.exists():
        return issues
    with open(issues_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    issues.append(cast(Issue, json.loads(line)))
                except json.JSONDecodeError as e:
                    print(f"Error: {issues_path} line {line_num}: invalid JSON: {e}",
                          file=sys.stderr)
                    sys.exit(1)
    return issues


def write_issues(issues_path: Path, issues: list[Issue]) -> None:
    """Write all issues back to the JSONL file."""
    with open(issues_path, "w") as f:
        for issue in issues:
            f.write(json.dumps(issue, separators=(",", ":")) + "\n")


# ── ID Generation ────────────────────────────────────────────────────────────


def generate_id(issues: list[Issue]) -> str:
    """Generate a unique top-level ID with a random 4-char hex hash.

    Format: {prefix}-a3f8 (65536 possibilities, collision-checked).
    Hash-based IDs prevent merge conflicts across parallel branches.
    """
    prefix = load_prefix()
    existing = {i.get("id", "") for i in issues}
    for _ in range(100):
        h = secrets.token_hex(2)
        candidate = f"{prefix}-{h}"
        if candidate not in existing:
            return candidate
    raise RuntimeError("Could not generate unique ID after 100 attempts")


def next_child_id(issues: list[Issue], parent_id: str, use_hash: bool = False) -> str:
    """Generate the next child ID under a parent.

    When use_hash=True (first-class epic children), generates a random 4-char
    hex hash to prevent merge conflicts across parallel sessions:
        {prefix}-1shots → {prefix}-1shots.a3f8, {prefix}-1shots.b2c1

    When use_hash=False (default), generates sequential integers:
        {prefix}-a3f8   → {prefix}-a3f8.1, {prefix}-a3f8.2
        {prefix}-a3f8.1 → {prefix}-a3f8.1.1, {prefix}-a3f8.1.2
    """
    existing = {i.get("id", "") for i in issues}

    if use_hash:
        for _ in range(100):
            h = secrets.token_hex(2)
            candidate = f"{parent_id}.{h}"
            if candidate not in existing:
                return candidate
        raise RuntimeError("Could not generate unique child ID after 100 attempts")

    prefix = f"{parent_id}."
    max_num = 0
    for eid in existing:
        if eid.startswith(prefix):
            suffix = eid[len(prefix):]
            if "." not in suffix:
                try:
                    max_num = max(max_num, int(suffix))
                except ValueError:
                    pass
    return f"{parent_id}.{max_num + 1}"


def id_depth(issues: list[Issue], issue_id: str) -> int:
    """Return nesting depth by walking the parent chain.

    Top-level issues (no parent) have depth 0.
    Issues whose parent is an epic have depth 1, etc.
    """
    depth = 0
    current_id = issue_id
    seen = set()
    while True:
        if current_id in seen:
            break  # prevent infinite loop on circular parents
        seen.add(current_id)
        issue = find_issue(issues, current_id)
        if not issue or "parent" not in issue:
            break
        depth += 1
        current_id = issue["parent"]
    return depth


def find_issue(issues: list[Issue], issue_id: str) -> Issue | None:
    """Find an issue by ID."""
    for issue in issues:
        if issue.get("id") == issue_id:
            return issue
    return None


def require_issue(issues: list[Issue], issue_id: str) -> Issue | None:
    """Find issue or print error. Returns the issue dict or None."""
    issue = find_issue(issues, issue_id)
    if not issue:
        print(f"Error: Issue '{issue_id}' not found", file=sys.stderr)
    return issue


def find_issue_by_commit(issues: list[Issue], commit: str) -> Issue | None:
    """Find an issue by its commit or merge_commit hash (supports partial match).

    Checks both 'commit' (original implementation commit) and 'merge_commit'
    (squash-merge commit) fields for traceability after squash-merge.
    """
    for issue in issues:
        # Check impl commit
        issue_commit = issue.get("commit", "")
        if issue_commit and (issue_commit == commit or issue_commit.startswith(commit)
                            or commit.startswith(issue_commit)):
            return issue
        # Check merge commit (for squash-merge traceability)
        merge_commit = issue.get("merge_commit", "")
        if merge_commit and (merge_commit == commit or merge_commit.startswith(commit)
                            or commit.startswith(merge_commit)):
            return issue
    return None


def get_children(issues: list[Issue], parent_id: str) -> list[str]:
    """Get direct children of an issue using the parent field."""
    children = []
    for issue in issues:
        if issue.get("parent") == parent_id:
            children.append(issue.get("id", ""))
    return sorted(children)


# ── Helpers ──────────────────────────────────────────────────────────────────


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_model(model: str, field: str) -> bool:
    """Validate that a model ID is a full identifier. Returns True if valid."""
    if model not in VALID_MODELS:
        print(f"Error: Invalid {field} '{model}'", file=sys.stderr)
        print(f"Valid models: {', '.join(VALID_MODELS)}", file=sys.stderr)
        return False
    return True


def validate_reference(ref: dict[str, Any] | Reference) -> str | None:
    """Validate a reference object. Returns error message or None if valid."""
    if not isinstance(ref, dict):
        return "Reference must be a dict"
    has_commit = bool(ref.get("commit"))
    has_file = bool(ref.get("file"))
    if not has_commit and not has_file:
        return "Reference must have at least 'commit' or 'file'"
    if ref.get("lines") and not has_file:
        return "'lines' requires 'file'"
    if ref.get("lines"):
        if not isinstance(ref["lines"], list):
            return "'lines' must be a list"
        for line in ref["lines"]:
            if not isinstance(line, str) or not re.match(r"^\d+(-\d+)?$", line):
                return f"Invalid line format '{line}': must be N or N-N"
    # Only allow known keys
    allowed = {"commit", "file", "lines"}
    unknown = set(ref.keys()) - allowed
    if unknown:
        return f"Unknown reference keys: {', '.join(sorted(unknown))}"
    return None


def format_reference(ref: dict[str, Any] | Reference) -> str:
    """Format a reference dict as a display string like 'commit:abc,file:f.py'."""
    parts = []
    if ref.get("commit"):
        parts.append(f"commit:{ref['commit']}")
    if ref.get("file"):
        parts.append(f"file:{ref['file']}")
    if ref.get("lines"):
        parts.append(f"lines:{';'.join(ref['lines'])}")
    return ",".join(parts)


def parse_ref(ref_str: str) -> dict[str, Any]:
    """Parse a --ref compact string into a reference dict.

    Format: key:value pairs separated by commas.
    - file:path
    - commit:sha
    - lines:L1,L2,L3 (each Li is N or N-N; semicolons also accepted)

    Examples:
        file:src/api.py,lines:42-50,100
        commit:abc1234
        commit:abc1234,file:src/api.py,lines:42-50
    """
    ref: dict[str, Any] = {}
    last_key: str | None = None
    for part in ref_str.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            if last_key == "lines":
                ref["lines"].append(part)
                continue
            raise ValueError(f"Invalid ref part '{part}': expected key:value")
        key, value = part.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key == "lines":
            ref["lines"] = [v.strip() for v in re.split(r"[,;]", value) if v.strip()]
            last_key = "lines"
        elif key in ("file", "commit"):
            ref[key] = value
            last_key = key
        else:
            raise ValueError(f"Unknown ref key '{key}': expected file, commit, or lines")
    return ref


def get_head_commit() -> str:
    """Get the current HEAD commit SHA (short form)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


# ── Dependency Management ────────────────────────────────────────────────────


def get_deps_by_type(issue: Issue, dep_type: str) -> list[str]:
    """Get all dependency IDs of a specific type."""
    deps = issue.get("deps", [])
    return [d["id"] for d in deps if d.get("type") == dep_type]


def add_dep(issue: Issue, target_id: str, dep_type: str) -> bool:
    """Add a dependency to an issue. Returns True if added, False if exists."""
    if "deps" not in issue:
        issue["deps"] = []

    # Check if already exists
    for dep in issue["deps"]:
        if dep.get("id") == target_id and dep.get("type") == dep_type:
            return False

    issue["deps"].append({"id": target_id, "type": dep_type})
    return True


def remove_dep(issue: Issue, target_id: str, dep_type: str | None = None) -> bool:
    """Remove a dependency from an issue. Returns True if removed."""
    if "deps" not in issue:
        return False

    original_len = len(issue["deps"])
    if dep_type:
        issue["deps"] = [d for d in issue["deps"]
                        if not (d.get("id") == target_id and d.get("type") == dep_type)]
    else:
        issue["deps"] = [d for d in issue["deps"] if d.get("id") != target_id]

    return len(issue["deps"]) < original_len


def would_create_cycle(issues: list[Issue], source_id: str, target_id: str, dep_type: str) -> bool:
    """Check if adding a dependency would create a cycle.

    Only checks for blocking-type cycles (blocks/blocked_by).
    """
    if dep_type not in ("blocks", "blocked_by"):
        return False

    # Normalize direction: we want to check if target can reach source
    if dep_type == "blocks":
        # source blocks target means target is blocked_by source
        # Check if source is reachable from target via blocked_by
        start, end = target_id, source_id
    else:
        # source blocked_by target means source depends on target
        # Check if target is reachable from source via blocked_by
        start, end = source_id, target_id

    visited = set()

    def dfs(current: str) -> bool:
        if current == end:
            return True
        if current in visited:
            return False
        visited.add(current)

        issue = find_issue(issues, current)
        if not issue:
            return False

        # Follow blocked_by edges
        for dep in issue.get("deps", []):
            if dep.get("type") == "blocked_by":
                if dfs(dep["id"]):
                    return True
        return False

    return dfs(start)


def sync_bidirectional(issues: list[Issue], source_id: str, target_id: str,
                       dep_type: str, remove: bool = False) -> None:
    """Sync bidirectional dependency (add/remove inverse on target)."""
    inverse_type = DEP_TYPES.get(dep_type)
    if not inverse_type:
        return

    target = find_issue(issues, target_id)
    if not target:
        return

    if remove:
        remove_dep(target, source_id, inverse_type)
    else:
        add_dep(target, source_id, inverse_type)


# ── Archive Management ───────────────────────────────────────────────────────


def get_archive_dir() -> Path:
    """Get the archive directory, creating it if needed."""
    pearls_dir = find_pearls_dir()
    archive_dir = pearls_dir / "archive"
    archive_dir.mkdir(exist_ok=True)
    return archive_dir


def get_archive_path(epic_id: str) -> Path:
    """Get the archive file path for an epic."""
    return get_archive_dir() / f"{epic_id}.jsonl"


def read_archive(archive_path: Path) -> list[Issue]:
    """Read issues from an archive file."""
    if not archive_path.exists():
        return []
    issues = []
    with open(archive_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    issues.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"Error: {archive_path} line {line_num}: invalid JSON: {e}",
                          file=sys.stderr)
                    sys.exit(1)
    return issues


def write_archive(archive_path: Path, issues: list[Issue]) -> None:
    """Write issues to an archive file."""
    with open(archive_path, "w") as f:
        for issue in issues:
            f.write(json.dumps(issue, separators=(",", ":")) + "\n")


def read_all_archived() -> list[Issue]:
    """Read all issues from all archive files."""
    pearls_dir = find_pearls_dir()
    archive_dir = pearls_dir / "archive"
    if not archive_dir.exists():
        return []
    issues = []
    for path in sorted(archive_dir.glob("*.jsonl")):
        issues.extend(read_archive(path))
    return issues


def get_all_descendants(issues: list[Issue], parent_id: str) -> list[Issue]:
    """Get all descendants (children, grandchildren, etc.) of an issue."""
    descendants = []
    for issue in issues:
        if issue.get("parent") == parent_id:
            descendants.append(issue)
            descendants.extend(get_all_descendants(issues, issue["id"]))
    return descendants


def archive_issues(issues: list[Issue], to_archive: list[Issue]) -> tuple[list[Issue], str]:
    """Archive a list of issues, removing them from the main list.

    Args:
        issues: Current issues list (will be modified)
        to_archive: Issues to archive

    Returns:
        Tuple of (remaining_issues, archive_path_used)
    """
    if not to_archive:
        return issues, ""

    # Determine epic ID for archive file
    # If archiving an epic, use its ID
    # If archiving children, use their parent's root epic ID
    first = to_archive[0]
    if first.get("issue_type") == "epic":
        epic_id = first["id"]
    else:
        # Find the root epic by traversing up
        current = first
        while current.get("parent"):
            parent = next((i for i in issues if i["id"] == current["parent"]), None)
            if not parent:
                break
            current = parent
        epic_id = current["id"]

    # Get archive path and read existing
    archive_path = get_archive_path(epic_id)
    archived = read_archive(archive_path)

    # Add to archive (avoid duplicates)
    archived_ids = {i["id"] for i in archived}
    for issue in to_archive:
        if issue["id"] not in archived_ids:
            issue["archived_at"] = now_iso()
            archived.append(issue)

    # Write archive
    write_archive(archive_path, archived)

    # Remove from main issues
    archive_ids = {i["id"] for i in to_archive}
    remaining = [i for i in issues if i["id"] not in archive_ids]

    return remaining, str(archive_path)


# ── Subcommands ──────────────────────────────────────────────────────────────


def resolve_epic(issues: list[Issue], epic_arg: str) -> tuple[str | None, list[Issue]]:
    """Resolve --epic argument to an epic ID, auto-creating if needed.

    Args:
        issues: Current issues list (may be modified if epic created)
        epic_arg: Either a full epic ID, a slug, or an alias from config

    Returns:
        Tuple of (epic_id, updated_issues) or (None, issues) on error
    """
    prefix = load_prefix()
    config = load_config()

    # Try to match by slug or alias from config
    entry = get_epic_entry(config, epic_arg)
    if entry:
        slug = entry["slug"]
        epic_id = f"{prefix}-{slug}"
        epic = find_issue(issues, epic_id)
        if not epic:
            # Auto-create the epic using metadata from config (or defaults)
            title = entry.get("title", slug.replace("-", " ").title())
            new_epic: Issue = cast(Issue, {
                "id": epic_id,
                "title": title,
                "status": "open",
                "issue_type": "epic",
                "priority": 2,
                "created_at": now_iso(),
            })
            body = entry.get("body")
            if body:
                new_epic["body"] = body
            issues.append(new_epic)
            print(f"Created epic {epic_id}: {title}")
        return epic_id, issues

    # Handle full epic ID
    epic = find_issue(issues, epic_arg)
    if not epic:
        print(f"Error: Epic '{epic_arg}' not found", file=sys.stderr)
        return None, issues
    if epic.get("issue_type") != "epic":
        print(f"Error: '{epic_arg}' is not an epic (type: {epic.get('issue_type')})", file=sys.stderr)
        return None, issues
    return epic_arg, issues


def cmd_create(args: argparse.Namespace) -> int:
    issues_path = find_issues_file()
    issues = read_issues(issues_path)

    # Handle --defect-of flag
    defect_of = getattr(args, 'defect_of', None)
    defect_original = None
    if defect_of:
        defect_original = find_issue(issues, defect_of)
        if not defect_original:
            print(f"Error: Issue '{defect_of}' not found", file=sys.stderr)
            return 1
        if not defect_original.get("commit"):
            print(f"Error: Issue '{defect_of}' has no commit field. Cannot create defect.", file=sys.stderr)
            return 1
        # Imply --type=bug
        args.type = "bug"

    # Handle --epic flag
    parent_id = args.parent
    epic_arg = getattr(args, 'epic', None)
    if epic_arg and parent_id:
        print("Error: Cannot use both --epic and --parent", file=sys.stderr)
        return 1
    if epic_arg:
        resolved_epic, issues = resolve_epic(issues, epic_arg)
        if resolved_epic is None:
            return 1
        parent_id = resolved_epic

    if parent_id:
        parent = find_issue(issues, parent_id)
        if not parent:
            print(f"Error: Parent '{parent_id}' not found", file=sys.stderr)
            return 1
        use_hash = is_first_class_epic(parent_id)
        issue_id = next_child_id(issues, parent_id, use_hash=use_hash)
    else:
        issue_id = generate_id(issues)

    issue: Issue = cast(Issue, {
        "id": issue_id,
        "title": args.title,
        "status": "open",
        "issue_type": args.type,
        "priority": args.priority,
        "created_at": now_iso(),
    })
    if parent_id:
        issue["parent"] = parent_id
    if args.body:
        issue["body"] = args.body
    if args.blocked_by:
        issue["deps"] = [{"id": bid, "type": "blocked_by"} for bid in args.blocked_by]
        # Sync inverse deps
        for bid in args.blocked_by:
            sync_bidirectional(issues, issue_id, bid, "blocked_by")
    if args.labels:
        issue["labels"] = args.labels
    if args.ref:
        refs: list[dict[str, Any]] = []
        for ref_str in args.ref:
            try:
                ref = parse_ref(ref_str)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
            err = validate_reference(ref)
            if err:
                print(f"Error: {err}", file=sys.stderr)
                return 1
            refs.append(ref)
        issue["references"] = cast(list[Reference], refs)
    created_by = getattr(args, 'created_by', None)
    if created_by:
        issue["created_by"] = created_by

    # Handle --defect-of: add caused_by dep and ref to original's commit
    if defect_original and defect_of:
        add_dep(issue, defect_of, "caused_by")
        add_dep(defect_original, issue_id, "causes")
        commit = defect_original["commit"]
        defect_ref: Reference = {"commit": commit}
        if "references" not in issue:
            issue["references"] = []
        issue["references"].append(defect_ref)

    issues.append(issue)
    write_issues(issues_path, issues)

    print(f"Created {issue_id}: {args.title}")
    if defect_original:
        print(f"  defect of: {defect_of}")
        print(f"  ref: commit:{defect_original['commit']}")
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    """Edit fields on an existing issue."""
    # Check that at least one edit flag was provided
    has_edit = any([
        args.title is not None,
        args.body is not None,
        args.priority is not None,
        args.type is not None,
    ])
    if not has_edit:
        print("Error: At least one edit flag is required (--title, --body, --priority, --type)", file=sys.stderr)
        return 1

    issues_path = find_issues_file()
    issues = read_issues(issues_path)

    # Check archived issues first
    archived = read_all_archived()
    archived_issue = find_issue(archived, args.issue_id)
    if archived_issue:
        print(f"Error: Issue '{args.issue_id}' is archived and cannot be edited", file=sys.stderr)
        return 1

    issue = require_issue(issues, args.issue_id)
    if not issue:
        return 1

    changes: list[str] = []
    if args.title is not None:
        issue["title"] = args.title
        changes.append(f"title → {args.title}")
    if args.body is not None:
        issue["body"] = args.body
        changes.append("body updated")
    if args.priority is not None:
        issue["priority"] = args.priority
        changes.append(f"priority → P{args.priority}")
    if args.type is not None:
        issue["issue_type"] = cast(IssueType, args.type)
        changes.append(f"type → {args.type}")

    write_issues(issues_path, issues)
    print(f"Edited {args.issue_id}: {', '.join(changes)}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    if getattr(args, 'archived', False):
        issues = read_all_archived()
    else:
        issues_path = find_issues_file()
        issues = read_issues(issues_path)

    if not issues:
        print("No archived issues found." if getattr(args, 'archived', False) else "No issues found.")
        return 0

    filtered = issues
    if getattr(args, 'parent', None):
        parent = find_issue(issues, args.parent)
        if not parent:
            print(f"Error: Parent issue '{args.parent}' not found", file=sys.stderr)
            return 1
        filtered = [i for i in filtered if i.get("parent") == args.parent]
    if args.status:
        filtered = [i for i in filtered if i.get("status") == args.status]
    if args.type:
        filtered = [i for i in filtered if i.get("issue_type") == args.type]
    if args.implementer:
        filtered = [i for i in filtered if i.get("implementer", i.get("assignee")) == args.implementer]

    if not filtered:
        print("No matching issues.")
        return 0

    def parent_chain_path(issue: Issue) -> list[str]:
        """Build the materialized parent-chain path for sorting."""
        path: list[str] = []
        current: Issue | None = issue
        while current:
            path.append(current.get("id", ""))
            parent_id = current.get("parent")
            if parent_id:
                current = find_issue(issues, parent_id)
            else:
                current = None
        path.reverse()
        return path

    filtered.sort(key=lambda i: (parent_chain_path(i), i.get("priority", 99)))

    for issue in filtered:
        priority = issue.get("priority", "-")
        status = issue.get("status", "?")
        issue_type = issue.get("issue_type", "?")
        title = issue.get("title", "(untitled)")
        issue_id = issue.get("id", "?")
        implementer = issue.get("implementer", issue.get("assignee", ""))
        depth = id_depth(issues, issue_id)

        status_icon = STATUS_ICONS.get(status, "?")
        indent = "  " * depth
        implementer_str = f"  [{implementer}]" if implementer else ""

        print(f"  [{status_icon}] {indent}{issue_id}  P{priority} {issue_type:8s} {title}{implementer_str}")

    return 0


def cmd_show(args: argparse.Namespace) -> int:
    if getattr(args, 'archived', False):
        issues = read_all_archived()
    else:
        issues_path = find_issues_file()
        issues = read_issues(issues_path)

    issue = require_issue(issues, args.issue_id)
    if not issue:
        return 1

    # Get children
    children = get_children(issues, args.issue_id)

    # Group deps by type
    deps_grouped: dict[str, list[str]] = {}
    for dep in issue.get("deps", []):
        dep_type = dep.get("type", "unknown")
        if dep_type not in deps_grouped:
            deps_grouped[dep_type] = []
        deps_grouped[dep_type].append(dep["id"])

    output = dict(issue)
    if children:
        output["children"] = children
    if deps_grouped:
        output["deps"] = deps_grouped

    print(json.dumps(output, indent=2))
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    issues_path = find_issues_file()
    issues = read_issues(issues_path)

    issue = require_issue(issues, args.issue_id)
    if not issue:
        return 1

    old_status = issue.get("status")
    if old_status == "closed":
        print(f"Warning: Reopening closed issue {args.issue_id}", file=sys.stderr)
    issue["status"] = "in_progress"
    issue["started_at"] = now_iso()
    agent = getattr(args, 'agent', None)
    if agent:
        issue["started_by"] = agent
    write_issues(issues_path, issues)
    print(f"Started {args.issue_id}: {issue.get('title', '')}")
    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    if not validate_model(args.estimator, "estimator"):
        return 1
    if not validate_model(args.implementer, "implementer"):
        return 1

    # Estimator cost tracking is mandatory by default
    no_cost = getattr(args, 'no_cost', False)
    if not no_cost:
        ei = getattr(args, 'ei', None)
        eo = getattr(args, 'eo', None)
        if ei is None or eo is None:
            print("Error: --ei and --eo are required for estimator cost tracking", file=sys.stderr)
            print("  Use --no-cost to skip cost tracking", file=sys.stderr)
            return 1

    issues_path = find_issues_file()
    issues = read_issues(issues_path)
    cost = {"input": args.input, "output": args.output}

    issue = require_issue(issues, args.issue_id)
    if not issue:
        return 1

    estimates = issue.get("estimates", [])
    key = (args.estimator, args.implementer)
    existing_keys = {(e["estimator"], e["implementer"]) for e in estimates}

    if args.dry_run:
        action = "skip (already exists)" if key in existing_keys else "add"
        print(f"Dry run for {args.issue_id}: would {action}")
        print(f"  estimator:   {args.estimator}")
        print(f"  implementer: {args.implementer}")
        print(f"  cost:        {cost}")
        if not no_cost:
            print(f"  estimator_cost: {{'input': {args.ei}, 'output': {args.eo}}}")
        return 0

    if key in existing_keys:
        print(f"Skipped (already exists): {args.implementer} by {args.estimator}")
        return 0

    estimate_entry: Estimate = cast(Estimate, {
        "estimator": args.estimator,
        "implementer": args.implementer,
        "cost": cost,
    })
    if not no_cost:
        estimate_entry["estimator_cost"] = {"input": args.ei, "output": args.eo}

    estimates.append(estimate_entry)
    issue["estimates"] = estimates
    write_issues(issues_path, issues)
    print(f"Added estimate to {args.issue_id}:")
    print(f"  implementer: {args.implementer}")
    print(f"  estimator:   {args.estimator}")
    print(f"  cost:        {cost}")
    if not no_cost:
        print(f"  estimator_cost: {estimate_entry['estimator_cost']}")
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    issues_path = find_issues_file()
    issues = read_issues(issues_path)

    issue = require_issue(issues, args.issue_id)
    if not issue:
        return 1

    issue["status"] = "closed"
    issue["closed_at"] = now_iso()
    agent = getattr(args, 'agent', None)
    if agent:
        issue["closed_by"] = agent
    write_issues(issues_path, issues)
    print(f"Closed {args.issue_id}: {issue.get('title', '')}")

    # Auto-archive children when closing an epic (unless --no-archive)
    if issue.get("issue_type") == "epic" and not getattr(args, 'no_archive', False):
        # Re-read issues to get fresh state after any writes
        issues = read_issues(issues_path)
        children = get_all_descendants(issues, issue["id"])
        if children:
            # Check if all children are closed
            all_closed = all(c.get("status") == "closed" for c in children)
            if all_closed:
                remaining, archive_path = archive_issues(issues, children)
                write_issues(issues_path, remaining)
                print(f"  Archived {len(children)} closed children to {archive_path}")
            else:
                open_children = [c for c in children if c.get("status") != "closed"]
                print(f"  Note: {len(open_children)} children still open, skipping auto-archive")

    return 0


def cmd_impl(args: argparse.Namespace) -> int:
    """Mark an issue as implemented with cost tracking."""
    # Cost tracking is REQUIRED by default for AI agents
    if not args.no_cost:
        if not args.implementer:
            print("Error: --implementer (-a) is required for cost tracking", file=sys.stderr)
            print("  Use --no-cost to skip cost tracking", file=sys.stderr)
            return 1
        if args.input is None or args.output is None:
            print("Error: --input (-i) and --output (-o) are required for cost tracking", file=sys.stderr)
            print("  Use --no-cost to skip cost tracking", file=sys.stderr)
            return 1
        if not validate_model(args.implementer, "implementer"):
            return 1

    issues_path = find_issues_file()
    issues = read_issues(issues_path)

    issue = require_issue(issues, args.issue_id)
    if not issue:
        return 1

    if issue.get("status") != "in_progress":
        print(f"Error: Issue '{args.issue_id}' is not in_progress (status: {issue.get('status', '?')})", file=sys.stderr)
        return 1

    # Commit is always required (enforces one-commit-per-issue workflow)
    commit = args.commit or get_head_commit()
    if not commit:
        print("Error: Could not detect HEAD commit. Specify --commit (-c).", file=sys.stderr)
        return 1
    issue["commit"] = commit

    # Record implementation costs (unless --no-cost)
    if not args.no_cost:
        issue["implementer"] = args.implementer
        issue["cost"] = {"input": args.input, "output": args.output}

    issue["status"] = "implemented"
    issue["implemented_at"] = now_iso()
    write_issues(issues_path, issues)

    print(f"Implemented {args.issue_id}: {issue.get('title', '')}")
    if not args.no_cost:
        print(f"  implementer: {args.implementer}")
        print(f"  commit:      {commit}")
        print(f"  cost:        {issue['cost']}")
    else:
        print(f"  commit:      {commit}")

    return 0


DEFAULT_EVAL_DIMENSIONS: dict[str, dict[str, Any]] = {
    "correctness": {"description": "Does it work as specified?"},
    "completeness": {"description": "Are all acceptance criteria met?"},
    "quality": {"description": "Is it clean, maintainable, well-structured?"},
    "testing": {"description": "Are changes adequately tested?"},
    "documentation": {"description": "Are changes documented where needed?"},
}


def get_eval_dimensions(config: "dict[str, Any] | Config") -> list[dict[str, Any]]:
    """Return eval dimensions with resolved thresholds from config.

    Each returned dict has: name, description, threshold.
    When eval.dimensions is absent, returns default 5 dimensions.
    """
    global_threshold = config.get("eval", {}).get("threshold", 80)
    dims_config = config.get("eval", {}).get("dimensions")

    if dims_config:
        result = []
        for name, spec in dims_config.items():
            spec = spec or {}
            result.append({
                "name": name,
                "description": spec.get("description", ""),
                "threshold": spec.get("threshold", global_threshold),
            })
        return result

    # Default dimensions
    return [
        {"name": name, "description": spec["description"], "threshold": global_threshold}
        for name, spec in DEFAULT_EVAL_DIMENSIONS.items()
    ]


def cmd_eval(args: argparse.Namespace) -> int:
    """Record evaluation scores on an implemented issue."""
    if not validate_model(args.evaluator, "evaluator"):
        return 1

    # Cost tracking is mandatory by default
    no_cost = getattr(args, 'no_cost', False)
    if not no_cost:
        if args.input is None or args.output is None:
            print("Error: --input (-i) and --output (-o) are required for cost tracking", file=sys.stderr)
            print("  Use --no-cost to skip cost tracking", file=sys.stderr)
            return 1

    # Parse --score key=value pairs
    raw_scores = getattr(args, 'score', None) or []
    if not raw_scores:
        print("Error: at least one --score dimension=value is required", file=sys.stderr)
        print("  Example: --score correctness=90 --score completeness=85", file=sys.stderr)
        return 1
    scores: dict[str, int] = {}
    for entry in raw_scores:
        if '=' not in entry:
            print(f"Error: invalid --score format '{entry}' (expected name=value)", file=sys.stderr)
            return 1
        name, val_str = entry.split('=', 1)
        name = name.strip()
        if not name:
            print("Error: empty dimension name in --score", file=sys.stderr)
            return 1
        try:
            val = int(val_str.strip())
        except ValueError:
            print(f"Error: score for '{name}' must be an integer (got '{val_str.strip()}')", file=sys.stderr)
            return 1
        if val < 0 or val > 100:
            print(f"Error: --score {name} must be 0-100 (got {val})", file=sys.stderr)
            return 1
        scores[name] = val

    issues_path = find_issues_file()
    issues = read_issues(issues_path)

    issue = require_issue(issues, args.issue_id)
    if not issue:
        return 1

    # Validate status: must be implemented OR epic
    is_epic = issue.get("issue_type") == "epic"
    if not is_epic and issue.get("status") != "implemented":
        print(f"Error: Issue '{args.issue_id}' is not implemented (status: {issue.get('status', '?')})", file=sys.stderr)
        print("  Only implemented issues and epics can be evaluated.", file=sys.stderr)
        return 1

    # Check for existing evaluation
    if issue.get("evaluation") and not args.force:
        print(f"Error: Issue '{args.issue_id}' already has an evaluation.", file=sys.stderr)
        print("  Use --force to overwrite the previous evaluation.", file=sys.stderr)
        return 1

    # Compute simple average
    avg = sum(scores.values()) / len(scores)

    evaluation: Evaluation = cast(Evaluation, {
        "evaluator": args.evaluator,
        "evaluated_at": now_iso(),
        "scores": scores,
        "score": round(avg, 1),
    })
    if not no_cost:
        evaluation["cost"] = {"input": args.input, "output": args.output}

    issue["evaluation"] = evaluation

    # Auto-close on pass: per-dimension thresholds (epics exempt)
    no_close = getattr(args, 'no_close', False)
    auto_closed = False
    if not is_epic and not no_close:
        config = load_config()
        dimensions = get_eval_dimensions(config)
        dim_thresholds = {d["name"]: d["threshold"] for d in dimensions}
        # Warn about dimensions not in config (typo protection)
        for dim_name in scores:
            if dim_thresholds and dim_name not in dim_thresholds:
                print(f"Warning: dimension '{dim_name}' not in config", file=sys.stderr)
        # Each scored dimension must meet its threshold (fallback to global for unknown dims)
        global_threshold = config.get("eval", {}).get("threshold", 80)
        if all(s >= dim_thresholds.get(dim, global_threshold) for dim, s in scores.items()):
            issue["status"] = "closed"
            issue["closed_at"] = now_iso()
            auto_closed = True

    write_issues(issues_path, issues)

    print(f"Evaluated {args.issue_id}: {issue.get('title', '')}")
    print(f"  evaluator:     {args.evaluator}")
    max_dim_len = max(len(d) for d in scores)
    for dim, val in scores.items():
        print(f"  {dim + ':': <{max_dim_len + 1}}  {val}")
    print(f"  {'overall:': <{max_dim_len + 1}}  {issue['evaluation']['score']}")
    if not no_cost:
        print(f"  cost:          {evaluation['cost']}")
    if auto_closed:
        print(f"  auto-closed:   all scores >= threshold")

    return 0


def cmd_dep(args: argparse.Namespace) -> int:
    issues_path = find_issues_file()
    issues = read_issues(issues_path)

    issue = require_issue(issues, args.issue_id)
    if not issue:
        return 1

    if args.dep_action == "list":
        deps = issue.get("deps", [])
        if args.type:
            deps = [d for d in deps if d.get("type") == args.type]

        if not deps:
            filter_msg = f" of type '{args.type}'" if args.type else ""
            print(f"{args.issue_id} has no dependencies{filter_msg}.")
            return 0

        # Group by type for display
        by_type: dict[str, list[str]] = {}
        for dep in deps:
            t = dep.get("type", "unknown")
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(dep["id"])

        print(f"Dependencies for {args.issue_id}:")
        for dep_type, ids in sorted(by_type.items()):
            print(f"  {dep_type}:")
            for dep_id in ids:
                dep_issue = find_issue(issues, dep_id)
                status = dep_issue.get("status", "?") if dep_issue else "missing"
                title = dep_issue.get("title", "") if dep_issue else ""
                print(f"    {dep_id}  ({status})  {title}")
        return 0

    if not args.other_id:
        print("Error: other_id required for add/remove", file=sys.stderr)
        return 1

    dep_type = args.type or "blocks"
    if dep_type not in DEP_TYPES:
        print(f"Error: Invalid dependency type '{dep_type}'", file=sys.stderr)
        print(f"Valid types: {', '.join(DEP_TYPES.keys())}", file=sys.stderr)
        return 1

    if args.dep_action == "add":
        other = find_issue(issues, args.other_id)
        target_id = args.other_id

        # For caused_by, allow commit hash lookup if issue ID not found
        if not other and dep_type == "caused_by":
            other = find_issue_by_commit(issues, args.other_id)
            if other:
                target_id = other["id"]
                print(f"Resolved commit {args.other_id} to issue {target_id}")

        if not other:
            print(f"Error: Issue '{args.other_id}' not found", file=sys.stderr)
            if dep_type == "caused_by":
                print("  Hint: For caused_by, you can specify a commit hash", file=sys.stderr)
            return 1
        if target_id == args.issue_id:
            print("Error: Issue cannot depend on itself", file=sys.stderr)
            return 1

        # Check for cycles (blocking types only)
        if would_create_cycle(issues, args.issue_id, target_id, dep_type):
            print(f"Error: Adding this dependency would create a cycle", file=sys.stderr)
            return 1

        added = add_dep(issue, target_id, dep_type)
        if not added:
            print(f"{args.issue_id} already has {dep_type} dependency on {target_id}")
            return 0

        # Sync bidirectional
        sync_bidirectional(issues, args.issue_id, target_id, dep_type)

        write_issues(issues_path, issues)
        print(f"Added: {args.issue_id} {dep_type} {target_id}")
        return 0

    if args.dep_action == "remove":
        removed = remove_dep(issue, args.other_id, dep_type if args.type else None)
        if not removed:
            print(f"{args.issue_id} has no {dep_type} dependency on {args.other_id}")
            return 0

        # Sync bidirectional removal
        sync_bidirectional(issues, args.issue_id, args.other_id, dep_type, remove=True)

        write_issues(issues_path, issues)
        print(f"Removed: {args.issue_id} no longer {dep_type} {args.other_id}")
        return 0

    return 1


def cmd_ref(args: argparse.Namespace) -> int:
    """Manage references on an issue (add/list/remove)."""
    issues_path = find_issues_file()
    issues = read_issues(issues_path)

    issue = require_issue(issues, args.issue_id)
    if not issue:
        return 1

    if args.ref_action == "list":
        refs = issue.get("references", [])
        if not refs:
            print(f"No references on {args.issue_id}")
            return 0
        for i, ref in enumerate(refs):
            print(f"  [{i}] {format_reference(ref)}")
        return 0

    if args.ref_action == "add":
        if not args.file and not args.commit:
            print("Error: --file or --commit required", file=sys.stderr)
            return 1
        ref = {}
        if args.commit:
            ref["commit"] = args.commit
        if args.file:
            ref["file"] = args.file
        if args.lines:
            ref["lines"] = [l.strip() for l in re.split(r"[,;]", args.lines) if l.strip()]
        err = validate_reference(ref)
        if err:
            print(f"Error: {err}", file=sys.stderr)
            return 1
        refs = issue.get("references", [])
        refs.append(ref)
        issue["references"] = refs
        write_issues(issues_path, issues)
        print(f"Added reference to {args.issue_id}: {format_reference(ref)}")
        return 0

    if args.ref_action == "remove":
        if args.index is None:
            print("Error: --index required for remove", file=sys.stderr)
            return 1
        refs = issue.get("references", [])
        if args.index < 0 or args.index >= len(refs):
            print(f"Error: Index {args.index} out of range (0-{len(refs) - 1})", file=sys.stderr)
            return 1
        removed = refs.pop(args.index)
        if refs:
            issue["references"] = refs
        else:
            issue.pop("references", None)
        write_issues(issues_path, issues)
        print(f"Removed reference [{args.index}] from {args.issue_id}: {format_reference(removed)}")
        return 0

    return 1


def cmd_link(args: argparse.Namespace) -> int:
    """Add a relates_to dependency (bidirectional)."""
    issues_path = find_issues_file()
    issues = read_issues(issues_path)

    issue = require_issue(issues, args.issue_id)
    if not issue:
        return 1

    other = require_issue(issues, args.other_id)
    if not other:
        return 1

    if args.issue_id == args.other_id:
        print("Error: Cannot link issue to itself", file=sys.stderr)
        return 1

    added = add_dep(issue, args.other_id, "relates_to")
    add_dep(other, args.issue_id, "relates_to")  # symmetric

    write_issues(issues_path, issues)

    if added:
        print(f"Linked: {args.issue_id} <-> {args.other_id}")
    else:
        print(f"Already linked: {args.issue_id} <-> {args.other_id}")
    return 0


def cmd_dup(args: argparse.Namespace) -> int:
    """Mark an issue as duplicate and close it."""
    issues_path = find_issues_file()
    issues = read_issues(issues_path)

    issue = require_issue(issues, args.issue_id)
    if not issue:
        return 1

    duplicate = require_issue(issues, args.duplicate_id)
    if not duplicate:
        return 1

    if args.issue_id == args.duplicate_id:
        print("Error: Cannot mark issue as duplicate of itself", file=sys.stderr)
        return 1

    # Add bidirectional duplicate deps
    add_dep(issue, args.duplicate_id, "duplicates")
    add_dep(duplicate, args.issue_id, "duplicated_by")

    # Close the duplicate
    duplicate["status"] = "closed"
    duplicate["closed_at"] = now_iso()
    msg = args.message or f"Closed as duplicate of {args.issue_id}"
    duplicate["close_message"] = msg

    write_issues(issues_path, issues)

    print(f"Marked {args.duplicate_id} as duplicate of {args.issue_id}")
    print(f"Closed {args.duplicate_id}: {duplicate.get('title', '')}")
    return 0


def cmd_ready(args: argparse.Namespace) -> int:
    issues_path = find_issues_file()
    issues = read_issues(issues_path)

    open_ids = {i["id"] for i in issues if i.get("status") not in ("closed", "implemented")}

    ready = []
    blocked = []
    soft_warnings = []  # (issue, warning_msg)

    for issue in issues:
        if issue.get("status") != "open":
            continue

        deps = issue.get("deps", [])

        # Check hard blocking
        blocked_by = [d["id"] for d in deps if d.get("type") == "blocked_by"]
        open_blockers = [b for b in blocked_by if b in open_ids]

        if open_blockers:
            blocked.append((issue, open_blockers))
            continue

        # Check soft ordering (follows)
        follows = [d["id"] for d in deps if d.get("type") == "follows"]
        open_follows = [f for f in follows if f in open_ids]

        if open_follows:
            soft_warnings.append((issue, f"follows {', '.join(open_follows)}"))

        ready.append(issue)

    if not ready and not blocked:
        print("No open issues.")
        return 0

    # Sort by priority
    ready.sort(key=lambda i: i.get("priority", 99))

    if ready:
        print(f"{len(ready)} issue(s) ready for work:\n")
        for issue in ready:
            priority = issue.get("priority", "-")
            title = issue.get("title", "(untitled)")
            issue_id = issue.get("id", "?")

            # Check for soft warning
            warning = ""
            for wi, msg in soft_warnings:
                if wi["id"] == issue_id:
                    warning = f"  ({msg})"
                    break

            prefix = "  " if not warning else "  \u26a0\ufe0f "
            print(f"{prefix}{issue_id}  P{priority}  {title}{warning}")

    if blocked:
        print(f"\n{len(blocked)} issue(s) blocked:")
        for issue, blockers in blocked:
            issue_id = issue.get("id", "?")
            priority = issue.get("priority", "-")
            title = issue.get("title", "(untitled)")
            blocker_str = ", ".join(blockers)
            print(f"  {issue_id}  P{priority}  {title}  (blocked by {blocker_str})")

    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    """Show dependency graph for an issue."""
    issues_path = find_issues_file()
    issues = read_issues(issues_path)

    root = require_issue(issues, args.issue_id)
    if not root:
        return 1

    # Build graph data
    def truncate(s: str, max_len: int = 40) -> str:
        return s[:max_len-2] + ".." if len(s) > max_len else s

    # Collect all related issues (blockers and blocked)
    visited = set()
    to_visit = [args.issue_id]
    nodes = {}  # id -> issue
    edges_blocked_by = []  # (from, to) where from is blocked by to
    edges_blocks = []  # (from, to) where from blocks to

    while to_visit:
        current_id = to_visit.pop(0)
        if current_id in visited:
            continue
        visited.add(current_id)

        issue = find_issue(issues, current_id)
        if not issue:
            continue
        nodes[current_id] = issue

        for dep in issue.get("deps", []):
            dep_id = dep.get("id")
            dep_type = dep.get("type")
            if not dep_id:
                continue

            if dep_type == "blocked_by":
                edges_blocked_by.append((current_id, dep_id))
                if dep_id not in visited:
                    to_visit.append(dep_id)
            elif dep_type == "blocks":
                edges_blocks.append((current_id, dep_id))
                if dep_id not in visited:
                    to_visit.append(dep_id)

    # Print header
    print(f"\nDependency Graph for {args.issue_id}")
    print("=" * 60)

    # Find layers (topological-ish ordering)
    # Layer 0: issues that block root
    # Layer 1: root
    # Layer 2: issues blocked by root

    blockers = set()
    blocked = set()

    def find_blockers(issue_id: str, depth: int = 0) -> None:
        if depth > 10:
            return
        issue = nodes.get(issue_id)
        if not issue:
            return
        for dep in issue.get("deps", []):
            if dep.get("type") == "blocked_by":
                dep_id = dep.get("id")
                if dep_id and dep_id in nodes:
                    blockers.add(dep_id)
                    find_blockers(dep_id, depth + 1)

    def find_blocked(issue_id: str, depth: int = 0) -> None:
        if depth > 10:
            return
        issue = nodes.get(issue_id)
        if not issue:
            return
        for dep in issue.get("deps", []):
            if dep.get("type") == "blocks":
                dep_id = dep.get("id")
                if dep_id and dep_id in nodes:
                    blocked.add(dep_id)
                    find_blocked(dep_id, depth + 1)

    find_blockers(args.issue_id)
    find_blocked(args.issue_id)

    # Print blockers (upstream)
    if blockers:
        print("\n  BLOCKERS (must complete first):")
        for bid in sorted(blockers):
            issue = nodes[bid]
            icon = STATUS_ICONS.get(issue.get("status", ""), "?")
            title = truncate(issue.get("title", ""), 35)
            print(f"    {icon} {bid}  {title}")
        print("        │")
        print("        ▼")

    # Print root
    root_icon = STATUS_ICONS.get(root.get("status", ""), "?")
    root_title = truncate(root.get("title", ""), 35)
    print(f"\n  ► {root_icon} {args.issue_id}  {root_title}  ◄── YOU ARE HERE")

    # Print blocked (downstream)
    if blocked:
        print("        │")
        print("        ▼")
        print("\n  BLOCKED BY THIS (waiting):")
        for bid in sorted(blocked):
            issue = nodes[bid]
            icon = STATUS_ICONS.get(issue.get("status", ""), "?")
            title = truncate(issue.get("title", ""), 35)
            print(f"    {icon} {bid}  {title}")

    # Legend
    print("\n" + "-" * 60)
    print("  Legend: ○ open  ◐ in_progress  ● closed")

    # Summary
    open_blockers = sum(1 for b in blockers if nodes[b].get("status") != "closed")
    if open_blockers:
        print(f"\n  ⚠ {open_blockers} open blocker(s) - this issue cannot proceed")
    elif blockers:
        print(f"\n  ✓ All {len(blockers)} blocker(s) closed - ready to work")

    print()
    return 0


def cmd_board(args: argparse.Namespace) -> int:
    """Show kanban board view of issues."""
    issues_path = find_issues_file()
    issues = read_issues(issues_path)

    if not issues:
        print("No issues found.")
        return 0

    # Filter issues
    filtered = issues
    if args.type:
        filtered = [i for i in filtered if i.get("issue_type") == args.type]
    if args.label:
        filtered = [i for i in filtered if args.label in i.get("labels", [])]
    if args.parent:
        # Show only direct children of parent
        filtered = [i for i in filtered if i.get("parent") == args.parent]

    # Group by status
    columns: dict[str, list[Issue]] = {
        "open": [],
        "in_progress": [],
        "implemented": [],
        "closed": [],
    }

    for issue in filtered:
        status_str = issue.get("status", "open")
        if status_str in columns:
            columns[status_str].append(issue)
        elif status_str == "tombstone":  # type: ignore[comparison-overlap]
            columns["closed"].append(issue)

    # Sort each column by priority
    for col in columns.values():
        col.sort(key=lambda i: (i.get("priority", 99), i.get("id", "")))

    # Limit closed to most recent N if not showing all
    if not args.all and len(columns["closed"]) > 10:
        columns["closed"] = columns["closed"][:10]
        closed_truncated = True
    else:
        closed_truncated = False

    # Calculate column widths
    def truncate(s: str, max_len: int) -> str:
        return s[:max_len-2] + ".." if len(s) > max_len else s

    col_width = 24
    num_cols = 4
    title_width = col_width - 4

    # Print header
    total = sum(len(columns[s]) for s in columns)
    print(f"\n{'─' * (col_width * num_cols + num_cols * 2 + 2)}")
    print(f"  KANBAN BOARD ({total} issues)")
    print(f"{'─' * (col_width * num_cols + num_cols * 2 + 2)}")

    # Print column headers
    status_keys = ["open", "in_progress", "implemented", "closed"]
    headers = [
        f"  OPEN ({len(columns['open'])})",
        f"IN PROGRESS ({len(columns['in_progress'])})",
        f"IMPLEMENTED ({len(columns['implemented'])})",
        f"CLOSED ({len(columns['closed'])}{'+'if closed_truncated else ''})",
    ]
    header_line = "│ " + " │ ".join(f"{h:<{col_width}}" for h in headers) + " │"
    print(header_line)
    sep = "┼".join("─" * (col_width + 2) for _ in status_keys)
    print(f"├{sep}┤")

    # Find max rows needed
    max_rows = max(max(len(columns[s]) for s in status_keys), 1)

    # Print rows
    for i in range(max_rows):
        cells = []
        for status in status_keys:
            if i < len(columns[status]):
                issue = columns[status][i]
                priority = issue.get("priority", "-")
                issue_id = issue.get("id", "?")
                # Extract just the hash part for compact display
                short_id = issue_id.split("-")[-1] if "-" in issue_id else issue_id
                title = truncate(issue.get("title", ""), title_width - len(short_id) - 5)
                cell = f"P{priority} {short_id} {title}"
                cells.append(truncate(cell, col_width))
            else:
                cells.append("")
        row_line = "│ " + " │ ".join(f"{c:<{col_width}}" for c in cells) + " │"
        print(row_line)

    footer = "┴".join("─" * (col_width + 2) for _ in status_keys)
    print(f"└{footer}┘")

    # Print summary
    print(f"\n  Summary: {len(columns['open'])} open, {len(columns['in_progress'])} in progress, {len(columns['implemented'])} implemented, {len(columns['closed'])} closed")

    if closed_truncated:
        print(f"  (Showing 10 most recent closed. Use --all to see all)")

    print()
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    """Archive issues to .pearls/archive/<epic-id>.jsonl."""
    issues_path = find_issues_file()
    issues = read_issues(issues_path)

    issue = require_issue(issues, args.issue_id)
    if not issue:
        return 1

    to_archive = [issue]

    # If epic, include all descendants
    if issue.get("issue_type") == "epic" or args.children:
        descendants = get_all_descendants(issues, issue["id"])
        to_archive.extend(descendants)

    # Perform archive
    remaining, archive_path = archive_issues(issues, to_archive)

    # Write back
    write_issues(issues_path, remaining)

    # Report
    print(f"Archived {len(to_archive)} issue(s) to {archive_path}:")
    for i in to_archive:
        print(f"  - {i['id']}: {i.get('title', '')}")
    return 0


def cmd_move(args: argparse.Namespace) -> int:
    """Move an issue to a different parent epic or detach to top-level."""
    issues_path = find_issues_file()
    issues = read_issues(issues_path)

    issue = require_issue(issues, args.issue_id)
    if not issue:
        return 1

    # Cannot move closed issues
    if issue.get("status") == "closed":
        print(f"Error: Cannot move closed issue {args.issue_id}", file=sys.stderr)
        return 1

    no_epic = getattr(args, 'no_epic', False)
    target_id: str | None = getattr(args, 'to', None)

    if no_epic:
        # Detach to top-level
        current_parent = issue.get("parent")
        if not current_parent:
            print(f"Issue {args.issue_id} is already top-level")
            return 0
        del issue["parent"]
        write_issues(issues_path, issues)
        print(f"Moved {args.issue_id} to top-level (removed parent {current_parent})")
        return 0

    # Move to target epic
    if not target_id:
        print("Error: Must specify --to <epic-id> or --no-epic", file=sys.stderr)
        return 1

    target = require_issue(issues, target_id)
    if not target:
        return 1

    if target.get("issue_type") != "epic":
        print(f"Error: Target '{target_id}' is not an epic (type: {target.get('issue_type', '?')})", file=sys.stderr)
        return 1

    # Self-move check
    if args.issue_id == target_id:
        print(f"Error: Cannot move {args.issue_id} under itself", file=sys.stderr)
        return 1

    # No-op check
    if issue.get("parent") == target_id:
        print(f"Issue {args.issue_id} is already under {target_id}")
        return 0

    # Cycle detection: cannot move under own descendant
    descendants = get_all_descendants(issues, args.issue_id)
    descendant_ids = {d.get("id") for d in descendants}
    if target_id in descendant_ids:
        print(f"Error: Cannot move {args.issue_id} under its own descendant {target_id}", file=sys.stderr)
        return 1

    issue["parent"] = target_id
    write_issues(issues_path, issues)
    print(f"Moved {args.issue_id} to epic {target_id}")
    return 0


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"prl {VERSION} (pearls — lightweight issue tracker)")
    return 0


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="prl",
        description="pearls — lightweight, AI-native issue tracker",
    )
    sub = parser.add_subparsers(dest="command")

    # create
    p_create = sub.add_parser("create", help="Create a new issue")
    p_create.add_argument("--title", "-t", required=True, help="Issue title")
    p_create.add_argument("--type", choices=VALID_TYPES, default="task", help="Issue type (default: task)")
    p_create.add_argument("--priority", "-p", type=int, default=2, choices=range(1, 6), help="Priority 1-5 (default: 2)")
    p_create.add_argument("--body", "-b", help="Issue body/description")
    p_create.add_argument("--parent", help="Parent issue ID (creates a child task)")
    p_create.add_argument("--epic", help="Epic ID or slug ('1shot', 'enhncmnts')")
    p_create.add_argument("--blocked-by", nargs="*", help="Issue IDs that block this one")
    p_create.add_argument("--defect-of", help="Create a defect ticket linked to this issue (implies --type=bug)")
    p_create.add_argument("--labels", "-l", nargs="*", help="Labels for the issue")
    p_create.add_argument("--ref", action="append", help="Code reference (repeatable): file:path,lines:L1;L2 or commit:sha")
    p_create.add_argument("--created-by", help="Identity of the creator (freeform string)")
    p_create.set_defaults(func=cmd_create)

    # edit
    p_edit = sub.add_parser("edit", help="Edit fields on an existing issue")
    p_edit.add_argument("issue_id", help="Issue ID")
    p_edit.add_argument("--title", "-t", help="New title")
    p_edit.add_argument("--body", "-b", help="New body/description")
    p_edit.add_argument("--priority", "-p", type=int, choices=range(1, 6), help="New priority (1-5)")
    p_edit.add_argument("--type", choices=VALID_TYPES, help="New issue type")
    p_edit.set_defaults(func=cmd_edit)

    # list
    p_list = sub.add_parser("list", help="List issues")
    p_list.add_argument("--status", "-s", choices=VALID_STATUSES, help="Filter by status")
    p_list.add_argument("--type", choices=VALID_TYPES, help="Filter by type")
    p_list.add_argument("--implementer", "-a", help="Filter by implementer")
    p_list.add_argument("--parent", help="Filter to children of this issue")
    p_list.add_argument("--archived", action="store_true", help="List archived issues instead of active")
    p_list.set_defaults(func=cmd_list)

    # show
    p_show = sub.add_parser("show", help="Show issue details")
    p_show.add_argument("issue_id", help="Issue ID")
    p_show.add_argument("--archived", action="store_true", help="Look up issue in archive")
    p_show.set_defaults(func=cmd_show)

    # start
    p_start = sub.add_parser("start", help="Mark issue as in_progress")
    p_start.add_argument("issue_id", help="Issue ID")
    p_start.add_argument("--agent", help="Identity of the agent/person starting (freeform string)")
    p_start.set_defaults(func=cmd_start)

    # estimate
    p_est = sub.add_parser("estimate", help="Add a token cost estimate")
    p_est.add_argument("issue_id", help="Issue ID")
    p_est.add_argument("--estimator", "-e", required=True, help="Full model ID of estimator")
    p_est.add_argument("--implementer", "-m", required=True, help="Full model ID of implementer")
    p_est.add_argument("--input", "-i", type=int, required=True, help="Estimated input tokens")
    p_est.add_argument("--output", "-o", type=int, required=True, help="Estimated output tokens")
    p_est.add_argument("--ei", type=int, help="Estimator input tokens consumed (required unless --no-cost)")
    p_est.add_argument("--eo", type=int, help="Estimator output tokens generated (required unless --no-cost)")
    p_est.add_argument("--no-cost", action="store_true", help="Skip estimator cost tracking")
    p_est.add_argument("--dry-run", "-n", action="store_true", help="Preview without modifying")
    p_est.set_defaults(func=cmd_estimate)

    # close
    p_close = sub.add_parser("close", help="Close an issue")
    p_close.add_argument("issue_id", help="Issue ID")
    p_close.add_argument("--agent", help="Identity of the agent/person closing (freeform string)")
    p_close.add_argument("--no-archive", action="store_true", help="Skip auto-archive of children when closing epic")
    p_close.set_defaults(func=cmd_close)

    # impl
    p_impl = sub.add_parser("impl", help="Mark issue as implemented with cost tracking")
    p_impl.add_argument("issue_id", help="Issue ID")
    p_impl.add_argument("-a", "--implementer", required=False, help="Full model ID of implementer (required unless --no-cost)")
    p_impl.add_argument("-i", "--input", type=int, help="Actual input tokens consumed (required unless --no-cost)")
    p_impl.add_argument("-o", "--output", type=int, help="Actual output tokens generated (required unless --no-cost)")
    p_impl.add_argument("-c", "--commit", help="Commit SHA (defaults to HEAD)")
    p_impl.add_argument("--no-cost", action="store_true", help="Skip cost tracking")
    p_impl.set_defaults(func=cmd_impl)

    # eval
    p_eval = sub.add_parser("eval", help="Record evaluation scores on an implemented issue")
    p_eval.add_argument("issue_id", help="Issue ID")
    p_eval.add_argument("--evaluator", required=True, help="Full model ID of evaluator")
    p_eval.add_argument("--score", action="append", metavar="DIM=N", help="Score a dimension (repeatable, e.g. --score correctness=90)")
    p_eval.add_argument("-i", "--input", type=int, help="Evaluator input tokens consumed (required unless --no-cost)")
    p_eval.add_argument("-o", "--output", type=int, help="Evaluator output tokens generated (required unless --no-cost)")
    p_eval.add_argument("--no-cost", action="store_true", help="Skip cost tracking")
    p_eval.add_argument("--force", action="store_true", help="Overwrite existing evaluation")
    p_eval.add_argument("--no-close", action="store_true", help="Suppress auto-close even when all scores pass threshold")
    p_eval.set_defaults(func=cmd_eval)

    # dep
    p_dep = sub.add_parser("dep", help="Manage dependencies")
    p_dep.add_argument("dep_action", choices=["add", "remove", "list"], help="Dependency action")
    p_dep.add_argument("issue_id", help="Issue ID")
    p_dep.add_argument("other_id", nargs="?", help="Other issue ID (required for add/remove)")
    p_dep.add_argument("--type", "-t", help="Dependency type (default: blocks)")
    p_dep.set_defaults(func=cmd_dep)

    # ref
    p_ref = sub.add_parser("ref", help="Manage code references on an issue")
    p_ref.add_argument("ref_action", choices=["add", "list", "remove"], help="Reference action")
    p_ref.add_argument("issue_id", help="Issue ID")
    p_ref.add_argument("--commit", help="Commit SHA reference")
    p_ref.add_argument("--file", help="File path reference")
    p_ref.add_argument("--lines", help="Line ranges (comma or semicolon-separated): 42,100-110,200")
    p_ref.add_argument("--index", type=int, help="Reference index to remove (0-based)")
    p_ref.set_defaults(func=cmd_ref)

    # link (shortcut for relates_to)
    p_link = sub.add_parser("link", help="Link two issues (relates_to, bidirectional)")
    p_link.add_argument("issue_id", help="First issue ID")
    p_link.add_argument("other_id", help="Second issue ID")
    p_link.set_defaults(func=cmd_link)

    # dup (mark duplicate and close)
    p_dup = sub.add_parser("dup", help="Mark issue as duplicate and close it")
    p_dup.add_argument("issue_id", help="Original issue ID (kept open)")
    p_dup.add_argument("duplicate_id", help="Duplicate issue ID (will be closed)")
    p_dup.add_argument("-m", "--message", help="Close message (default: 'Closed as duplicate of <id>')")
    p_dup.set_defaults(func=cmd_dup)

    # ready
    p_ready = sub.add_parser("ready", help="Show issues ready for work")
    p_ready.set_defaults(func=cmd_ready)

    # graph
    p_graph = sub.add_parser("graph", help="Show dependency graph for an issue")
    p_graph.add_argument("issue_id", help="Issue ID to show graph for")
    p_graph.set_defaults(func=cmd_graph)

    # board
    p_board = sub.add_parser("board", help="Show kanban board view")
    p_board.add_argument("--type", "-t", choices=VALID_TYPES, help="Filter by issue type")
    p_board.add_argument("--label", "-l", help="Filter by label")
    p_board.add_argument("--parent", "-p", help="Show only children of this issue")
    p_board.add_argument("--all", "-a", action="store_true", help="Show all closed issues (default: 10)")
    p_board.set_defaults(func=cmd_board)

    # archive
    p_archive = sub.add_parser("archive", help="Archive issues to .pearls/archive/")
    p_archive.add_argument("issue_id", help="Issue or epic ID to archive")
    p_archive.add_argument("--children", "-c", action="store_true",
                          help="Include all children (for non-epics)")
    p_archive.set_defaults(func=cmd_archive)

    # move
    p_move = sub.add_parser("move", help="Move issue to a different parent epic")
    p_move.add_argument("issue_id", help="Issue ID to move")
    move_target = p_move.add_mutually_exclusive_group(required=True)
    move_target.add_argument("--to", help="Target epic ID to move under")
    move_target.add_argument("--no-epic", action="store_true", help="Detach to top-level (remove parent)")
    p_move.set_defaults(func=cmd_move)

    # version
    p_version = sub.add_parser("version", help="Show version")
    p_version.set_defaults(func=cmd_version)

    # Intercept removed subcommands before argparse to give helpful errors
    if len(sys.argv) > 1 and sys.argv[1] == "prompt":
        print(
            "Error: 'prl prompt' has been removed. Use 'madp' instead.\n"
            "\n"
            "  madp              # default intro prompt\n"
            "  madp planning     # plan features\n"
            "  madp implement    # implement tasks\n"
            "  madp eval         # evaluate implementations\n"
            "\n"
            "Run 'madp --help' for all available modes.",
            file=sys.stderr,
        )
        return 1

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
