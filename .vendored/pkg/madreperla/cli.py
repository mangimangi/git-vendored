#!/usr/bin/env python3
"""madp — madreperla CLI for prompt generation and hook orchestration.

Usage:
    madp                     # header + intro (description + docs)
    madp <mode>              # header + intro + body (7 modes)
    madp --resume            # header only (minimal context)
    madp --install-hooks     # generate orchestrator + wire settings.json
    madp --version           # version info
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

VERSION = "0.0.5"

VALID_MODES = {"planning", "refine", "estimate", "implement", "oneshot", "eval", "cleanup"}


# ── Config Loading ───────────────────────────────────────────────────────────


def _find_project_root() -> Path:
    """Walk up from madreperla module location to find the project root.

    Looks for .vendored/ or .madreperla/ directories as markers.
    """
    # Start from this file's directory (.madreperla/)
    start = Path(__file__).resolve().parent

    # .madreperla/ is inside the project root
    candidate = start.parent
    if (candidate / ".vendored").is_dir() or (candidate / ".madreperla").is_dir():
        return candidate

    # Walk up from CWD as fallback
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".vendored").is_dir() or (parent / ".madreperla").is_dir():
            return parent

    raise FileNotFoundError(
        "Could not find project root. "
        "Run from a directory containing .vendored/ or .madreperla/."
    )


def load_config(project_root: Path | None = None) -> dict[str, Any]:
    """Load madreperla config from .vendored/configs/madreperla.json.

    Returns dict with keys: description, docs, providers, prompts, sessions, eval.
    Returns empty dict if config file is missing.
    Strips _vendor metadata before returning.
    """
    if project_root is None:
        project_root = _find_project_root()
    config_path = project_root / ".vendored" / "configs" / "madreperla.json"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r") as f:
            raw: dict[str, Any] = json.load(f)
        return {k: v for k, v in raw.items() if k != "_vendor"}
    except json.JSONDecodeError as e:
        print(f"Warning: {config_path} is not valid JSON: {e}", file=sys.stderr)
        return {}


# ── Prompt Functions ─────────────────────────────────────────────────────────


def get_prompt_header() -> str:
    """Return version/command context for all prompt outputs.

    Note: madp does NOT announce vendored tools — they self-announce
    via their own session hooks (e.g., pearls emits its own prl header).
    """
    return f"madp v{VERSION}"


def get_prompt_intro(description: str, docs_str: str) -> str:
    """Return the shared intro line used by all prompt modes."""
    return f"hi claude - this is {description}...check out {docs_str} to understand the contributing workflow"


# ── Provider Announcements ──────────────────────────────────────────────────

_DOCS_PROVIDER_DEFAULTS: dict[str, str] = {
    "planning": "docs/planning",
    "epics": "docs/planning/epics",
    "designs": "docs/designs",
}


def _is_vendored_provider(provider_config: dict[str, Any]) -> bool:
    """Check if a provider is vendored (has docs pointing into .vendored/)."""
    docs = provider_config.get("docs", [])
    return any(str(d).startswith(".vendored/") for d in docs)


def get_provider_announcements(config: dict[str, Any]) -> str:
    """Generate announcement lines for non-vendored providers.

    Vendored providers self-announce via their own session hooks.
    Non-vendored providers are announced by madp from config.

    Returns empty string if no announcements to make.
    """
    providers = config.get("providers", {})
    announcements: list[str] = []

    for slot, provider_config in providers.items():
        if not isinstance(provider_config, dict):
            continue
        # Skip vendored providers — they self-announce
        if _is_vendored_provider(provider_config):
            continue

        name = provider_config.get("name", slot)

        # docs provider: announce per-type artifact paths
        if slot == "docs":
            paths = {
                doc_type: provider_config.get(doc_type, default)
                for doc_type, default in _DOCS_PROVIDER_DEFAULTS.items()
            }
            parts = " | ".join(f"{t} \u2192 {p}/" for t, p in paths.items())
            announcements.append(f"{name}: {parts}")
        else:
            # Other non-vendored providers: simple name announcement
            announcements.append(f"{name}: configured")

    return "\n".join(announcements)


def get_docs_provider_paths(config: dict[str, Any]) -> dict[str, str]:
    """Resolve docs provider paths from config, with defaults.

    Returns dict with keys: planning, epics, designs.
    """
    docs_config = config.get("providers", {}).get("docs", {})
    return {
        doc_type: docs_config.get(doc_type, default)
        for doc_type, default in _DOCS_PROVIDER_DEFAULTS.items()
    }


def validate_prompt_config(config: dict[str, Any]) -> bool:
    """Validate that description and docs are configured for prompt generation."""
    if not config.get("description"):
        print(
            "Error: 'description' not configured in .vendored/configs/madreperla.json.\n"
            "Add a project description to use madp.",
            file=sys.stderr,
        )
        return False
    if not config.get("docs"):
        print(
            "Error: 'docs' not configured in .vendored/configs/madreperla.json.\n"
            "Add docs paths to use madp.",
            file=sys.stderr,
        )
        return False
    return True


# ── Orchestrator Generation ──────────────────────────────────────────────────

ORCHESTRATOR_SCRIPT = """\
#!/bin/bash
# vendored-session.sh — orchestrator for vendored session hooks.
# Generated by madp --install-hooks. Do not edit manually.
set -euo pipefail

MODE=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --start) MODE="start"; shift ;;
        --resume) MODE="resume"; shift ;;
        *) shift ;;
    esac
done

if [ -z "$MODE" ]; then
    echo "Usage: vendored-session.sh --start|--resume" >&2
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
VENDORED_INSTALL="$PROJECT_DIR/.vendored/install"

if [ ! -f "$VENDORED_INSTALL" ]; then
    echo "Warning: .vendored/install not found, skipping hook orchestration" >&2
    exit 0
fi

# ── Post-install safety net ──────────────────────────────────────────────────
# Check version stamps and re-run stale post-install hooks before session hooks.
MANIFESTS_DIR="$PROJECT_DIR/.vendored/manifests"
VENDORS=$(python3 "$VENDORED_INSTALL" --list 2>/dev/null) || true

if [ -n "$VENDORS" ]; then
    while IFS= read -r vendor_name; do
        [ -z "$vendor_name" ] && continue
        version_file="$MANIFESTS_DIR/$vendor_name.version"
        stamp_file="$MANIFESTS_DIR/$vendor_name.post-installed"
        post_install_hook="$PROJECT_DIR/.vendored/pkg/$vendor_name/hooks/post-install.sh"

        # Skip if no version file (not installed)
        [ ! -f "$version_file" ] && continue
        # Skip if no post-install hook
        [ ! -f "$post_install_hook" ] && continue

        # Compare stamps: run post-install if stamp is missing or differs
        if [ ! -f "$stamp_file" ] || [ "$(cat "$version_file")" != "$(cat "$stamp_file")" ]; then
            VENDOR_NAME="$vendor_name" \\
            VENDOR_PKG_DIR="$PROJECT_DIR/.vendored/pkg/$vendor_name" \\
            PROJECT_DIR="$PROJECT_DIR" \\
            bash "$post_install_hook"
            # Update stamp on success
            cp "$version_file" "$stamp_file"
        fi
    done <<< "$VENDORS"
fi

# ── Session hooks ────────────────────────────────────────────────────────────
# Discover and run session hooks in dependency order.
HOOK_PATHS=$(python3 "$VENDORED_INSTALL" --hooks "$MODE" 2>/dev/null) || true

if [ -z "$HOOK_PATHS" ]; then
    exit 0
fi

# Run each vendor's hook with env vars
while IFS= read -r hook_path; do
    [ -z "$hook_path" ] && continue
    # Extract vendor name from path: .vendored/pkg/<vendor>/hooks/<hook>
    vendor_dir=$(dirname "$(dirname "$hook_path")")
    vendor_name=$(basename "$vendor_dir")

    VENDOR_NAME="$vendor_name" \\
    VENDOR_PKG_DIR="$vendor_dir" \\
    PROJECT_DIR="$PROJECT_DIR" \\
    bash "$hook_path"
done <<< "$HOOK_PATHS"
"""


def generate_orchestrator(project_root: Path) -> Path:
    """Generate .claude/hooks/vendored-session.sh orchestrator script."""
    hooks_dir = project_root / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    orchestrator_path = hooks_dir / "vendored-session.sh"
    orchestrator_path.write_text(ORCHESTRATOR_SCRIPT)
    orchestrator_path.chmod(0o755)
    return orchestrator_path


# ── Settings.json Management ────────────────────────────────────────────────

VENDORED_MARKER = ".claude/hooks/vendored-"


def _is_vendored_hook(command: str) -> bool:
    """Check if a hook command is managed by madreperla."""
    return VENDORED_MARKER in command


def _build_vendored_entries() -> list[dict[str, Any]]:
    """Build the SessionStart entries for the vendored orchestrator."""
    return [
        {
            "matcher": "startup",
            "hooks": [
                {
                    "type": "command",
                    "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/vendored-session.sh --start',
                    "statusMessage": "Configuring vendored tools...",
                }
            ],
        },
        {
            "matcher": "resume",
            "hooks": [
                {
                    "type": "command",
                    "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/vendored-session.sh --resume',
                    "statusMessage": "Configuring vendored tools...",
                }
            ],
        },
    ]


def write_settings_json(project_root: Path) -> Path:
    """Write/merge .claude/settings.json with vendored orchestrator hooks.

    Managed entries (commands containing '.claude/hooks/vendored-') are
    replaced. All other entries and non-hook keys are preserved.
    """
    settings_path = project_root / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing settings
    existing: dict[str, Any] = {}
    if settings_path.exists():
        try:
            with open(settings_path, "r") as f:
                existing = json.load(f)
        except json.JSONDecodeError:
            existing = {}

    # Filter out vendored-managed entries from SessionStart
    hooks = existing.setdefault("hooks", {})
    session_start: list[dict[str, Any]] = hooks.get("SessionStart", [])
    non_vendored = [
        entry for entry in session_start
        if not any(_is_vendored_hook(h.get("command", "")) for h in entry.get("hooks", []))
    ]

    # Also filter out legacy configure.sh entries
    legacy_markers = ["configure.sh", "configure-prl.sh"]
    non_vendored = [
        entry for entry in non_vendored
        if not any(
            any(m in h.get("command", "") for m in legacy_markers)
            for h in entry.get("hooks", [])
        )
    ]

    # Prepend orchestrator entries
    vendored_entries = _build_vendored_entries()
    hooks["SessionStart"] = vendored_entries + non_vendored
    existing["hooks"] = hooks

    with open(settings_path, "w") as f:
        json.dump(existing, f, indent=2)
        f.write("\n")

    return settings_path


# ── CLI ──────────────────────────────────────────────────────────────────────


def run(args: list[str] | None = None) -> int:
    """Main entry point for madp CLI."""
    parser = argparse.ArgumentParser(
        prog="madp",
        description="madreperla — prompt methodology engine",
    )
    parser.add_argument(
        "mode", nargs="?", default=None,
        help="Prompt mode: planning, refine, estimate, implement, oneshot, eval, or cleanup",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Output minimal resume header only",
    )
    parser.add_argument(
        "--install-hooks", action="store_true", dest="install_hooks",
        help="Generate orchestrator script and wire settings.json",
    )
    parser.add_argument(
        "--version", action="store_true",
        help="Show version info",
    )

    parsed = parser.parse_args(args)

    # --version
    if parsed.version:
        print(f"madp {VERSION}")
        return 0

    # --install-hooks: generate orchestrator + wire settings.json
    if parsed.install_hooks:
        try:
            project_root = _find_project_root()
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        orch_path = generate_orchestrator(project_root)
        print(f"Generated {orch_path.relative_to(project_root)}")
        settings_path = write_settings_json(project_root)
        print(f"Updated {settings_path.relative_to(project_root)}")
        return 0

    # --resume without mode: header only (backward-compatible)
    if parsed.resume and parsed.mode is None:
        print(get_prompt_header())
        return 0

    # Load config
    config = load_config()

    if not validate_prompt_config(config):
        return 1

    description: str = config["description"]
    docs: list[str] = config["docs"]
    docs_str = " ".join(docs)
    header = get_prompt_header()

    # Build announcements for non-vendored providers
    announcements = get_provider_announcements(config)

    # No mode: header + intro (+ announcements if any)
    if parsed.mode is None:
        parts = [header, get_prompt_intro(description, docs_str)]
        if announcements:
            parts.append(announcements)
        print("\n\n".join(parts))
        return 0

    # Validate mode
    if parsed.mode not in VALID_MODES:
        print(
            f"Error: Unknown mode '{parsed.mode}'. "
            "Valid modes: planning, refine, estimate, implement, oneshot, eval, cleanup",
            file=sys.stderr,
        )
        return 1

    # Import prompt body generation
    import importlib.util

    pkg_dir = Path(__file__).resolve().parent
    if 'madreperla.prompt' not in sys.modules:
        ps = importlib.util.spec_from_file_location('madreperla.prompt', pkg_dir / 'prompt.py')
        assert ps is not None and ps.loader is not None
        pm = importlib.util.module_from_spec(ps)
        sys.modules['madreperla.prompt'] = pm
        ps.loader.exec_module(pm)
    if 'madreperla' not in sys.modules:
        s = importlib.util.spec_from_file_location(
            'madreperla', pkg_dir / '__init__.py',
            submodule_search_locations=[str(pkg_dir)])
        assert s is not None and s.loader is not None
        m = importlib.util.module_from_spec(s)
        sys.modules['madreperla'] = m
        s.loader.exec_module(m)
    from madreperla import get_prompt_body, get_prompt_resume_body  # type: ignore[import-not-found]

    intro = get_prompt_intro(description, docs_str)
    if parsed.resume:
        # --resume <mode>: header + intro + announcements + resume body
        body: str = get_prompt_resume_body(parsed.mode, config)
    else:
        # <mode>: header + intro + announcements + start body
        body = get_prompt_body(parsed.mode, config)
    parts = [header, intro]
    if announcements:
        parts.append(announcements)
    parts.append(body)
    print("\n\n".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(run())
