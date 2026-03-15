"""Tests for vendored session hooks: discovery, orchestrator, settings, post-install."""

import importlib.machinery
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── Import install script as module ───────────────────────────────────────

ROOT = Path(__file__).parent.parent


def _import_install():
    # Reuse existing module if already loaded (avoids breaking patches in other test files)
    if "vendored_install" in sys.modules:
        return sys.modules["vendored_install"]
    filepath = str(ROOT / "templates" / "install")
    loader = importlib.machinery.SourceFileLoader("vendored_install", filepath)
    spec = importlib.util.spec_from_loader("vendored_install", loader, origin=filepath)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = filepath
    sys.modules["vendored_install"] = module
    spec.loader.exec_module(module)
    return module


inst = _import_install()


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """Create a temporary directory with .vendored/ structure and chdir into it."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".vendored").mkdir()
    (tmp_path / ".vendored" / "manifests").mkdir()
    (tmp_path / ".vendored" / "configs").mkdir()
    (tmp_path / ".vendored" / "pkg").mkdir()
    return tmp_path


@pytest.fixture
def make_vendor_hooks(tmp_repo):
    """Create hook files for a vendor in .vendored/pkg/<vendor>/hooks/."""
    def _make(vendor_name, hooks=None):
        if hooks is None:
            hooks = ["session-start.sh"]
        hooks_dir = tmp_repo / ".vendored" / "pkg" / vendor_name / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        for hook in hooks:
            hook_path = hooks_dir / hook
            hook_path.write_text(f"#!/bin/bash\necho '{vendor_name} {hook}'\n")
            hook_path.chmod(0o755)
        return hooks_dir
    return _make


@pytest.fixture
def make_vendor_config(tmp_repo):
    """Create a per-vendor config file."""
    def _make(vendor_name, config=None):
        if config is None:
            config = {
                "repo": f"owner/{vendor_name}",
                "install_branch": f"chore/install-{vendor_name}",
                "protected": [f".vendored/pkg/{vendor_name}/**"],
            }
        filepath = tmp_repo / ".vendored" / "configs" / f"{vendor_name}.json"
        filepath.write_text(json.dumps({"_vendor": config}))
        return filepath
    return _make


# ── Tests: discover_hooks (gv-3adc.1) ─────────────────────────────────────

class TestDiscoverHooks:
    def test_discovers_hooks_across_multiple_vendors(self, tmp_repo,
                                                      make_vendor_hooks,
                                                      make_vendor_config):
        """Discovers hooks across multiple vendors."""
        make_vendor_hooks("alpha", ["session-start.sh", "session-resume.sh"])
        make_vendor_hooks("beta", ["session-start.sh"])
        make_vendor_config("alpha")
        make_vendor_config("beta")

        vendors = {"alpha": {}, "beta": {}}
        result = inst.discover_hooks(vendors)
        assert len(result) == 2
        vendor_names = [name for name, _ in result]
        assert "alpha" in vendor_names
        assert "beta" in vendor_names

    def test_returns_empty_when_no_hooks(self, tmp_repo, make_vendor_config):
        """Returns empty list when no vendors have hooks."""
        make_vendor_config("alpha")
        vendors = {"alpha": {}}
        result = inst.discover_hooks(vendors)
        assert result == []

    def test_respects_dependency_order(self, tmp_repo, make_vendor_hooks,
                                        make_vendor_config):
        """Vendor A depends on B → B comes first."""
        make_vendor_hooks("vendor-a", ["session-start.sh"])
        make_vendor_hooks("vendor-b", ["session-start.sh"])
        make_vendor_config("vendor-a")
        make_vendor_config("vendor-b")
        # vendor-a depends on vendor-b
        (tmp_repo / ".vendored" / "manifests" / "vendor-a.deps").write_text("vendor-b\n")

        vendors = {"vendor-a": {}, "vendor-b": {}}
        result = inst.discover_hooks(vendors)
        names = [name for name, _ in result]
        assert names.index("vendor-b") < names.index("vendor-a")

    def test_alphabetical_tiebreak(self, tmp_repo, make_vendor_hooks,
                                    make_vendor_config):
        """Unrelated vendors sorted alphabetically."""
        make_vendor_hooks("zebra", ["session-start.sh"])
        make_vendor_hooks("alpha", ["session-start.sh"])
        make_vendor_hooks("middle", ["session-start.sh"])
        make_vendor_config("zebra")
        make_vendor_config("alpha")
        make_vendor_config("middle")

        vendors = {"zebra": {}, "alpha": {}, "middle": {}}
        result = inst.discover_hooks(vendors)
        names = [name for name, _ in result]
        assert names == ["alpha", "middle", "zebra"]

    def test_handles_partial_hooks(self, tmp_repo, make_vendor_hooks,
                                    make_vendor_config):
        """Vendor with only session-start.sh (no session-resume.sh) is discovered."""
        make_vendor_hooks("partial", ["session-start.sh"])
        make_vendor_config("partial")

        vendors = {"partial": {}}
        result = inst.discover_hooks(vendors)
        assert len(result) == 1
        name, hooks = result[0]
        assert name == "partial"
        assert "session-start.sh" in hooks
        assert "session-resume.sh" not in hooks

    def test_errors_on_dependency_cycle(self, tmp_repo, make_vendor_hooks,
                                         make_vendor_config):
        """Dependency cycle triggers sys.exit(1)."""
        make_vendor_hooks("a", ["session-start.sh"])
        make_vendor_hooks("b", ["session-start.sh"])
        make_vendor_config("a")
        make_vendor_config("b")
        (tmp_repo / ".vendored" / "manifests" / "a.deps").write_text("b\n")
        (tmp_repo / ".vendored" / "manifests" / "b.deps").write_text("a\n")

        vendors = {"a": {}, "b": {}}
        with pytest.raises(SystemExit) as exc_info:
            inst.discover_hooks(vendors)
        assert exc_info.value.code == 1

    def test_skips_vendors_without_hooks_dir(self, tmp_repo, make_vendor_config):
        """Vendors without hooks/ directory are skipped."""
        (tmp_repo / ".vendored" / "pkg" / "no-hooks").mkdir(parents=True)
        make_vendor_config("no-hooks")

        vendors = {"no-hooks": {}}
        result = inst.discover_hooks(vendors)
        assert result == []

    def test_hook_files_dict_contains_full_paths(self, tmp_repo,
                                                   make_vendor_hooks,
                                                   make_vendor_config):
        """Hook files dict maps hook name to full path."""
        make_vendor_hooks("tool", ["session-start.sh", "post-install.sh"])
        make_vendor_config("tool")

        vendors = {"tool": {}}
        result = inst.discover_hooks(vendors)
        _, hooks = result[0]
        assert hooks["session-start.sh"] == ".vendored/pkg/tool/hooks/session-start.sh"
        assert hooks["post-install.sh"] == ".vendored/pkg/tool/hooks/post-install.sh"


# ── Tests: post-install execution (gv-3adc.4) ─────────────────────────────

class TestRunPostInstall:
    def test_runs_when_git_exists(self, tmp_repo, make_vendor_hooks):
        """post-install.sh runs after install when .git/ exists."""
        (tmp_repo / ".git").mkdir()
        hooks_dir = make_vendor_hooks("tool", ["post-install.sh"])
        # Write a post-install that creates a marker file
        (hooks_dir / "post-install.sh").write_text(
            "#!/bin/bash\ntouch \"$PROJECT_DIR/.post-install-ran\"\n"
        )
        # Write version file
        (tmp_repo / ".vendored" / "manifests" / "tool.version").write_text("1.0.0\n")

        install_dir = str(tmp_repo / ".vendored" / "pkg" / "tool")
        result = inst.run_post_install("tool", install_dir, str(tmp_repo))
        assert result is True
        assert (tmp_repo / ".post-install-ran").exists()

    def test_skipped_when_no_git(self, tmp_repo, make_vendor_hooks):
        """post-install.sh skipped when .git/ does not exist."""
        make_vendor_hooks("tool", ["post-install.sh"])
        (tmp_repo / ".vendored" / "manifests" / "tool.version").write_text("1.0.0\n")

        install_dir = str(tmp_repo / ".vendored" / "pkg" / "tool")
        result = inst.run_post_install("tool", install_dir, str(tmp_repo))
        assert result is False

    def test_skipped_when_no_hook_file(self, tmp_repo):
        """post-install.sh skipped when no hook file present."""
        (tmp_repo / ".git").mkdir()
        (tmp_repo / ".vendored" / "pkg" / "tool").mkdir(parents=True)
        (tmp_repo / ".vendored" / "manifests" / "tool.version").write_text("1.0.0\n")

        install_dir = str(tmp_repo / ".vendored" / "pkg" / "tool")
        result = inst.run_post_install("tool", install_dir, str(tmp_repo))
        assert result is False

    def test_version_stamp_written_on_success(self, tmp_repo, make_vendor_hooks):
        """Version stamp written on success."""
        (tmp_repo / ".git").mkdir()
        hooks_dir = make_vendor_hooks("tool", ["post-install.sh"])
        (hooks_dir / "post-install.sh").write_text("#!/bin/bash\ntrue\n")
        (tmp_repo / ".vendored" / "manifests" / "tool.version").write_text("1.0.0\n")

        install_dir = str(tmp_repo / ".vendored" / "pkg" / "tool")
        inst.run_post_install("tool", install_dir, str(tmp_repo))

        stamp_path = tmp_repo / ".vendored" / "manifests" / "tool.post-installed"
        assert stamp_path.read_text().strip() == "1.0.0"

    def test_stamp_not_written_on_failure(self, tmp_repo, make_vendor_hooks):
        """Version stamp NOT written on failure."""
        (tmp_repo / ".git").mkdir()
        hooks_dir = make_vendor_hooks("tool", ["post-install.sh"])
        (hooks_dir / "post-install.sh").write_text("#!/bin/bash\nexit 1\n")
        (tmp_repo / ".vendored" / "manifests" / "tool.version").write_text("1.0.0\n")

        install_dir = str(tmp_repo / ".vendored" / "pkg" / "tool")
        result = inst.run_post_install("tool", install_dir, str(tmp_repo))
        assert result is False
        stamp_path = tmp_repo / ".vendored" / "manifests" / "tool.post-installed"
        assert not stamp_path.exists()

    def test_skips_when_stamp_matches(self, tmp_repo, make_vendor_hooks):
        """Skips execution when stamp matches current version."""
        (tmp_repo / ".git").mkdir()
        make_vendor_hooks("tool", ["post-install.sh"])
        (tmp_repo / ".vendored" / "manifests" / "tool.version").write_text("1.0.0\n")
        (tmp_repo / ".vendored" / "manifests" / "tool.post-installed").write_text("1.0.0\n")

        install_dir = str(tmp_repo / ".vendored" / "pkg" / "tool")
        result = inst.run_post_install("tool", install_dir, str(tmp_repo))
        assert result is False

    def test_reruns_when_stamp_differs(self, tmp_repo, make_vendor_hooks):
        """Re-runs when stamp differs from current version (upgrade)."""
        (tmp_repo / ".git").mkdir()
        hooks_dir = make_vendor_hooks("tool", ["post-install.sh"])
        (hooks_dir / "post-install.sh").write_text(
            "#!/bin/bash\ntouch \"$PROJECT_DIR/.post-install-reran\"\n"
        )
        (tmp_repo / ".vendored" / "manifests" / "tool.version").write_text("2.0.0\n")
        (tmp_repo / ".vendored" / "manifests" / "tool.post-installed").write_text("1.0.0\n")

        install_dir = str(tmp_repo / ".vendored" / "pkg" / "tool")
        result = inst.run_post_install("tool", install_dir, str(tmp_repo))
        assert result is True
        assert (tmp_repo / ".post-install-reran").exists()
        stamp = (tmp_repo / ".vendored" / "manifests" / "tool.post-installed").read_text().strip()
        assert stamp == "2.0.0"

    def test_env_vars_set(self, tmp_repo, make_vendor_hooks):
        """VENDOR_NAME, VENDOR_PKG_DIR, PROJECT_DIR are set for post-install."""
        (tmp_repo / ".git").mkdir()
        hooks_dir = make_vendor_hooks("tool", ["post-install.sh"])
        (hooks_dir / "post-install.sh").write_text(
            '#!/bin/bash\n'
            'echo "$VENDOR_NAME" > "$PROJECT_DIR/.env-check"\n'
            'echo "$VENDOR_PKG_DIR" >> "$PROJECT_DIR/.env-check"\n'
            'echo "$PROJECT_DIR" >> "$PROJECT_DIR/.env-check"\n'
        )
        (tmp_repo / ".vendored" / "manifests" / "tool.version").write_text("1.0.0\n")

        install_dir = str(tmp_repo / ".vendored" / "pkg" / "tool")
        inst.run_post_install("tool", install_dir, str(tmp_repo))

        lines = (tmp_repo / ".env-check").read_text().strip().split("\n")
        assert lines[0] == "tool"
        assert lines[1] == os.path.abspath(install_dir)
        assert lines[2] == os.path.abspath(str(tmp_repo))


# ── Tests: generate orchestrator (gv-3adc.2) ──────────────────────────────

class TestGenerateOrchestrator:
    def test_generated_after_install_with_hooks(self, tmp_repo,
                                                  make_vendor_hooks,
                                                  make_vendor_config):
        """Orchestrator generated after install with hook-bearing vendor."""
        make_vendor_hooks("tool", ["session-start.sh", "session-resume.sh"])
        make_vendor_config("tool")

        vendors = {"tool": {}}
        result = inst.write_orchestrator(vendors)
        assert result is True
        orch_path = tmp_repo / ".claude" / "hooks" / "vendored-session.sh"
        assert orch_path.exists()

    def test_orchestrator_contains_correct_vendor_order(self, tmp_repo,
                                                          make_vendor_hooks,
                                                          make_vendor_config):
        """Orchestrator contains correct vendor order."""
        make_vendor_hooks("alpha", ["session-start.sh"])
        make_vendor_hooks("beta", ["session-start.sh"])
        make_vendor_config("alpha")
        make_vendor_config("beta")
        # beta depends on alpha
        (tmp_repo / ".vendored" / "manifests" / "beta.deps").write_text("alpha\n")

        vendors = {"alpha": {}, "beta": {}}
        inst.write_orchestrator(vendors)

        content = (tmp_repo / ".claude" / "hooks" / "vendored-session.sh").read_text()
        alpha_pos = content.index("# ── alpha ──")
        beta_pos = content.index("# ── beta ──")
        assert alpha_pos < beta_pos

    def test_no_orchestrator_when_no_hooks(self, tmp_repo, make_vendor_config):
        """Orchestrator not generated when no vendors have hooks."""
        make_vendor_config("tool")
        vendors = {"tool": {}}
        result = inst.write_orchestrator(vendors)
        assert result is False
        assert not (tmp_repo / ".claude" / "hooks" / "vendored-session.sh").exists()

    def test_remove_triggers_regeneration(self, tmp_repo, make_vendor_hooks,
                                            make_vendor_config):
        """When last hook-bearing vendor is removed, orchestrator is removed."""
        make_vendor_hooks("tool", ["session-start.sh"])
        make_vendor_config("tool")

        # First generate the orchestrator
        vendors = {"tool": {}}
        inst.write_orchestrator(vendors)
        orch_path = tmp_repo / ".claude" / "hooks" / "vendored-session.sh"
        assert orch_path.exists()

        # Now regenerate with empty vendors (vendor was removed)
        inst.write_orchestrator({})
        assert not orch_path.exists()

    def test_orchestrator_is_executable(self, tmp_repo, make_vendor_hooks,
                                          make_vendor_config):
        """Generated script is executable (mode 755)."""
        make_vendor_hooks("tool", ["session-start.sh"])
        make_vendor_config("tool")

        vendors = {"tool": {}}
        inst.write_orchestrator(vendors)

        orch_path = tmp_repo / ".claude" / "hooks" / "vendored-session.sh"
        mode = os.stat(orch_path).st_mode
        assert mode & stat.S_IXUSR
        assert mode & stat.S_IXGRP
        assert mode & stat.S_IXOTH

    def test_orchestrator_has_shebang_and_pipefail(self, tmp_repo,
                                                      make_vendor_hooks,
                                                      make_vendor_config):
        """Generated script has shebang and set -euo pipefail."""
        make_vendor_hooks("tool", ["session-start.sh"])
        make_vendor_config("tool")

        vendors = {"tool": {}}
        inst.write_orchestrator(vendors)

        content = (tmp_repo / ".claude" / "hooks" / "vendored-session.sh").read_text()
        assert content.startswith("#!/bin/bash\n")
        assert "set -euo pipefail" in content

    def test_orchestrator_post_install_safety_net(self, tmp_repo,
                                                    make_vendor_hooks,
                                                    make_vendor_config):
        """Orchestrator includes post-install safety net function."""
        make_vendor_hooks("tool", ["session-start.sh", "post-install.sh"])
        make_vendor_config("tool")

        vendors = {"tool": {}}
        inst.write_orchestrator(vendors)

        content = (tmp_repo / ".claude" / "hooks" / "vendored-session.sh").read_text()
        assert "run_post_install_if_needed" in content

    def test_orchestrator_project_dir_derivation(self, tmp_repo,
                                                    make_vendor_hooks,
                                                    make_vendor_config):
        """PROJECT_DIR derived from script location."""
        make_vendor_hooks("tool", ["session-start.sh"])
        make_vendor_config("tool")

        vendors = {"tool": {}}
        inst.write_orchestrator(vendors)

        content = (tmp_repo / ".claude" / "hooks" / "vendored-session.sh").read_text()
        assert 'PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"' in content

    def test_orchestrator_mode_parsing(self, tmp_repo, make_vendor_hooks,
                                        make_vendor_config):
        """Orchestrator parses --start/--resume mode."""
        make_vendor_hooks("tool", ["session-start.sh", "session-resume.sh"])
        make_vendor_config("tool")

        vendors = {"tool": {}}
        inst.write_orchestrator(vendors)

        content = (tmp_repo / ".claude" / "hooks" / "vendored-session.sh").read_text()
        assert '"--resume"' in content
        assert '"--start"' in content
        assert 'MODE="start"' in content


# ── Tests: merge settings.json (gv-3adc.3) ────────────────────────────────

class TestMergeSettings:
    def test_creates_settings_from_scratch(self, tmp_repo, make_vendor_hooks,
                                             make_vendor_config):
        """Creates settings.json from scratch when absent."""
        make_vendor_hooks("tool", ["session-start.sh"])
        make_vendor_config("tool")

        vendors = {"tool": {}}
        inst.merge_settings(vendors)

        settings_path = tmp_repo / ".claude" / "settings.json"
        assert settings_path.exists()
        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings
        assert "SessionStart" in settings["hooks"]
        entries = settings["hooks"]["SessionStart"]
        assert len(entries) == 2
        assert entries[0]["matcher"] == "startup"
        assert entries[1]["matcher"] == "resume"

    def test_preserves_non_vendor_hooks(self, tmp_repo, make_vendor_hooks,
                                          make_vendor_config):
        """Preserves existing non-vendor hooks in SessionStart."""
        claude_dir = tmp_repo / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        existing = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "hooks": [{
                            "type": "command",
                            "command": "echo custom hook",
                        }]
                    }
                ]
            }
        }
        (claude_dir / "settings.json").write_text(json.dumps(existing, indent=2) + "\n")

        make_vendor_hooks("tool", ["session-start.sh"])
        make_vendor_config("tool")

        vendors = {"tool": {}}
        inst.merge_settings(vendors)

        settings = json.loads((claude_dir / "settings.json").read_text())
        entries = settings["hooks"]["SessionStart"]
        # First two are vendored, third is the custom hook
        assert len(entries) == 3
        assert entries[0]["matcher"] == "startup"
        assert "vendored-session.sh" in entries[0]["hooks"][0]["command"]
        assert entries[2]["hooks"][0]["command"] == "echo custom hook"

    def test_preserves_other_top_level_keys(self, tmp_repo, make_vendor_hooks,
                                              make_vendor_config):
        """Preserves other top-level keys (permissions, etc.)."""
        claude_dir = tmp_repo / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        existing = {
            "permissions": {"allow": ["Bash"]},
            "hooks": {"SessionStart": []}
        }
        (claude_dir / "settings.json").write_text(json.dumps(existing, indent=2) + "\n")

        make_vendor_hooks("tool", ["session-start.sh"])
        make_vendor_config("tool")

        vendors = {"tool": {}}
        inst.merge_settings(vendors)

        settings = json.loads((claude_dir / "settings.json").read_text())
        assert settings["permissions"] == {"allow": ["Bash"]}

    def test_replaces_stale_vendored_entries(self, tmp_repo, make_vendor_hooks,
                                               make_vendor_config):
        """Replaces stale vendored entries on regeneration (idempotent)."""
        claude_dir = tmp_repo / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        existing = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "hooks": [{
                            "type": "command",
                            "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/vendored-session.sh --start',
                        }]
                    },
                    {
                        "matcher": "resume",
                        "hooks": [{
                            "type": "command",
                            "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/vendored-session.sh --resume',
                        }]
                    },
                ]
            }
        }
        (claude_dir / "settings.json").write_text(json.dumps(existing, indent=2) + "\n")

        make_vendor_hooks("tool", ["session-start.sh"])
        make_vendor_config("tool")

        vendors = {"tool": {}}
        inst.merge_settings(vendors)

        settings = json.loads((claude_dir / "settings.json").read_text())
        entries = settings["hooks"]["SessionStart"]
        # Should still be exactly 2 entries (replaced, not duplicated)
        assert len(entries) == 2

    def test_removes_vendored_entries_when_no_hooks(self, tmp_repo, make_vendor_config):
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
                            "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/vendored-session.sh --start',
                        }]
                    },
                ]
            }
        }
        (claude_dir / "settings.json").write_text(json.dumps(existing, indent=2) + "\n")

        make_vendor_config("tool")
        vendors = {"tool": {}}
        inst.merge_settings(vendors)

        settings = json.loads((claude_dir / "settings.json").read_text())
        # hooks.SessionStart should be gone (no entries left)
        assert "SessionStart" not in settings.get("hooks", {})

    def test_handles_malformed_settings(self, tmp_repo, make_vendor_hooks,
                                          make_vendor_config):
        """Handles malformed/empty settings.json gracefully."""
        claude_dir = tmp_repo / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "settings.json").write_text("not valid json")

        make_vendor_hooks("tool", ["session-start.sh"])
        make_vendor_config("tool")

        vendors = {"tool": {}}
        inst.merge_settings(vendors)

        settings = json.loads((claude_dir / "settings.json").read_text())
        assert "hooks" in settings
        assert len(settings["hooks"]["SessionStart"]) == 2

    def test_hook_entry_format(self, tmp_repo, make_vendor_hooks,
                                 make_vendor_config):
        """Hook entries use correct command format with $CLAUDE_PROJECT_DIR."""
        make_vendor_hooks("tool", ["session-start.sh"])
        make_vendor_config("tool")

        vendors = {"tool": {}}
        inst.merge_settings(vendors)

        settings = json.loads((tmp_repo / ".claude" / "settings.json").read_text())
        start_entry = settings["hooks"]["SessionStart"][0]
        assert start_entry["matcher"] == "startup"
        hook = start_entry["hooks"][0]
        assert hook["type"] == "command"
        assert '"$CLAUDE_PROJECT_DIR"/.claude/hooks/vendored-session.sh --start' == hook["command"]
        assert hook["statusMessage"] == "Configuring vendored tools..."
