"""Tests for hook discovery, orchestrator generation, and settings.json merge."""

import importlib.machinery
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Import install script as module ───────────────────────────────────────

ROOT = Path(__file__).parent.parent


def _import_install():
    filepath = str(ROOT / "templates" / "install")
    loader = importlib.machinery.SourceFileLoader("vendored_install_hooks", filepath)
    spec = importlib.util.spec_from_loader("vendored_install_hooks", loader,
                                           origin=filepath)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = filepath
    sys.modules["vendored_install_hooks"] = module
    spec.loader.exec_module(module)
    return module


inst = _import_install()


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """Create a temporary directory with .vendored/ structure and chdir into it."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".vendored" / "pkg").mkdir(parents=True)
    (tmp_path / ".vendored" / "manifests").mkdir(parents=True)
    return tmp_path


def _create_hook(tmp_path: Path, vendor: str, hook_name: str,
                 content: str = "#!/bin/bash\nexit 0\n") -> Path:
    """Create a hook script file for a vendor."""
    hook_dir = tmp_path / ".vendored" / "pkg" / vendor / "hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)
    hook_file = hook_dir / hook_name
    hook_file.write_text(content)
    hook_file.chmod(hook_file.stat().st_mode | stat.S_IEXEC)
    return hook_file


def _write_deps(tmp_path: Path, vendor: str, deps: list[str]) -> None:
    """Write a .deps file for a vendor."""
    deps_path = tmp_path / ".vendored" / "manifests" / f"{vendor}.deps"
    deps_path.write_text("\n".join(deps) + "\n")


SAMPLE_VENDORS = {
    "alpha": {"repo": "owner/alpha"},
    "beta": {"repo": "owner/beta"},
    "gamma": {"repo": "owner/gamma"},
}


# ── Tests: discover_vendor_hooks (gv-3adc.1) ─────────────────────────────

class TestDiscoverVendorHooks:
    def test_discovers_hooks_across_vendors(self, tmp_repo):
        """Discovers hooks in multiple vendor packages."""
        _create_hook(tmp_repo, "alpha", "session-start.sh")
        _create_hook(tmp_repo, "beta", "session-start.sh")
        _create_hook(tmp_repo, "beta", "session-resume.sh")

        result = inst.discover_vendor_hooks(SAMPLE_VENDORS)
        assert len(result) == 2
        names = [name for name, _ in result]
        assert "alpha" in names
        assert "beta" in names
        # beta should have both hooks
        beta_hooks = dict(result)["beta"]
        assert "session-start.sh" in beta_hooks
        assert "session-resume.sh" in beta_hooks

    def test_returns_empty_when_no_hooks(self, tmp_repo):
        """Returns empty list when no vendors have hooks."""
        result = inst.discover_vendor_hooks(SAMPLE_VENDORS)
        assert result == []

    def test_respects_dependency_order(self, tmp_repo):
        """Vendors ordered by deps: beta depends on alpha → alpha first."""
        _create_hook(tmp_repo, "alpha", "session-start.sh")
        _create_hook(tmp_repo, "beta", "session-start.sh")
        _write_deps(tmp_repo, "beta", ["alpha"])

        result = inst.discover_vendor_hooks(SAMPLE_VENDORS)
        names = [name for name, _ in result]
        assert names.index("alpha") < names.index("beta")

    def test_alphabetical_tiebreak(self, tmp_repo):
        """Unrelated vendors use alphabetical tiebreak."""
        _create_hook(tmp_repo, "gamma", "session-start.sh")
        _create_hook(tmp_repo, "alpha", "session-start.sh")
        _create_hook(tmp_repo, "beta", "session-start.sh")

        result = inst.discover_vendor_hooks(SAMPLE_VENDORS)
        names = [name for name, _ in result]
        assert names == ["alpha", "beta", "gamma"]

    def test_partial_hooks(self, tmp_repo):
        """Vendor with only session-start.sh (no session-resume.sh) is included."""
        _create_hook(tmp_repo, "alpha", "session-start.sh")

        result = inst.discover_vendor_hooks(SAMPLE_VENDORS)
        assert len(result) == 1
        name, hooks = result[0]
        assert name == "alpha"
        assert "session-start.sh" in hooks
        assert "session-resume.sh" not in hooks

    def test_errors_on_dependency_cycles(self, tmp_repo):
        """Circular deps cause SystemExit."""
        _create_hook(tmp_repo, "alpha", "session-start.sh")
        _create_hook(tmp_repo, "beta", "session-start.sh")
        _write_deps(tmp_repo, "alpha", ["beta"])
        _write_deps(tmp_repo, "beta", ["alpha"])

        with pytest.raises(SystemExit):
            inst.discover_vendor_hooks(SAMPLE_VENDORS)

    def test_skips_vendors_without_hooks_dir(self, tmp_repo):
        """Vendors without a hooks/ directory are skipped."""
        # alpha has no hooks dir at all
        (tmp_repo / ".vendored" / "pkg" / "alpha").mkdir(parents=True)
        _create_hook(tmp_repo, "beta", "session-start.sh")

        result = inst.discover_vendor_hooks(SAMPLE_VENDORS)
        assert len(result) == 1
        assert result[0][0] == "beta"

    def test_post_install_hook_discovered(self, tmp_repo):
        """post-install.sh is also discovered."""
        _create_hook(tmp_repo, "alpha", "post-install.sh")

        result = inst.discover_vendor_hooks(SAMPLE_VENDORS)
        assert len(result) == 1
        assert "post-install.sh" in result[0][1]


# ── Tests: run_post_install (gv-3adc.4) ──────────────────────────────────

class TestRunPostInstall:
    def test_runs_when_git_exists(self, tmp_repo):
        """post-install.sh runs when .git/ exists."""
        (tmp_repo / ".git").mkdir()
        stamp_content = "hello from post-install\n"
        _create_hook(tmp_repo, "alpha", "post-install.sh",
                     "#!/bin/bash\nset -euo pipefail\nexit 0\n")
        # Write version file
        (tmp_repo / ".vendored" / "manifests" / "alpha.version").write_text("1.0.0\n")

        inst.run_post_install("alpha", str(tmp_repo))
        # Should write stamp
        stamp = tmp_repo / ".vendored" / "manifests" / "alpha.post-installed"
        assert stamp.exists()
        assert stamp.read_text().strip() == "1.0.0"

    def test_skipped_when_no_git(self, tmp_repo):
        """post-install.sh skipped when .git/ does not exist."""
        _create_hook(tmp_repo, "alpha", "post-install.sh",
                     "#!/bin/bash\nexit 0\n")
        (tmp_repo / ".vendored" / "manifests" / "alpha.version").write_text("1.0.0\n")

        inst.run_post_install("alpha", str(tmp_repo))
        stamp = tmp_repo / ".vendored" / "manifests" / "alpha.post-installed"
        assert not stamp.exists()

    def test_skipped_when_no_hook(self, tmp_repo):
        """No post-install.sh → no action, no error."""
        (tmp_repo / ".git").mkdir()
        (tmp_repo / ".vendored" / "manifests" / "alpha.version").write_text("1.0.0\n")

        # Should not raise
        inst.run_post_install("alpha", str(tmp_repo))
        stamp = tmp_repo / ".vendored" / "manifests" / "alpha.post-installed"
        assert not stamp.exists()

    def test_stamp_written_on_success(self, tmp_repo):
        """Version stamp written after successful post-install."""
        (tmp_repo / ".git").mkdir()
        _create_hook(tmp_repo, "alpha", "post-install.sh",
                     "#!/bin/bash\nexit 0\n")
        (tmp_repo / ".vendored" / "manifests" / "alpha.version").write_text("2.0.0\n")

        inst.run_post_install("alpha", str(tmp_repo))
        stamp = tmp_repo / ".vendored" / "manifests" / "alpha.post-installed"
        assert stamp.read_text().strip() == "2.0.0"

    def test_stamp_not_written_on_failure(self, tmp_repo):
        """Version stamp NOT written when post-install fails."""
        (tmp_repo / ".git").mkdir()
        _create_hook(tmp_repo, "alpha", "post-install.sh",
                     "#!/bin/bash\nexit 1\n")
        (tmp_repo / ".vendored" / "manifests" / "alpha.version").write_text("1.0.0\n")

        inst.run_post_install("alpha", str(tmp_repo))
        stamp = tmp_repo / ".vendored" / "manifests" / "alpha.post-installed"
        assert not stamp.exists()

    def test_skipped_when_stamp_matches(self, tmp_repo):
        """Skips execution when stamp already matches current version."""
        (tmp_repo / ".git").mkdir()
        # This script would fail if actually run
        _create_hook(tmp_repo, "alpha", "post-install.sh",
                     "#!/bin/bash\nexit 1\n")
        (tmp_repo / ".vendored" / "manifests" / "alpha.version").write_text("1.0.0\n")
        (tmp_repo / ".vendored" / "manifests" / "alpha.post-installed").write_text("1.0.0\n")

        # Should skip (not fail) because stamp matches
        inst.run_post_install("alpha", str(tmp_repo))

    def test_reruns_when_stamp_differs(self, tmp_repo):
        """Re-runs when stamp differs from current version (upgrade)."""
        (tmp_repo / ".git").mkdir()
        _create_hook(tmp_repo, "alpha", "post-install.sh",
                     "#!/bin/bash\nexit 0\n")
        (tmp_repo / ".vendored" / "manifests" / "alpha.version").write_text("2.0.0\n")
        (tmp_repo / ".vendored" / "manifests" / "alpha.post-installed").write_text("1.0.0\n")

        inst.run_post_install("alpha", str(tmp_repo))
        stamp = tmp_repo / ".vendored" / "manifests" / "alpha.post-installed"
        assert stamp.read_text().strip() == "2.0.0"


# ── Tests: generate_orchestrator (gv-3adc.2) ─────────────────────────────

class TestGenerateOrchestrator:
    def test_generated_after_install(self, tmp_repo):
        """Orchestrator generated when vendor has hooks."""
        _create_hook(tmp_repo, "alpha", "session-start.sh")

        inst.generate_orchestrator(SAMPLE_VENDORS, str(tmp_repo))
        orch = tmp_repo / ".claude" / "hooks" / "vendored-session.sh"
        assert orch.exists()
        assert os.access(str(orch), os.X_OK)

    def test_correct_vendor_order(self, tmp_repo):
        """Orchestrator contains vendors in dependency order."""
        _create_hook(tmp_repo, "alpha", "session-start.sh")
        _create_hook(tmp_repo, "beta", "session-start.sh")
        _write_deps(tmp_repo, "beta", ["alpha"])

        inst.generate_orchestrator(SAMPLE_VENDORS, str(tmp_repo))
        orch = tmp_repo / ".claude" / "hooks" / "vendored-session.sh"
        content = orch.read_text()
        alpha_pos = content.index("alpha")
        beta_pos = content.index("beta")
        assert alpha_pos < beta_pos

    def test_noop_when_no_hooks(self, tmp_repo):
        """No orchestrator generated when no vendors have hooks."""
        inst.generate_orchestrator(SAMPLE_VENDORS, str(tmp_repo))
        orch = tmp_repo / ".claude" / "hooks" / "vendored-session.sh"
        assert not orch.exists()

    def test_remove_triggers_regeneration(self, tmp_repo):
        """Orchestrator regenerated without removed vendor."""
        _create_hook(tmp_repo, "alpha", "session-start.sh")
        _create_hook(tmp_repo, "beta", "session-start.sh")

        inst.generate_orchestrator(SAMPLE_VENDORS, str(tmp_repo))
        orch = tmp_repo / ".claude" / "hooks" / "vendored-session.sh"
        content = orch.read_text()
        assert "alpha" in content
        assert "beta" in content

        # Simulate removing beta (regenerate with only alpha)
        reduced = {"alpha": SAMPLE_VENDORS["alpha"]}
        inst.generate_orchestrator(reduced, str(tmp_repo))
        content = orch.read_text()
        assert "alpha" in content
        assert "beta" not in content

    def test_executable_permissions(self, tmp_repo):
        """Generated script has mode 755."""
        _create_hook(tmp_repo, "alpha", "session-start.sh")

        inst.generate_orchestrator(SAMPLE_VENDORS, str(tmp_repo))
        orch = tmp_repo / ".claude" / "hooks" / "vendored-session.sh"
        mode = orch.stat().st_mode
        assert mode & stat.S_IXUSR
        assert mode & stat.S_IXGRP
        assert mode & stat.S_IXOTH

    def test_post_install_safety_net(self, tmp_repo):
        """Generated script includes post-install safety net logic."""
        _create_hook(tmp_repo, "alpha", "session-start.sh")
        _create_hook(tmp_repo, "alpha", "post-install.sh")

        inst.generate_orchestrator(SAMPLE_VENDORS, str(tmp_repo))
        orch = tmp_repo / ".claude" / "hooks" / "vendored-session.sh"
        content = orch.read_text()
        assert "post-install" in content.lower() or "post_install" in content

    def test_set_euo_pipefail(self, tmp_repo):
        """Generated script uses set -euo pipefail."""
        _create_hook(tmp_repo, "alpha", "session-start.sh")

        inst.generate_orchestrator(SAMPLE_VENDORS, str(tmp_repo))
        orch = tmp_repo / ".claude" / "hooks" / "vendored-session.sh"
        content = orch.read_text()
        assert "set -euo pipefail" in content

    def test_mode_argument_parsing(self, tmp_repo):
        """Orchestrator handles --start and --resume mode arguments."""
        _create_hook(tmp_repo, "alpha", "session-start.sh")
        _create_hook(tmp_repo, "alpha", "session-resume.sh")

        inst.generate_orchestrator(SAMPLE_VENDORS, str(tmp_repo))
        orch = tmp_repo / ".claude" / "hooks" / "vendored-session.sh"
        content = orch.read_text()
        assert "--start" in content
        assert "--resume" in content

    def test_removes_stale_orchestrator(self, tmp_repo):
        """Orchestrator removed when no hooks remain."""
        _create_hook(tmp_repo, "alpha", "session-start.sh")
        inst.generate_orchestrator(SAMPLE_VENDORS, str(tmp_repo))
        orch = tmp_repo / ".claude" / "hooks" / "vendored-session.sh"
        assert orch.exists()

        # Remove hook files, regenerate with empty vendor set
        inst.generate_orchestrator({}, str(tmp_repo))
        assert not orch.exists()


# ── Tests: merge_settings_json (gv-3adc.3) ───────────────────────────────

class TestMergeSettingsJson:
    def test_creates_from_scratch(self, tmp_repo):
        """Creates settings.json when absent."""
        _create_hook(tmp_repo, "alpha", "session-start.sh")
        inst.generate_orchestrator(SAMPLE_VENDORS, str(tmp_repo))

        inst.merge_settings_json(str(tmp_repo), has_hooks=True)
        settings_path = tmp_repo / ".claude" / "settings.json"
        assert settings_path.exists()
        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings
        assert "SessionStart" in settings["hooks"]

    def test_preserves_non_vendor_hooks(self, tmp_repo):
        """Preserves user-defined hooks in SessionStart."""
        claude_dir = tmp_repo / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        existing = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "hooks": [{"type": "command", "command": "echo hello"}]
                    }
                ]
            }
        }
        (claude_dir / "settings.json").write_text(json.dumps(existing, indent=2) + "\n")

        _create_hook(tmp_repo, "alpha", "session-start.sh")
        inst.generate_orchestrator(SAMPLE_VENDORS, str(tmp_repo))
        inst.merge_settings_json(str(tmp_repo), has_hooks=True)

        settings = json.loads((claude_dir / "settings.json").read_text())
        commands = []
        for entry in settings["hooks"]["SessionStart"]:
            for h in entry.get("hooks", []):
                commands.append(h.get("command", ""))
        assert any("echo hello" in c for c in commands)
        assert any("vendored-session" in c for c in commands)

    def test_preserves_other_top_level_keys(self, tmp_repo):
        """Preserves permissions, custom keys, etc."""
        claude_dir = tmp_repo / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        existing = {
            "permissions": {"allow": ["Read"]},
            "custom_key": "preserved"
        }
        (claude_dir / "settings.json").write_text(json.dumps(existing, indent=2) + "\n")

        _create_hook(tmp_repo, "alpha", "session-start.sh")
        inst.generate_orchestrator(SAMPLE_VENDORS, str(tmp_repo))
        inst.merge_settings_json(str(tmp_repo), has_hooks=True)

        settings = json.loads((claude_dir / "settings.json").read_text())
        assert settings["permissions"] == {"allow": ["Read"]}
        assert settings["custom_key"] == "preserved"

    def test_idempotent_replacement(self, tmp_repo):
        """Running merge twice doesn't duplicate vendored entries."""
        _create_hook(tmp_repo, "alpha", "session-start.sh")
        inst.generate_orchestrator(SAMPLE_VENDORS, str(tmp_repo))

        inst.merge_settings_json(str(tmp_repo), has_hooks=True)
        inst.merge_settings_json(str(tmp_repo), has_hooks=True)

        settings_path = tmp_repo / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text())
        vendored_entries = [
            e for e in settings["hooks"]["SessionStart"]
            if any("vendored-session" in h.get("command", "")
                   for h in e.get("hooks", []))
        ]
        assert len(vendored_entries) == 2  # one --start, one --resume

    def test_removes_entries_when_no_hooks(self, tmp_repo):
        """Removes vendored entries when no vendors have hooks."""
        claude_dir = tmp_repo / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        existing = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "hooks": [{
                            "type": "command",
                            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/vendored-session.sh --start"
                        }]
                    },
                    {
                        "matcher": "startup",
                        "hooks": [{"type": "command", "command": "echo keep"}]
                    }
                ]
            }
        }
        (claude_dir / "settings.json").write_text(json.dumps(existing, indent=2) + "\n")

        inst.merge_settings_json(str(tmp_repo), has_hooks=False)

        settings = json.loads((claude_dir / "settings.json").read_text())
        for entry in settings["hooks"]["SessionStart"]:
            for h in entry.get("hooks", []):
                assert "vendored-session" not in h.get("command", "")
        # Non-vendor entry preserved
        assert len(settings["hooks"]["SessionStart"]) == 1

    def test_handles_empty_settings(self, tmp_repo):
        """Handles empty/malformed settings.json gracefully."""
        claude_dir = tmp_repo / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "settings.json").write_text("{}\n")

        _create_hook(tmp_repo, "alpha", "session-start.sh")
        inst.generate_orchestrator(SAMPLE_VENDORS, str(tmp_repo))
        inst.merge_settings_json(str(tmp_repo), has_hooks=True)

        settings = json.loads((claude_dir / "settings.json").read_text())
        assert "hooks" in settings

    def test_handles_malformed_json(self, tmp_repo):
        """Treats unreadable settings.json as empty."""
        claude_dir = tmp_repo / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "settings.json").write_text("not json\n")

        _create_hook(tmp_repo, "alpha", "session-start.sh")
        inst.generate_orchestrator(SAMPLE_VENDORS, str(tmp_repo))
        inst.merge_settings_json(str(tmp_repo), has_hooks=True)

        settings = json.loads((claude_dir / "settings.json").read_text())
        assert "hooks" in settings
