"""Tests for the vendored/update script."""

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

# ── Import update script as module ────────────────────────────────────────

ROOT = Path(__file__).parent.parent


def _import_update():
    filepath = str(ROOT / "vendored" / "update")
    loader = importlib.machinery.SourceFileLoader("vendored_update", filepath)
    spec = importlib.util.spec_from_loader("vendored_update", loader, origin=filepath)
    module = importlib.util.module_from_spec(spec)
    sys.modules["vendored_update"] = module
    spec.loader.exec_module(module)
    return module


inst = _import_update()


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


SAMPLE_VENDOR = {
    "repo": "owner/tool",
    "install_branch": "chore/install-tool",
    "protected": [".tool/**"],
    "allowed": [".tool/config.json", ".tool/.version"]
}

PRIVATE_VENDOR = {
    "repo": "owner/private-tool",
    "private": True,
    "install_branch": "chore/install-private-tool",
    "protected": [".private-tool/**"],
    "allowed": [".private-tool/.version"]
}


# ── Tests: load_config ─────────────────────────────────────────────────────

class TestLoadConfig:
    def test_loads_valid_config(self, make_config):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        config = inst.load_config()
        assert "vendors" in config

    def test_missing_config_exits(self, tmp_repo):
        with pytest.raises(SystemExit) as exc_info:
            inst.load_config("/nonexistent/config.json")
        assert exc_info.value.code == 1


# ── Tests: get_auth_token ──────────────────────────────────────────────────

class TestGetAuthToken:
    def test_public_uses_github_token(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token-123")
        monkeypatch.delenv("VENDOR_PAT", raising=False)
        token = inst.get_auth_token(SAMPLE_VENDOR)
        assert token == "gh-token-123"

    def test_public_falls_back_to_gh_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "gh-token-456")
        monkeypatch.delenv("VENDOR_PAT", raising=False)
        token = inst.get_auth_token(SAMPLE_VENDOR)
        assert token == "gh-token-456"

    def test_private_uses_vendor_pat(self, monkeypatch):
        monkeypatch.setenv("VENDOR_PAT", "pat-secret-789")
        token = inst.get_auth_token(PRIVATE_VENDOR)
        assert token == "pat-secret-789"

    def test_private_missing_pat_exits(self, monkeypatch):
        monkeypatch.delenv("VENDOR_PAT", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            inst.get_auth_token(PRIVATE_VENDOR)
        assert exc_info.value.code == 1


# ── Tests: get_current_version ─────────────────────────────────────────────

class TestGetCurrentVersion:
    def test_reads_version_from_allowed(self, tmp_repo):
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / ".version").write_text("1.2.3\n")
        version = inst.get_current_version("tool", SAMPLE_VENDOR)
        assert version == "1.2.3"

    def test_reads_version_from_protected_dir(self, tmp_repo):
        vendor_config = {
            "protected": [".mytool/**"],
            "allowed": [".mytool/config.json"]
        }
        (tmp_repo / ".mytool").mkdir()
        (tmp_repo / ".mytool" / ".version").write_text("2.0.0\n")
        version = inst.get_current_version("mytool", vendor_config)
        assert version == "2.0.0"

    def test_returns_none_if_no_version_file(self, tmp_repo):
        version = inst.get_current_version("tool", SAMPLE_VENDOR)
        assert version is None


# ── Tests: resolve_version ─────────────────────────────────────────────────

class TestResolveVersion:
    def test_specific_version_returned(self):
        version = inst.resolve_version("tool", SAMPLE_VENDOR, "1.5.0", "token")
        assert version == "1.5.0"

    @patch("vendored_update._resolve_from_releases")
    def test_latest_uses_releases(self, mock_releases):
        mock_releases.return_value = "2.0.0"
        version = inst.resolve_version("tool", SAMPLE_VENDOR, "latest", "token")
        assert version == "2.0.0"

    @patch("vendored_update._resolve_from_releases")
    @patch("vendored_update._resolve_from_version_file")
    def test_fallback_to_version_file(self, mock_vf, mock_releases):
        mock_releases.return_value = None
        mock_vf.return_value = "1.0.0"
        version = inst.resolve_version("tool", SAMPLE_VENDOR, "latest", "token")
        assert version == "1.0.0"

    @patch("vendored_update._resolve_from_releases")
    @patch("vendored_update._resolve_from_version_file")
    def test_exits_if_cannot_resolve(self, mock_vf, mock_releases):
        mock_releases.return_value = None
        mock_vf.return_value = None
        with pytest.raises(SystemExit) as exc_info:
            inst.resolve_version("tool", SAMPLE_VENDOR, "latest", "token")
        assert exc_info.value.code == 1


# ── Tests: install_vendor ──────────────────────────────────────────────────

class TestInstallVendor:
    @patch("vendored_update.download_and_run_install")
    @patch("vendored_update.resolve_version")
    @patch("vendored_update.get_auth_token")
    def test_skip_when_current(self, mock_token, mock_resolve, mock_download, tmp_repo):
        mock_token.return_value = "token"
        mock_resolve.return_value = "1.0.0"
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / ".version").write_text("1.0.0")

        result = inst.install_vendor("tool", SAMPLE_VENDOR, "latest")
        assert result["changed"] is False
        assert result["old_version"] == "1.0.0"
        mock_download.assert_not_called()

    @patch("vendored_update.download_and_run_install")
    @patch("vendored_update.resolve_version")
    @patch("vendored_update.get_auth_token")
    def test_installs_new_version(self, mock_token, mock_resolve, mock_download, tmp_repo):
        mock_token.return_value = "token"
        mock_resolve.return_value = "2.0.0"
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / ".version").write_text("1.0.0")

        result = inst.install_vendor("tool", SAMPLE_VENDOR, "latest")
        assert result["changed"] is True
        assert result["old_version"] == "1.0.0"
        assert result["new_version"] == "2.0.0"
        mock_download.assert_called_once()

    @patch("vendored_update.download_and_run_install")
    @patch("vendored_update.resolve_version")
    @patch("vendored_update.get_auth_token")
    def test_fresh_install(self, mock_token, mock_resolve, mock_download, tmp_repo):
        mock_token.return_value = "token"
        mock_resolve.return_value = "1.0.0"

        result = inst.install_vendor("tool", SAMPLE_VENDOR, "latest")
        assert result["changed"] is True
        assert result["old_version"] == "none"
        assert result["new_version"] == "1.0.0"


# ── Tests: output_result ──────────────────────────────────────────────────

class TestOutputResult:
    def test_single_result_format(self, make_config, capsys, monkeypatch):
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        inst.output_result({
            "vendor": "tool",
            "old_version": "1.0.0",
            "new_version": "2.0.0",
            "changed": True,
        })
        out = capsys.readouterr().out
        assert "vendor=tool" in out
        assert "old_version=1.0.0" in out
        assert "new_version=2.0.0" in out
        assert "changed=true" in out

    def test_output_results_single(self, make_config, capsys, monkeypatch):
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        results = [{
            "vendor": "tool",
            "old_version": "1.0.0",
            "new_version": "2.0.0",
            "changed": True,
        }]
        inst.output_results(results)
        out = capsys.readouterr().out
        assert "vendor=tool" in out

    def test_output_results_multiple(self, capsys, monkeypatch):
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        results = [
            {"vendor": "a", "old_version": "1.0", "new_version": "2.0", "changed": True},
            {"vendor": "b", "old_version": "1.0", "new_version": "1.0", "changed": False},
        ]
        inst.output_results(results)
        out = capsys.readouterr().out
        assert "changed_count=1" in out
        assert "results=" in out


# ── Tests: write_github_output ────────────────────────────────────────────

class TestWriteGithubOutput:
    def test_writes_to_github_output_file(self, tmp_repo, monkeypatch):
        """When GITHUB_OUTPUT is set, key=value pairs are written to the file."""
        output_file = tmp_repo / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

        inst.write_github_output({"vendor": "tool", "changed": "true"})

        content = output_file.read_text()
        assert "vendor=tool\n" in content
        assert "changed=true\n" in content

    def test_no_file_when_env_unset(self, tmp_repo, monkeypatch):
        """When GITHUB_OUTPUT is not set, no file is written."""
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        output_file = tmp_repo / "github_output.txt"

        inst.write_github_output({"vendor": "tool"})

        assert not output_file.exists()

    def test_single_vendor_writes_github_output(self, make_config, tmp_repo, monkeypatch, capsys):
        """output_result writes to GITHUB_OUTPUT when env var is set."""
        output_file = tmp_repo / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})

        inst.output_result({
            "vendor": "tool",
            "old_version": "1.0.0",
            "new_version": "2.0.0",
            "changed": True,
        })

        content = output_file.read_text()
        assert "vendor=tool\n" in content
        assert "old_version=1.0.0\n" in content
        assert "new_version=2.0.0\n" in content
        assert "changed=true\n" in content
        assert "install_branch=chore/install-tool\n" in content

    def test_multi_vendor_writes_github_output(self, tmp_repo, monkeypatch, capsys):
        """output_results (multi) writes changed_vendors and changed_count to GITHUB_OUTPUT."""
        output_file = tmp_repo / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

        results = [
            {"vendor": "a", "old_version": "1.0", "new_version": "2.0", "changed": True},
            {"vendor": "b", "old_version": "1.0", "new_version": "1.0", "changed": False},
        ]
        inst.output_results(results)

        content = output_file.read_text()
        assert "changed_count=1\n" in content
        assert "changed=true\n" in content
        assert "changed_vendors=" in content
        # Parse the JSON
        for line in content.strip().split("\n"):
            if line.startswith("changed_vendors="):
                vendors_json = json.loads(line.split("=", 1)[1])
                assert len(vendors_json) == 1
                assert vendors_json[0]["vendor"] == "a"

    def test_appends_to_existing_file(self, tmp_repo, monkeypatch):
        """GITHUB_OUTPUT appends to existing content."""
        output_file = tmp_repo / "github_output.txt"
        output_file.write_text("existing=value\n")
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

        inst.write_github_output({"new_key": "new_value"})

        content = output_file.read_text()
        assert "existing=value\n" in content
        assert "new_key=new_value\n" in content


# ── Tests: get_pr_metadata ──────────────────────────────────────────────

class TestGetPrMetadata:
    def test_single_vendor_metadata(self, make_config):
        """Single vendor result — branch includes install_branch and version."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        meta = inst.get_pr_metadata(results)
        assert meta["branch"] == "chore/install-tool-v2.0.0"
        assert meta["title"] == "chore: install tool v2.0.0"
        assert "1.0.0" in meta["body"]
        assert "2.0.0" in meta["body"]

    def test_single_vendor_automerge_true(self, make_config):
        """Single vendor with automerge — metadata includes automerge=True."""
        vendor = dict(SAMPLE_VENDOR, automerge=True)
        make_config({"vendors": {"tool": vendor}})
        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        meta = inst.get_pr_metadata(results)
        assert meta["automerge"] is True

    def test_single_vendor_automerge_default(self, make_config):
        """Single vendor without automerge — defaults to False."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        meta = inst.get_pr_metadata(results)
        assert meta["automerge"] is False

    def test_multi_vendor_metadata(self, make_config):
        """Multiple vendors — title lists all changed vendors with versions."""
        make_config({"vendors": {"a": SAMPLE_VENDOR, "b": SAMPLE_VENDOR}})
        results = [
            {"vendor": "a", "old_version": "1.0", "new_version": "2.0", "changed": True},
            {"vendor": "b", "old_version": "1.0", "new_version": "3.0", "changed": True},
        ]
        meta = inst.get_pr_metadata(results)
        assert meta["branch"] == "chore/install-vendors"
        assert "a v2.0" in meta["title"]
        assert "b v3.0" in meta["title"]
        assert meta["automerge"] is False

    def test_multi_vendor_only_changed_in_title(self, make_config):
        """Multi-vendor mode — only changed vendors appear in title."""
        make_config({"vendors": {"a": SAMPLE_VENDOR, "b": SAMPLE_VENDOR}})
        results = [
            {"vendor": "a", "old_version": "1.0", "new_version": "2.0", "changed": True},
            {"vendor": "b", "old_version": "1.0", "new_version": "1.0", "changed": False},
        ]
        meta = inst.get_pr_metadata(results)
        assert "a v2.0" in meta["title"]
        assert "b" not in meta["title"]

    def test_no_changes_returns_none(self, make_config):
        """No vendors changed — returns None."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "1.0.0", "changed": False}]
        assert inst.get_pr_metadata(results) is None

    def test_fallback_install_branch(self, make_config):
        """Vendor without install_branch in config — uses default pattern."""
        vendor = {"repo": "owner/tool", "protected": [".tool/**"]}
        make_config({"vendors": {"tool": vendor}})
        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        meta = inst.get_pr_metadata(results)
        assert meta["branch"] == "chore/install-tool-v2.0.0"


# ── Tests: create_pull_request ───────────────────────────────────────────

class TestCreatePullRequest:
    def _mock_subprocess(self, pr_stdout="https://github.com/o/r/pull/1\n",
                         pr_returncode=0, pr_stderr="",
                         diff_returncode=1):
        """Build a side_effect function for subprocess.run mocking."""
        def side_effect(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "diff":
                return MagicMock(returncode=diff_returncode)
            if cmd[0] == "gh" and cmd[1] == "pr" and cmd[2] == "create":
                return MagicMock(
                    returncode=pr_returncode,
                    stdout=pr_stdout, stderr=pr_stderr,
                )
            if cmd[0] == "gh" and cmd[1] == "pr" and cmd[2] == "merge":
                return MagicMock(returncode=0)
            # git config, checkout, add, commit, push
            return MagicMock(returncode=0)
        return side_effect

    @patch("vendored_update.subprocess.run")
    def test_creates_pr_single_vendor(self, mock_run, make_config, monkeypatch):
        """Single vendor with changes — calls git and gh pr create."""
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        mock_run.side_effect = self._mock_subprocess()

        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        pr_url = inst.create_pull_request(results)
        assert pr_url == "https://github.com/o/r/pull/1"

        # Verify git commands were called
        calls = [c[0][0] for c in mock_run.call_args_list]
        git_cmds = [c for c in calls if c[0] == "git"]
        assert ["git", "config", "user.name", "github-actions[bot]"] in git_cmds
        assert any("checkout" in c for c in git_cmds)
        assert ["git", "add", "-A"] in git_cmds
        assert any("commit" in c for c in git_cmds)
        assert any("push" in c for c in git_cmds)

    @patch("vendored_update.subprocess.run")
    def test_no_changes_skips_pr(self, mock_run, make_config, capsys):
        """No vendors changed — prints message, no git/gh calls."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "1.0.0", "changed": False}]
        result = inst.create_pull_request(results)
        assert result is None
        out = capsys.readouterr().out
        assert "No vendor changes" in out
        mock_run.assert_not_called()

    @patch("vendored_update.subprocess.run")
    def test_no_staged_changes_returns_early(self, mock_run, make_config, monkeypatch, capsys):
        """Git diff --cached shows no changes — returns early after staging."""
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        mock_run.side_effect = self._mock_subprocess(diff_returncode=0)

        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        result = inst.create_pull_request(results)
        assert result is None
        out = capsys.readouterr().out
        assert "No changes to commit" in out

    @patch("vendored_update.subprocess.run")
    def test_pr_already_exists(self, mock_run, make_config, monkeypatch, capsys):
        """gh pr create fails with 'already exists' — exits gracefully."""
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        mock_run.side_effect = self._mock_subprocess(
            pr_returncode=1, pr_stderr="already exists for pull request",
            pr_stdout="",
        )

        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        result = inst.create_pull_request(results)
        assert result is None
        out = capsys.readouterr().out
        assert "PR already exists" in out

    @patch("vendored_update.subprocess.run")
    def test_pr_create_failure_exits(self, mock_run, make_config, monkeypatch):
        """gh pr create fails with unexpected error — exits with code 1."""
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        mock_run.side_effect = self._mock_subprocess(
            pr_returncode=1, pr_stderr="network error", pr_stdout="",
        )

        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        with pytest.raises(SystemExit) as exc_info:
            inst.create_pull_request(results)
        assert exc_info.value.code == 1

    @patch("vendored_update.subprocess.run")
    def test_automerge_when_enabled(self, mock_run, make_config, monkeypatch):
        """Vendor with automerge: true — calls gh pr merge."""
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        vendor = dict(SAMPLE_VENDOR, automerge=True)
        make_config({"vendors": {"tool": vendor}})
        mock_run.side_effect = self._mock_subprocess()

        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        inst.create_pull_request(results)

        merge_calls = [c for c in mock_run.call_args_list
                       if c[0][0][0:3] == ["gh", "pr", "merge"]]
        assert len(merge_calls) == 1

    @patch("vendored_update.subprocess.run")
    def test_no_automerge_by_default(self, mock_run, make_config, monkeypatch):
        """Vendor without automerge — does not call gh pr merge."""
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        mock_run.side_effect = self._mock_subprocess()

        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        inst.create_pull_request(results)

        merge_calls = [c for c in mock_run.call_args_list
                       if c[0][0][0:3] == ["gh", "pr", "merge"]]
        assert len(merge_calls) == 0

    @patch("vendored_update.subprocess.run")
    def test_uses_github_token_for_gh(self, mock_run, make_config, monkeypatch):
        """PR creation uses GITHUB_TOKEN (not VENDOR_PAT) for gh CLI."""
        monkeypatch.setenv("GITHUB_TOKEN", "repo-token")
        monkeypatch.setenv("GH_TOKEN", "vendor-pat")
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        mock_run.side_effect = self._mock_subprocess()

        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        inst.create_pull_request(results)

        # Find the gh pr create call and check its env
        pr_create_calls = [c for c in mock_run.call_args_list
                           if c[0][0][0:3] == ["gh", "pr", "create"]]
        assert len(pr_create_calls) == 1
        env = pr_create_calls[0][1].get("env", {})
        assert env.get("GH_TOKEN") == "repo-token"
