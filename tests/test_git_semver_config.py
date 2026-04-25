"""Guard the .vendored/configs/git-semver.json files audit (gv-f2c0).

Asserts that user-facing shipped files are covered by the file patterns and
that internal/repo-only files are not — so a future edit cannot silently
drop coverage of the install payload, validate CLI, or docs.
"""

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
GIT_SEMVER_BIN = ROOT / ".vendored" / "pkg" / "git-semver" / "git-semver"
CONFIG_PATH = ROOT / ".vendored" / "configs" / "git-semver.json"


def _load_matches_pattern():
    """Import git-semver's pattern matcher (the script has no .py extension)."""
    loader = importlib.machinery.SourceFileLoader("git_semver_bin", str(GIT_SEMVER_BIN))
    spec = importlib.util.spec_from_loader("git_semver_bin", loader, origin=str(GIT_SEMVER_BIN))
    module = importlib.util.module_from_spec(spec)
    sys.modules["git_semver_bin"] = module
    spec.loader.exec_module(module)
    return module.matches_pattern


matches_pattern = _load_matches_pattern()


def _patterns():
    with CONFIG_PATH.open() as f:
        return json.load(f)["files"]


@pytest.mark.parametrize(
    "filepath",
    [
        # Top-level shipped artifacts
        "install.sh",
        "validate",
        # Install-payload (fetched by install.sh into consumer .vendored/)
        "templates/install",
        "templates/check",
        "templates/audit",
        "templates/feedback",
        "templates/remove",
        "templates/config.json",
        "templates/lib/vendor-helpers.sh",
        "templates/github/workflows/check-vendor.yml",
        "templates/github/workflows/install-vendored.yml",
        # User-facing docs
        "docs/README.md",
        "docs/adoption.md",
        "docs/vendor-install-dir-guide.md",
        "AGENTS.md",
        "README.md",
    ],
)
def test_user_facing_file_is_covered(filepath):
    patterns = _patterns()
    assert any(matches_pattern(filepath, p) for p in patterns), (
        f"{filepath} is user-facing but no pattern in git-semver.json matches it"
    )


@pytest.mark.parametrize(
    "filepath",
    [
        # Repo-internal config / metadata
        "LICENSE",
        "VERSION",
        "medici.yaml",
        "pearls.yaml",
        "madreperla.yaml",
        # Tracker / session artifacts
        ".pearls/issues.jsonl",
        ".madreperla/sessions.jsonl",
        # Repo's own CI (consumers don't ship these)
        ".github/workflows/test.yml",
        # Tests aren't shipped to consumers
        "tests/test_install.py",
        # Vendor configs themselves
        ".vendored/configs/git-semver.json",
    ],
)
def test_internal_file_is_not_covered(filepath):
    patterns = _patterns()
    assert not any(matches_pattern(filepath, p) for p in patterns), (
        f"{filepath} is repo-internal — matching it would trigger spurious version bumps"
    )


def test_all_patterns_reference_real_files():
    """No stale patterns: each pattern should match at least one tracked file."""
    import subprocess

    tracked = subprocess.check_output(
        ["git", "ls-files"], cwd=ROOT, text=True
    ).splitlines()
    for pattern in _patterns():
        assert any(matches_pattern(f, pattern) for f in tracked), (
            f"pattern {pattern!r} matches no tracked file (stale entry)"
        )
