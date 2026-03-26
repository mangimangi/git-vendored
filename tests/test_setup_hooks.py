"""Tests for --setup-hooks command in the install script."""

import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def _import_install():
    filepath = str(ROOT / "templates" / "install")
    loader = importlib.machinery.SourceFileLoader("vendored_install_hooks", filepath)
    spec = importlib.util.spec_from_loader("vendored_install_hooks", loader, origin=filepath)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = filepath
    sys.modules["vendored_install_hooks"] = module
    spec.loader.exec_module(module)
    return module


inst = _import_install()


@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """Create a temporary directory with .vendored/ and chdir into it."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".vendored" / "hooks").mkdir(parents=True)
    return tmp_path


class TestAllAgents:
    def test_all_agents_contains_claude_and_codex(self):
        assert "claude" in inst.ALL_AGENTS
        assert "codex" in inst.ALL_AGENTS


class TestSetupHooksClaude:
    def test_creates_settings_json(self, tmp_repo):
        (tmp_repo / ".claude").mkdir()
        inst.setup_hooks_claude()
        settings_path = tmp_repo / ".claude" / "settings.json"
        assert settings_path.is_file()
        settings = json.loads(settings_path.read_text())
        hooks = settings["hooks"]["SessionStart"]
        matchers = [h["matcher"] for h in hooks]
        assert "startup" in matchers
        assert "resume" in matchers

    def test_startup_hook_points_to_orchestrator(self, tmp_repo):
        (tmp_repo / ".claude").mkdir()
        inst.setup_hooks_claude()
        settings = json.loads((tmp_repo / ".claude" / "settings.json").read_text())
        startup = [h for h in settings["hooks"]["SessionStart"]
                   if h["matcher"] == "startup"][0]
        cmd = startup["hooks"][0]["command"]
        assert ".vendored/hooks/vendored-session.sh" in cmd
        assert "--start" in cmd

    def test_resume_hook_points_to_orchestrator(self, tmp_repo):
        (tmp_repo / ".claude").mkdir()
        inst.setup_hooks_claude()
        settings = json.loads((tmp_repo / ".claude" / "settings.json").read_text())
        resume = [h for h in settings["hooks"]["SessionStart"]
                  if h["matcher"] == "resume"][0]
        cmd = resume["hooks"][0]["command"]
        assert ".vendored/hooks/vendored-session.sh" in cmd
        assert "--resume" in cmd

    def test_preserves_existing_settings(self, tmp_repo):
        (tmp_repo / ".claude").mkdir()
        existing = {"customSetting": True, "hooks": {"PreToolUse": []}}
        (tmp_repo / ".claude" / "settings.json").write_text(
            json.dumps(existing, indent=2) + "\n")
        inst.setup_hooks_claude()
        settings = json.loads((tmp_repo / ".claude" / "settings.json").read_text())
        assert settings["customSetting"] is True
        assert "PreToolUse" in settings["hooks"]
        assert "SessionStart" in settings["hooks"]

    def test_idempotent(self, tmp_repo):
        (tmp_repo / ".claude").mkdir()
        inst.setup_hooks_claude()
        first = json.loads((tmp_repo / ".claude" / "settings.json").read_text())
        inst.setup_hooks_claude()
        second = json.loads((tmp_repo / ".claude" / "settings.json").read_text())
        assert first == second

    def test_migrates_old_path(self, tmp_repo):
        (tmp_repo / ".claude").mkdir()
        # Write settings with old orchestrator path
        old_settings = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "hooks": [{
                            "type": "command",
                            "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/vendored-session.sh --start',
                            "statusMessage": "Configuring vendored tools...",
                        }],
                    },
                    {
                        "matcher": "resume",
                        "hooks": [{
                            "type": "command",
                            "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/vendored-session.sh --resume',
                            "statusMessage": "Configuring vendored tools...",
                        }],
                    },
                ],
            },
        }
        (tmp_repo / ".claude" / "settings.json").write_text(
            json.dumps(old_settings, indent=2) + "\n")
        inst.setup_hooks_claude()
        settings = json.loads((tmp_repo / ".claude" / "settings.json").read_text())
        hooks = settings["hooks"]["SessionStart"]
        # Should have exactly 2 entries (not duplicated)
        assert len(hooks) == 2
        for h in hooks:
            cmd = h["hooks"][0]["command"]
            assert ".vendored/hooks/vendored-session.sh" in cmd
            assert ".claude/hooks/vendored-session.sh" not in cmd


class TestSetupHooksCodex:
    def test_creates_config_toml(self, tmp_repo):
        inst.setup_hooks_codex()
        config_path = tmp_repo / ".codex" / "config.toml"
        assert config_path.is_file()
        content = config_path.read_text()
        assert "[hooks.session-start]" in content
        assert ".vendored/hooks/vendored-session.sh" in content

    def test_preserves_existing_config(self, tmp_repo):
        (tmp_repo / ".codex").mkdir()
        existing = "[settings]\nmodel = \"o4-mini\"\n"
        (tmp_repo / ".codex" / "config.toml").write_text(existing)
        inst.setup_hooks_codex()
        content = (tmp_repo / ".codex" / "config.toml").read_text()
        assert "model = \"o4-mini\"" in content
        assert "[hooks.session-start]" in content

    def test_idempotent(self, tmp_repo):
        inst.setup_hooks_codex()
        first = (tmp_repo / ".codex" / "config.toml").read_text()
        inst.setup_hooks_codex()
        second = (tmp_repo / ".codex" / "config.toml").read_text()
        assert first == second


class TestSetupHooks:
    def test_configures_both_agents_by_default(self, tmp_repo):
        inst.setup_hooks()
        assert (tmp_repo / ".claude" / "settings.json").is_file()
        assert (tmp_repo / ".codex" / "config.toml").is_file()

    def test_configures_both_even_without_dotdirs(self, tmp_repo):
        """Both agents should be configured even if .claude/ and .codex/ don't exist yet."""
        assert not (tmp_repo / ".claude").exists()
        assert not (tmp_repo / ".codex").exists()
        inst.setup_hooks()
        assert (tmp_repo / ".claude" / "settings.json").is_file()
        assert (tmp_repo / ".codex" / "config.toml").is_file()

    def test_explicit_claude(self, tmp_repo):
        inst.setup_hooks("claude")
        assert (tmp_repo / ".claude" / "settings.json").is_file()
        assert not (tmp_repo / ".codex" / "config.toml").exists()

    def test_explicit_codex(self, tmp_repo):
        inst.setup_hooks("codex")
        assert (tmp_repo / ".codex" / "config.toml").is_file()
        assert not (tmp_repo / ".claude").exists()

    def test_removes_old_orchestrator(self, tmp_repo):
        (tmp_repo / ".claude" / "hooks").mkdir(parents=True)
        old = tmp_repo / ".claude" / "hooks" / "vendored-session.sh"
        old.write_text("#!/bin/bash\n# old")
        inst.setup_hooks("claude")
        assert not old.is_file()

    def test_unknown_agent_errors(self, tmp_repo):
        with pytest.raises(SystemExit):
            inst.setup_hooks("unknown")


class TestOrchestratorTemplate:
    """Verify the orchestrator template has required properties."""

    def test_template_exists(self):
        path = ROOT / "templates" / "hooks" / "vendored-session.sh"
        assert path.is_file()

    def test_uses_git_rev_parse(self):
        content = (ROOT / "templates" / "hooks" / "vendored-session.sh").read_text()
        assert "git rev-parse --show-toplevel" in content

    def test_has_breadcrumb(self):
        content = (ROOT / "templates" / "hooks" / "vendored-session.sh").read_text()
        assert ".vendored/feedback" in content

    def test_has_start_and_resume(self):
        content = (ROOT / "templates" / "hooks" / "vendored-session.sh").read_text()
        assert "--start" in content
        assert "--resume" in content
