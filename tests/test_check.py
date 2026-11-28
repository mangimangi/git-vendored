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

@pytest.fixture(autouse=True)
def _no_cicd_source_branch(monkeypatch):
    """git-cicd sets CICD_SOURCE_BRANCH for the test job itself; the check
    reads it first, so a test sees it only when it sets it."""
    monkeypatch.delenv("CICD_SOURCE_BRANCH", raising=False)


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
                ".vendored/configs/pearls.json",
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
    def test_no_violations_unrelated_files(self, tmp_repo):
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            ["src/main.py", "README.md"], "feature/something"
        )
        assert violations == []

    def test_violation_protected_file(self, tmp_repo):
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            [".vendored/install", "README.md"], "feature/something"
        )
        assert ".vendored/install" in violations
        assert len(violations) == 1

    def test_allowed_file_not_violation(self, tmp_repo):
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            [".vendored/config.json", ".vendored/.version"], "feature/something"
        )
        assert violations == []

    def test_skip_on_install_branch(self, tmp_repo):
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            [".vendored/install", ".vendored/check"], "chore/install-git-vendored-v1.0"
        )
        assert violations == []

    def test_install_branch_only_skips_own_vendor(self, tmp_repo):
        """A pearls install branch should NOT skip git-vendored checks."""
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            [".vendored/install"], "chore/install-pearls-v2.0"
        )
        assert ".vendored/install" in violations

    def test_multi_vendor_install_branch_skips_every_vendor(self, tmp_repo):
        """The installer's own multi-vendor branch may change any vendor's files."""
        for name in ("git-vendored", "pearls"):
            vendor_config = SAMPLE_CONFIG["vendors"][name]
            protected = check.get_protected_files(name, vendor_config)
            violations = check.check_vendor(
                name, vendor_config, [".vendored/install"] + [
                    p for p in protected if "*" not in p],
                "chore/install-vendors",
            )
            assert violations == []

    def test_branch_merely_resembling_the_multi_vendor_branch_is_checked(self, tmp_repo):
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            [".vendored/install"], "feature/chore/install-vendors"
        )
        assert ".vendored/install" in violations

    def test_installer_and_check_agree_on_the_multi_vendor_branch(self):
        installer = (Path(__file__).parent.parent / "templates" / "install").read_text()
        assert f'MULTI_VENDOR_INSTALL_BRANCH = "{check.MULTI_VENDOR_INSTALL_BRANCH}"' in installer

    def test_pearls_allowed_files(self, tmp_repo):
        vendor_config = SAMPLE_CONFIG["vendors"]["pearls"]
        violations = check.check_vendor(
            "pearls", vendor_config,
            [".pearls/issues.jsonl", ".vendored/configs/pearls.json", ".pearls/.prl-version"],
            "feature/something"
        )
        assert violations == []

    def test_pearls_protected_file(self, tmp_repo):
        vendor_config = SAMPLE_CONFIG["vendors"]["pearls"]
        violations = check.check_vendor(
            "pearls", vendor_config,
            [".pearls/prl.py", ".pearls/merge-driver.py"],
            "feature/something"
        )
        assert ".pearls/prl.py" in violations
        assert ".pearls/merge-driver.py" in violations

    def test_pearls_archive_allowed(self, tmp_repo):
        vendor_config = SAMPLE_CONFIG["vendors"]["pearls"]
        violations = check.check_vendor(
            "pearls", vendor_config,
            [".pearls/archive/2024-01.jsonl"],
            "feature/something"
        )
        assert violations == []

    def test_workflow_file_protected(self, tmp_repo):
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            [".github/workflows/install-vendored.yml"],
            "feature/something"
        )
        assert ".github/workflows/install-vendored.yml" in violations

    def test_mixed_violations_and_allowed(self, tmp_repo):
        vendor_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        violations = check.check_vendor(
            "git-vendored", vendor_config,
            [".vendored/config.json", ".vendored/install", ".vendored/check"],
            "feature/something"
        )
        assert ".vendored/config.json" not in violations
        assert ".vendored/install" in violations
        assert ".vendored/check" in violations

    def test_no_protected_patterns(self, tmp_repo):
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

    def test_protects_commit_file(self, tmp_repo):
        """The recorded commit of the installed version is protected."""
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")
        result = check.get_protected_files("tool", {"protected": []})
        assert ".vendored/manifests/tool.commit" in result

    def test_protects_schema_file_when_present(self, tmp_repo):
        """Schema file is protected when it exists alongside manifest."""
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")
        (manifests_dir / "tool.schema").write_text('{"vendor": "tool"}\n')

        vendor_config = {"protected": [".tool/**"]}
        result = check.get_protected_files("tool", vendor_config)
        assert ".vendored/manifests/tool.schema" in result

    def test_no_schema_protection_when_missing(self, tmp_repo):
        """Schema file is not in protected list when it doesn't exist."""
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")

        vendor_config = {"protected": [".tool/**"]}
        result = check.get_protected_files("tool", vendor_config)
        assert ".vendored/manifests/tool.schema" not in result


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

    def test_prefers_registry_file_over_vendor_key(self, tmp_repo):
        """load_config() reads from .registry file when available."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        gv_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        vendor_file = {"_vendor": dict(gv_config, repo="old/repo")}
        (configs_dir / "git-vendored.json").write_text(json.dumps(vendor_file))

        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        registry = dict(gv_config, repo="new/repo")
        (manifests_dir / "git-vendored.registry").write_text(json.dumps(registry))

        config = check.load_config()
        assert config["vendors"]["git-vendored"]["repo"] == "new/repo"

    def test_falls_back_to_vendor_key_without_registry(self, tmp_repo):
        """load_config() falls back to _vendor when no .registry file."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        gv_config = SAMPLE_CONFIG["vendors"]["git-vendored"]
        vendor_file = {"_vendor": gv_config}
        (configs_dir / "git-vendored.json").write_text(json.dumps(vendor_file))

        config = check.load_config()
        assert config["vendors"]["git-vendored"]["repo"] == "mangimangi/git-vendored"

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


# ── Tests: ** patterns with a suffix ──────────────────────────────────────

class TestDoubleStarSuffixPatterns:
    def test_suffix_matches_file_directly_under_prefix(self):
        """'docs/**/*.md' covers docs/a.md: ** may stand for no directory."""
        assert check.matches_any_pattern("docs/a.md", ["docs/**/*.md"])

    def test_suffix_rejects_other_extension_nested(self):
        assert not check.matches_any_pattern("docs/a/b.txt", ["docs/**/*.md"])

    def test_suffix_rejects_other_extension_at_top(self):
        assert not check.matches_any_pattern("docs/b.txt", ["docs/**/*.md"])

    def test_trailing_slash_pattern_covers_everything_below(self):
        """'tools/**/' protects every file below tools/."""
        assert check.matches_any_pattern("tools/x", ["tools/**/"])

    def test_prefix_mismatch_is_not_a_match(self):
        assert not check.matches_any_pattern("other/a.md", ["docs/**/*.md"])


# ── Tests: get_changed_files ──────────────────────────────────────────────

class TestGetChangedFiles:
    def test_three_dot_diff(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="a\nb/c\n")
            assert check.get_changed_files("origin/main") == ["a", "b/c"]
            mock_run.assert_called_once_with(
                ["git", "diff", "--name-only", "origin/main...HEAD"],
                capture_output=True, text=True
            )

    def test_falls_back_to_two_ref_diff(self):
        """Without a merge base, the diff of the two refs is used."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=128, stdout="", stderr="no merge base"),
                MagicMock(returncode=0, stdout="x\n"),
            ]
            assert check.get_changed_files("base") == ["x"]
            assert mock_run.call_args_list[1].args[0] == [
                "git", "diff", "--name-only", "base", "HEAD"]

    def test_both_diffs_fail_exits_1(self, capsys):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128, stdout="", stderr="fatal: bad revision 'nope'\n")
            with pytest.raises(SystemExit) as exc_info:
                check.get_changed_files("nope")
        assert exc_info.value.code == 1
        assert ("Failed to get changed files: fatal: bad revision 'nope'"
                in capsys.readouterr().out)

    def test_no_changes(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="\n")
            assert check.get_changed_files("origin/main") == []


class TestGetBranchNameGitFailure:
    def test_git_failure_gives_empty_branch(self, monkeypatch):
        """A detached or broken checkout has no branch: nothing is skipped."""
        monkeypatch.delenv("GITHUB_HEAD_REF", raising=False)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="")
            assert check.get_branch_name() == ""


# ── Tests: main (end to end in a real git repo) ───────────────────────────

def _git(repo, *args):
    import subprocess
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=str(repo), check=True, capture_output=True, text=True,
    )


@pytest.fixture
def git_repo(tmp_repo, monkeypatch):
    """A git repo on main with one manifest-protected vendor, then a branch."""
    monkeypatch.delenv("GITHUB_HEAD_REF", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    _git(tmp_repo, "init", "-q", "-b", "main")
    configs = tmp_repo / ".vendored" / "configs"
    configs.mkdir()
    (configs / "tool.json").write_text(json.dumps({"_vendor": {
        "repo": "o/tool",
        "install_branch": "chore/install-tool",
        "allowed": [".vendored/pkg/tool/settings.json"],
    }}))
    manifests = tmp_repo / ".vendored" / "manifests"
    manifests.mkdir()
    (manifests / "tool.files").write_text(
        ".vendored/pkg/tool/run\n.vendored/pkg/tool/settings.json\n")
    (manifests / "tool.version").write_text("1.0.0\n")
    pkg = tmp_repo / ".vendored" / "pkg" / "tool"
    pkg.mkdir(parents=True)
    (pkg / "run").write_text("v1\n")
    (pkg / "settings.json").write_text("{}\n")
    (tmp_repo / "README.md").write_text("hi\n")
    _git(tmp_repo, "add", "-A")
    _git(tmp_repo, "commit", "-q", "-m", "base")
    _git(tmp_repo, "checkout", "-q", "-b", "feature")
    return tmp_repo


def _run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["check", *args])
    with pytest.raises(SystemExit) as exc_info:
        check.main()
    return exc_info.value.code


class TestMain:
    def test_no_vendors_configured(self, tmp_repo, make_config, monkeypatch, capsys):
        make_config({"vendors": {}})
        assert _run_main(monkeypatch) == 0
        assert "No vendors configured" in capsys.readouterr().out

    def test_protected_file_change_fails(self, git_repo, monkeypatch, capsys):
        (git_repo / ".vendored/pkg/tool/run").write_text("v2\n")
        _git(git_repo, "commit", "-q", "-am", "edit vendor file")
        assert _run_main(monkeypatch, "--base", "main") == 1
        out = capsys.readouterr().out
        assert "::error::Protected vendor files were modified!" in out
        assert "  tool:\n    - .vendored/pkg/tool/run\n" in out
        assert "These files are managed by their respective vendor install workflows." in out
        assert "To update them, use the install-vendored workflow instead." in out

    def test_manifest_file_itself_is_protected(self, git_repo, monkeypatch, capsys):
        (git_repo / ".vendored/manifests/tool.version").write_text("9.9.9\n")
        _git(git_repo, "commit", "-q", "-am", "bump version by hand")
        assert _run_main(monkeypatch, "--base", "main") == 1
        assert "- .vendored/manifests/tool.version" in capsys.readouterr().out

    def test_commit_file_is_protected(self, git_repo, monkeypatch, capsys):
        (git_repo / ".vendored/manifests/tool.commit").write_text("a" * 40 + "\n")
        _git(git_repo, "add", "-A")
        _git(git_repo, "commit", "-q", "-m", "record a commit by hand")
        assert _run_main(monkeypatch, "--base", "main") == 1
        assert "- .vendored/manifests/tool.commit" in capsys.readouterr().out

    def test_allowed_and_unprotected_changes_pass(self, git_repo, monkeypatch, capsys):
        (git_repo / ".vendored/pkg/tool/settings.json").write_text('{"a": 1}\n')
        (git_repo / "README.md").write_text("changed\n")
        _git(git_repo, "commit", "-q", "-am", "edit allowed + own files")
        assert _run_main(monkeypatch, "--base", "main") == 0
        assert "No vendor file violations detected." in capsys.readouterr().out

    def test_install_branch_may_change_protected_files(self, git_repo, monkeypatch, capsys):
        (git_repo / ".vendored/pkg/tool/run").write_text("v2\n")
        _git(git_repo, "commit", "-q", "-am", "install")
        monkeypatch.setenv("GITHUB_HEAD_REF", "chore/install-tool-v2")
        assert _run_main(monkeypatch, "--base", "main") == 0
        assert "No vendor file violations detected." in capsys.readouterr().out

    def test_install_branch_read_from_git_when_head_ref_unset(self, git_repo, monkeypatch, capsys):
        _git(git_repo, "checkout", "-q", "-b", "chore/install-tool-v2")
        (git_repo / ".vendored/pkg/tool/run").write_text("v2\n")
        _git(git_repo, "commit", "-q", "-am", "install")
        assert _run_main(monkeypatch, "--base", "main") == 0

    def test_no_changes(self, git_repo, monkeypatch, capsys):
        assert _run_main(monkeypatch, "--base", "main") == 0
        assert "No changed files" in capsys.readouterr().out

    def test_default_base_uses_github_base_ref(self, tmp_repo, make_config, monkeypatch):
        make_config(SAMPLE_CONFIG)
        monkeypatch.setenv("GITHUB_BASE_REF", "release")
        with patch.object(check, "get_changed_files", return_value=[]) as gcf:
            assert _run_main(monkeypatch) == 0
        gcf.assert_called_once_with("origin/release")

    def test_default_base_is_origin_main(self, tmp_repo, make_config, monkeypatch):
        make_config(SAMPLE_CONFIG)
        monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
        with patch.object(check, "get_changed_files", return_value=[]) as gcf:
            assert _run_main(monkeypatch) == 0
        gcf.assert_called_once_with("origin/main")

    def test_staged_mode_checks_the_index(self, git_repo, monkeypatch, capsys):
        (git_repo / ".vendored/pkg/tool/run").write_text("v2\n")
        _git(git_repo, "add", ".vendored/pkg/tool/run")
        assert _run_main(monkeypatch, "--staged") == 1
        assert "- .vendored/pkg/tool/run" in capsys.readouterr().out

    def test_staged_mode_ignores_unstaged_edits(self, git_repo, monkeypatch, capsys):
        (git_repo / ".vendored/pkg/tool/run").write_text("v2\n")
        assert _run_main(monkeypatch, "--staged") == 0
        assert "No changed files" in capsys.readouterr().out

    def test_unknown_base_exits_1(self, git_repo, monkeypatch, capsys):
        assert _run_main(monkeypatch, "--base", "no-such-ref") == 1
        assert "Failed to get changed files:" in capsys.readouterr().out


# ── Tests: CICD_SOURCE_BRANCH ─────────────────────────────────────────────

class TestCicdSourceBranch:
    def test_cicd_source_branch_is_read(self, monkeypatch):
        monkeypatch.delenv("GITHUB_HEAD_REF", raising=False)
        monkeypatch.setenv("CICD_SOURCE_BRANCH", "feature/x")
        with patch("subprocess.run") as mock_run:
            assert check.get_branch_name() == "feature/x"
        mock_run.assert_not_called()

    def test_cicd_source_branch_wins_over_github_head_ref(self, monkeypatch):
        monkeypatch.setenv("CICD_SOURCE_BRANCH", "chore/install-tool-v2")
        monkeypatch.setenv("GITHUB_HEAD_REF", "feature/other")
        assert check.get_branch_name() == "chore/install-tool-v2"

    def test_empty_cicd_source_branch_falls_back_to_github_head_ref(self, monkeypatch):
        monkeypatch.setenv("CICD_SOURCE_BRANCH", "")
        monkeypatch.setenv("GITHUB_HEAD_REF", "feature/pr")
        assert check.get_branch_name() == "feature/pr"

    def test_empty_cicd_source_branch_and_head_ref_fall_back_to_git(self, monkeypatch):
        monkeypatch.setenv("CICD_SOURCE_BRANCH", "")
        monkeypatch.setenv("GITHUB_HEAD_REF", "")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="local\n")
            assert check.get_branch_name() == "local"

    def test_install_branch_let_through_with_only_cicd_source_branch(
            self, git_repo, monkeypatch, capsys):
        """Under git-cicd no wrapper is needed: the install branch is let through."""
        (git_repo / ".vendored/pkg/tool/run").write_text("v2\n")
        _git(git_repo, "commit", "-q", "-am", "install")
        monkeypatch.setenv("CICD_SOURCE_BRANCH", "chore/install-tool-v1.2.3")
        assert _run_main(monkeypatch, "--base", "main") == 0
        assert "No vendor file violations detected." in capsys.readouterr().out

    def test_ordinary_cicd_source_branch_is_still_checked(
            self, git_repo, monkeypatch, capsys):
        """The checkout is on an install branch, but CICD_SOURCE_BRANCH says otherwise."""
        _git(git_repo, "checkout", "-q", "-b", "chore/install-tool-v2")
        (git_repo / ".vendored/pkg/tool/run").write_text("v2\n")
        _git(git_repo, "commit", "-q", "-am", "edit")
        monkeypatch.setenv("CICD_SOURCE_BRANCH", "feature/sneaky")
        assert _run_main(monkeypatch, "--base", "main") == 1
        assert "- .vendored/pkg/tool/run" in capsys.readouterr().out


# ── Tests: --base notes uncommitted / staged changes it did not read ──────

NOTE_PREFIX = "Note: "
NOTE_TAIL = ("not checked (only commits in main..HEAD are read); "
             "run with --staged to check staged files")


def _note_lines(out):
    return [line for line in out.splitlines() if line.startswith(NOTE_PREFIX)]


class TestBaseNotesUnreadChanges:
    def test_unstaged_edit_only(self, git_repo, monkeypatch, capsys):
        (git_repo / ".vendored/pkg/tool/run").write_text("v2\n")
        assert _run_main(monkeypatch, "--base", "main") == 0
        out = capsys.readouterr().out
        assert "No changed files" in out
        assert _note_lines(out) == [
            "Note: 1 uncommitted or staged file(s) " + NOTE_TAIL]

    def test_staged_only(self, git_repo, monkeypatch, capsys):
        (git_repo / ".vendored/pkg/tool/run").write_text("v2\n")
        (git_repo / "README.md").write_text("changed\n")
        _git(git_repo, "add", "-A")
        assert _run_main(monkeypatch, "--base", "main") == 0
        out = capsys.readouterr().out
        assert "No changed files" in out
        assert _note_lines(out) == [
            "Note: 2 uncommitted or staged file(s) " + NOTE_TAIL]

    def test_staged_and_unstaged_same_file_counted_once(self, git_repo, monkeypatch, capsys):
        (git_repo / "README.md").write_text("staged\n")
        _git(git_repo, "add", "README.md")
        (git_repo / "README.md").write_text("then edited again\n")
        assert _run_main(monkeypatch, "--base", "main") == 0
        assert _note_lines(capsys.readouterr().out) == [
            "Note: 1 uncommitted or staged file(s) " + NOTE_TAIL]

    def test_committed_violation_plus_uncommitted_file(self, git_repo, monkeypatch, capsys):
        (git_repo / ".vendored/pkg/tool/run").write_text("v2\n")
        _git(git_repo, "commit", "-q", "-am", "edit vendor file")
        # Uncommitted: another change to the committed file (in the range,
        # so not counted) and an edit outside it.
        (git_repo / ".vendored/pkg/tool/run").write_text("v3\n")
        (git_repo / "README.md").write_text("changed\n")
        assert _run_main(monkeypatch, "--base", "main") == 1
        out = capsys.readouterr().out
        assert _note_lines(out) == [
            "Note: 1 uncommitted or staged file(s) " + NOTE_TAIL]
        assert "::error::Protected vendor files were modified!" in out
        assert "  tool:\n    - .vendored/pkg/tool/run\n" in out

    def test_committed_clean_change_plus_uncommitted_file_still_passes(
            self, git_repo, monkeypatch, capsys):
        """The note is not a violation: the exit code is unchanged."""
        (git_repo / "README.md").write_text("changed\n")
        _git(git_repo, "commit", "-q", "-am", "edit readme")
        (git_repo / ".vendored/pkg/tool/run").write_text("v2\n")
        assert _run_main(monkeypatch, "--base", "main") == 0
        out = capsys.readouterr().out
        assert len(_note_lines(out)) == 1
        assert "No vendor file violations detected." in out

    def test_clean_tree_has_no_note(self, git_repo, monkeypatch, capsys):
        (git_repo / "README.md").write_text("changed\n")
        _git(git_repo, "commit", "-q", "-am", "edit readme")
        assert _run_main(monkeypatch, "--base", "main") == 0
        assert _note_lines(capsys.readouterr().out) == []

    def test_clean_tree_no_changes_has_no_note(self, git_repo, monkeypatch, capsys):
        assert _run_main(monkeypatch, "--base", "main") == 0
        out = capsys.readouterr().out
        assert "No changed files" in out
        assert _note_lines(out) == []

    def test_staged_mode_prints_no_note(self, git_repo, monkeypatch, capsys):
        (git_repo / "README.md").write_text("staged\n")
        _git(git_repo, "add", "README.md")
        (git_repo / ".vendored/pkg/tool/run").write_text("unstaged\n")
        assert _run_main(monkeypatch, "--staged") == 0
        assert _note_lines(capsys.readouterr().out) == []

    def test_note_names_the_default_base(self, git_repo, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_BASE_REF", "main")
        (git_repo / "README.md").write_text("changed\n")
        with patch.object(check, "get_changed_files", return_value=[]):
            assert _run_main(monkeypatch) == 0
        assert ("only commits in origin/main..HEAD are read"
                in capsys.readouterr().out)

    def test_git_failure_gives_no_note(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="")
            assert check.get_unread_local_files([]) == []
