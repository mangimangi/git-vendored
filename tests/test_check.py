"""Tests for the vendored/check script."""

import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── Import check script as module ──────────────────────────────────────────

ROOT = Path(__file__).parent.parent


def _import_check():
    filepath = str(ROOT / "templates" / "check")
    loader = importlib.machinery.SourceFileLoader("vendored_check", filepath)
    spec = importlib.util.spec_from_loader("vendored_check", loader, origin=filepath)
    module = importlib.util.module_from_spec(spec)
    sys.modules["vendored_check"] = module
    spec.loader.exec_module(module)
    return module


check = _import_check()


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """Create a temporary directory with .vendored/ and chdir into it."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".vendored").mkdir()
    return tmp_path


@pytest.fixture
def make_config(tmp_repo):
    """Write a .vendored/config.json."""
    def _make(config_dict):
        config_path = tmp_repo / ".vendored" / "config.json"
        config_path.write_text(json.dumps(config_dict, indent=2) + "\n")
        return str(config_path)
    return _make


SAMPLE_CONFIG = {
    "vendors": {
        "git-vendored": {
            "repo": "mangimangi/git-vendored",
            "install_branch": "chore/install-git-vendored",
            "protected": [
                ".vendored/**",
                ".github/workflows/install-vendored.yml",
                ".github/workflows/check-vendor.yml"
            ],
            "allowed": [".vendored/config.json", ".vendored/.version"]
        },
        "pearls": {
            "repo": "mangimangi/pearls",
            "private": True,
            "install_branch": "chore/install-pearls",
            "protected": [".pearls/**"],
            "allowed": [
                ".pearls/issues.jsonl",
                ".pearls/config.json",
                ".pearls/.prl-version",
                ".pearls/archive/*.jsonl"
            ]
        }
    }
}


# ── Tests: matches_any_pattern ─────────────────────────────────────────────

class TestMatchesAnyPattern:
    def test_exact_match(self):
        assert check.matches_any_pattern(".vendored/config.json", [".vendored/config.json"])

    def test_no_match(self):
        assert not check.matches_any_pattern("README.md", [".vendored/**"])

    def test_glob_star(self):
        assert check.matches_any_pattern(".vendored/install", [".vendored/*"])

    def test_double_star_nested(self):
        assert check.matches_any_pattern(".pearls/archive/old.jsonl", [".pearls/**"])

    def test_double_star_deep_nested(self):
        assert check.matches_any_pattern(".vendored/a/b/c.py", [".vendored/**"])

    def test_fnmatch_wildcard(self):
        assert check.matches_any_pattern(".pearls/archive/2024.jsonl", [".pearls/archive/*.jsonl"])

    def test_multiple_patterns(self):
        patterns = [".vendored/**", ".github/workflows/check-vendor.yml"]
        assert check.matches_any_pattern(".github/workflows/check-vendor.yml", patterns)
        assert check.matches_any_pattern(".vendored/install", patterns)
        assert not check.matches_any_pattern("src/main.py", patterns)


# ── Tests: check_vendor ────────────────────────────────────────────────────

class TestCheckVendor:
    def test_no_violations_unrelated_files(self):
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            ["src/main.py", "README.md"], "feature/something"
        )
        assert violations == []

    def test_violation_protected_file(self):
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            [".vendored/install", "README.md"], "feature/something"
        )
        assert ".vendored/install" in violations
        assert len(violations) == 1

    def test_allowed_file_not_violation(self):
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            [".vendored/config.json", ".vendored/.version"], "feature/something"
        )
        assert violations == []

    def test_skip_on_install_branch(self):
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            [".vendored/install", ".vendored/check"], "chore/install-git-vendored-v1.0"
        )
        assert violations == []

    def test_install_branch_only_skips_own_vendor(self):
        """A pearls install branch should NOT skip git-vendored checks."""
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            [".vendored/install"], "chore/install-pearls-v2.0"
        )
        assert ".vendored/install" in violations

    def test_pearls_allowed_files(self):
        vendor_config = SAMPLE_CONFIG["vendors"]["pearls"]
        violations = check.check_vendor(
            "pearls", vendor_config,
            [".pearls/issues.jsonl", ".pearls/config.json", ".pearls/.prl-version"],
            "feature/something"
        )
        assert violations == []

    def test_pearls_protected_file(self):
        vendor_config = SAMPLE_CONFIG["vendors"]["pearls"]
        violations = check.check_vendor(
            "pearls", vendor_config,
            [".pearls/prl.py", ".pearls/merge-driver.py"],
            "feature/something"
        )
        assert ".pearls/prl.py" in violations
        assert ".pearls/merge-driver.py" in violations

    def test_pearls_archive_allowed(self):
        vendor_config = SAMPLE_CONFIG["vendors"]["pearls"]
        violations = check.check_vendor(
            "pearls", vendor_config,
            [".pearls/archive/2024-01.jsonl"],
            "feature/something"
        )
        assert violations == []

    def test_workflow_file_protected(self):
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            [".github/workflows/install-vendored.yml"],
            "feature/something"
        )
        assert ".github/workflows/install-vendored.yml" in violations

    def test_mixed_violations_and_allowed(self):
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            [".vendored/config.json", ".vendored/install", ".vendored/check"],
            "feature/something"
        )
        assert ".vendored/config.json" not in violations
        assert ".vendored/install" in violations
        assert ".vendored/check" in violations

    def test_no_protected_patterns(self):
        vendor_config = {"repo": "owner/repo", "protected": [], "allowed": []}
        violations = check.check_vendor(
            "empty", vendor_config,
            [".anything/file.py"], "feature/something"
        )
        assert violations == []


# ── Tests: manifest-based protection ──────────────────────────────────────

class TestManifestProtection:
    def test_manifest_files_are_protected(self, tmp_repo):
        """When a manifest exists, its listed files are protected."""
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "my-tool.files").write_text(
            ".my-tool/script.sh\n.my-tool/config.json\n"
        )
        vendor_config = {
            "repo": "owner/my-tool",
            "install_branch": "chore/install-my-tool",
            "protected": [".my-tool/**"],
        }
        violations = check.check_vendor(
            "my-tool", vendor_config,
            [".my-tool/script.sh"], "feature/something"
        )
        assert ".my-tool/script.sh" in violations

    def test_manifest_allows_unlisted_files(self, tmp_repo):
        """Files not in manifest are NOT protected, even if inside vendor dir."""
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "my-tool.files").write_text(
            ".my-tool/script.sh\n"
        )
        vendor_config = {
            "repo": "owner/my-tool",
            "install_branch": "chore/install-my-tool",
            "protected": [".my-tool/**"],
        }
        violations = check.check_vendor(
            "my-tool", vendor_config,
            [".my-tool/user-config.json"], "feature/something"
        )
        assert violations == []

    def test_manifest_protects_manifest_files_themselves(self, tmp_repo):
        """The manifest files (.files, .version) should be protected."""
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "my-tool.files").write_text(".my-tool/script.sh\n")

        vendor_config = {
            "repo": "owner/my-tool",
            "install_branch": "chore/install-my-tool",
            "protected": [".my-tool/**"],
        }
        violations = check.check_vendor(
            "my-tool", vendor_config,
            [".vendored/manifests/my-tool.files"], "feature/something"
        )
        assert ".vendored/manifests/my-tool.files" in violations

    def test_manifest_skips_on_install_branch(self, tmp_repo):
        """Install branch bypass works with manifest-based protection too."""
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "my-tool.files").write_text(".my-tool/script.sh\n")

        vendor_config = {
            "repo": "owner/my-tool",
            "install_branch": "chore/install-my-tool",
            "protected": [".my-tool/**"],
        }
        violations = check.check_vendor(
            "my-tool", vendor_config,
            [".my-tool/script.sh"], "chore/install-my-tool-v2.0"
        )
        assert violations == []

    def test_no_manifest_falls_back_to_config(self, tmp_repo):
        """Without a manifest, check uses config 'protected' patterns."""
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            [".vendored/install"], "feature/something"
        )
        assert ".vendored/install" in violations

    def test_manifest_with_allowed_exceptions(self, tmp_repo):
        """Allowed list still applies even with manifest-based protection."""
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "my-tool.files").write_text(
            ".my-tool/script.sh\n.my-tool/config.json\n"
        )
        vendor_config = {
            "repo": "owner/my-tool",
            "install_branch": "chore/install-my-tool",
            "protected": [".my-tool/**"],
            "allowed": [".my-tool/config.json"],
        }
        violations = check.check_vendor(
            "my-tool", vendor_config,
            [".my-tool/config.json", ".my-tool/script.sh"], "feature/something"
        )
        # config.json is allowed, script.sh is not
        assert ".my-tool/config.json" not in violations
        assert ".my-tool/script.sh" in violations


# ── Tests: get_protected_files ────────────────────────────────────────────

class TestGetProtectedFiles:
    def test_returns_config_patterns_without_manifest(self, tmp_repo):
        vendor_config = {"protected": [".tool/**", ".github/workflows/tool.yml"]}
        result = check.get_protected_files("tool", vendor_config)
        assert result == [".tool/**", ".github/workflows/tool.yml"]

    def test_returns_manifest_files_with_manifest(self, tmp_repo):
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(
            ".tool/script.sh\n.tool/lib.py\n"
        )
        vendor_config = {"protected": [".tool/**"]}
        result = check.get_protected_files("tool", vendor_config)
        assert ".tool/script.sh" in result
        assert ".tool/lib.py" in result
        assert ".vendored/manifests/tool.files" in result
        assert ".vendored/manifests/tool.version" in result
        # Config patterns should NOT be in the result
        assert ".tool/**" not in result


# ── Tests: load_config ─────────────────────────────────────────────────────

class TestLoadConfig:
    def test_loads_valid_config(self, make_config):
        make_config(SAMPLE_CONFIG)
        config = check.load_config()
        assert "vendors" in config
        assert "git-vendored" in config["vendors"]

    def test_missing_config_exits_clean(self, tmp_repo):
        with pytest.raises(SystemExit) as exc_info:
            check.load_config("/nonexistent/config.json")
        assert exc_info.value.code == 0

    def test_loads_per_vendor_configs(self, tmp_repo):
        """load_config() scans configs/ for per-vendor .json files (flat format)."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        gv_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        (configs_dir / "git-vendored.json").write_text(json.dumps(gv_config))
        config = check.load_config()
        assert "vendors" in config
        assert "git-vendored" in config["vendors"]
        assert config["vendors"]["git-vendored"]["repo"] == "mangimangi/git-vendored"

    def test_loads_per_vendor_configs_with_vendor_key(self, tmp_repo):
        """load_config() extracts registry from _vendor key."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        gv_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        vendor_file = {"_vendor": gv_config, "project_setting": True}
        (configs_dir / "git-vendored.json").write_text(json.dumps(vendor_file))
        config = check.load_config()
        assert config["vendors"]["git-vendored"]["repo"] == "mangimangi/git-vendored"
        # Project config should not leak into vendor registry
        assert "project_setting" not in config["vendors"]["git-vendored"]

    def test_empty_configs_dir_falls_back(self, tmp_repo, make_config):
        """Empty configs/ dir falls back to monolithic config.json."""
        make_config(SAMPLE_CONFIG)
        (tmp_repo / ".vendored" / "configs").mkdir(parents=True)
        config = check.load_config()
        assert "git-vendored" in config["vendors"]


# ── Tests: get_branch_name ─────────────────────────────────────────────────

class TestGetBranchName:
    def test_github_head_ref(self, monkeypatch):
        monkeypatch.setenv("GITHUB_HEAD_REF", "feature/my-branch")
        assert check.get_branch_name() == "feature/my-branch"

    def test_fallback_to_git(self, monkeypatch):
        monkeypatch.delenv("GITHUB_HEAD_REF", raising=False)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="main\n"
            )
            branch = check.get_branch_name()
            assert branch == "main"


# ── Tests: get_staged_files ──────────────────────────────────────────────

class TestGetStagedFiles:
    def test_returns_staged_files(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=".vendored/install\nREADME.md\n"
            )
            files = check.get_staged_files()
            assert files == [".vendored/install", "README.md"]
            mock_run.assert_called_once_with(
                ["git", "diff", "--cached", "--name-only"],
                capture_output=True, text=True
            )

    def test_empty_staging_area(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="\n"
            )
            files = check.get_staged_files()
            assert files == []

    def test_git_failure_exits(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stderr="fatal: not a git repo"
            )
            with pytest.raises(SystemExit) as exc_info:
                check.get_staged_files()
            assert exc_info.value.code == 1


# ── Tests: install_hook ──────────────────────────────────────────────────

class TestInstallHook:
    def test_creates_symlink(self, tmp_repo):
        # Create the hook source
        hooks_dir = tmp_repo / ".vendored" / "hooks"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "pre-commit").write_text("#!/bin/bash\n")

        # Create .git/hooks directory
        git_hooks = tmp_repo / ".git" / "hooks"
        git_hooks.mkdir(parents=True)

        check.install_hook()

        hook_dst = git_hooks / "pre-commit"
        assert hook_dst.is_symlink()
        assert os.readlink(str(hook_dst)) == "../../.vendored/hooks/pre-commit"

    def test_overwrites_existing_file(self, tmp_repo):
        hooks_dir = tmp_repo / ".vendored" / "hooks"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "pre-commit").write_text("#!/bin/bash\n")

        git_hooks = tmp_repo / ".git" / "hooks"
        git_hooks.mkdir(parents=True)
        (git_hooks / "pre-commit").write_text("#!/bin/bash\nold hook\n")

        check.install_hook()

        hook_dst = git_hooks / "pre-commit"
        assert hook_dst.is_symlink()
        assert os.readlink(str(hook_dst)) == "../../.vendored/hooks/pre-commit"

    def test_overwrites_existing_symlink(self, tmp_repo):
        hooks_dir = tmp_repo / ".vendored" / "hooks"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "pre-commit").write_text("#!/bin/bash\n")

        git_hooks = tmp_repo / ".git" / "hooks"
        git_hooks.mkdir(parents=True)
        # Symlink to pearls hook (the scenario we're squashing)
        os.symlink("../../.pearls/hooks/pre-commit", str(git_hooks / "pre-commit"))

        check.install_hook()

        hook_dst = git_hooks / "pre-commit"
        assert hook_dst.is_symlink()
        assert os.readlink(str(hook_dst)) == "../../.vendored/hooks/pre-commit"

    def test_errors_when_hook_source_missing(self, tmp_repo):
        (tmp_repo / ".git" / "hooks").mkdir(parents=True)

        with pytest.raises(SystemExit) as exc_info:
            check.install_hook()
        assert exc_info.value.code == 1

    def test_creates_git_hooks_dir(self, tmp_repo):
        hooks_dir = tmp_repo / ".vendored" / "hooks"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "pre-commit").write_text("#!/bin/bash\n")

        # .git dir exists but no hooks subdir
        (tmp_repo / ".git").mkdir(exist_ok=True)

        check.install_hook()

        hook_dst = tmp_repo / ".git" / "hooks" / "pre-commit"
        assert hook_dst.is_symlink()
