"""Tests for the unified templates/install script."""

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── Import install script as module ───────────────────────────────────────

ROOT = Path(__file__).parent.parent


def _import_install():
    filepath = str(ROOT / "templates" / "install")
    loader = importlib.machinery.SourceFileLoader("vendored_install", filepath)
    spec = importlib.util.spec_from_loader("vendored_install", loader, origin=filepath)
    module = importlib.util.module_from_spec(spec)
    sys.modules["vendored_install"] = module
    spec.loader.exec_module(module)
    return module


inst = _import_install()


# ── Fixtures ──────────────────────────────────────────────────────────────

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

EXISTING_VENDOR = {
    "repo": "owner/existing-tool",
    "install_branch": "chore/install-existing-tool",
    "protected": [".existing-tool/**"],
}


# ── Tests: load_config ────────────────────────────────────────────────────

class TestLoadConfig:
    def test_loads_valid_config(self, make_config):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        config = inst.load_config()
        assert "vendors" in config

    def test_missing_config_exits(self, tmp_repo):
        with pytest.raises(SystemExit) as exc_info:
            inst.load_config("/nonexistent/config.json")
        assert exc_info.value.code == 1


# ── Tests: get_auth_token ─────────────────────────────────────────────────

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

    def test_no_config_returns_env_token(self, monkeypatch):
        """get_auth_token with no vendor_config (add path)."""
        monkeypatch.setenv("GH_TOKEN", "my-token")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        token = inst.get_auth_token()
        assert token == "my-token"


# ── Tests: Pre-validation (add path) ──────────────────────────────────────

class TestPreValidate:
    @patch("vendored_install.subprocess.run")
    def test_repo_with_install_sh_passes(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="install.sh\n")
        inst.check_install_sh("owner/tool", "token")

    @patch("vendored_install.subprocess.run")
    def test_repo_without_install_sh_fails(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Not Found")
        with pytest.raises(SystemExit) as exc_info:
            inst.check_install_sh("owner/tool", "token")
        assert exc_info.value.code == 1

    @patch("vendored_install.subprocess.run")
    def test_repo_not_found_fails(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Not Found")
        with pytest.raises(SystemExit) as exc_info:
            inst.check_repo_exists("owner/nonexistent", "token")
        assert exc_info.value.code == 1

    @patch("vendored_install.subprocess.run")
    def test_version_resolvable_from_releases(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="v1.2.3\n")
        version = inst.resolve_version("tool", "owner/tool", "latest", "token")
        assert version == "1.2.3"

    @patch("vendored_install.subprocess.run")
    def test_version_resolvable_from_version_file(self, mock_run):
        import base64
        encoded = base64.b64encode(b"2.0.0\n").decode()

        def side_effect(cmd, **kwargs):
            if "releases/latest" in cmd[2]:
                return MagicMock(returncode=1, stdout="")
            if "contents/VERSION" in cmd[2]:
                return MagicMock(returncode=0, stdout=encoded + "\n")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = side_effect
        version = inst.resolve_version("tool", "owner/tool", "latest", "token")
        assert version == "2.0.0"

    @patch("vendored_install.subprocess.run")
    def test_version_not_resolvable_fails(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        with pytest.raises(SystemExit) as exc_info:
            inst.resolve_version("tool", "owner/tool", "latest", "token")
        assert exc_info.value.code == 1


# ── Tests: get_current_version ────────────────────────────────────────────

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


# ── Tests: SnapshotAndDiff (post-validation) ──────────────────────────────

class TestSnapshotAndDiff:
    def test_detects_new_config_entry(self):
        before = {"existing": EXISTING_VENDOR}
        after = {
            "existing": EXISTING_VENDOR,
            "new-tool": {"repo": "owner/new-tool", "protected": [".new-tool/**"], "install_branch": "chore/install-new-tool"},
        }
        key, entry = inst.find_new_entry(before, after)
        assert key == "new-tool"
        assert entry["repo"] == "owner/new-tool"

    def test_no_new_entry_fails(self):
        before = {"existing": EXISTING_VENDOR}
        after = {"existing": EXISTING_VENDOR}
        key, entry = inst.find_new_entry(before, after)
        assert key is None
        assert entry is None


# ── Tests: PostValidate ───────────────────────────────────────────────────

class TestPostValidate:
    def test_valid_entry_passes(self):
        entry = {
            "repo": "owner/tool",
            "protected": [".tool/**"],
            "install_branch": "chore/install-tool",
        }
        inst.validate_entry("tool", entry)

    def test_missing_repo_fails(self):
        entry = {"protected": [".tool/**"], "install_branch": "chore/install-tool"}
        with pytest.raises(SystemExit) as exc_info:
            inst.validate_entry("tool", entry)
        assert exc_info.value.code == 1

    def test_missing_protected_fails(self):
        entry = {"repo": "owner/tool", "install_branch": "chore/install-tool"}
        with pytest.raises(SystemExit) as exc_info:
            inst.validate_entry("tool", entry)
        assert exc_info.value.code == 1


# ── Tests: resolve_version ────────────────────────────────────────────────

class TestResolveVersion:
    def test_specific_version_returned(self):
        version = inst.resolve_version("tool", "owner/tool", "1.5.0", "token")
        assert version == "1.5.0"

    @patch("vendored_install._resolve_from_releases")
    def test_latest_uses_releases(self, mock_releases):
        mock_releases.return_value = "2.0.0"
        version = inst.resolve_version("tool", "owner/tool", "latest", "token")
        assert version == "2.0.0"

    @patch("vendored_install._resolve_from_releases")
    @patch("vendored_install._resolve_from_version_file")
    def test_fallback_to_version_file(self, mock_vf, mock_releases):
        mock_releases.return_value = None
        mock_vf.return_value = "1.0.0"
        version = inst.resolve_version("tool", "owner/tool", "latest", "token")
        assert version == "1.0.0"

    @patch("vendored_install._resolve_from_releases")
    @patch("vendored_install._resolve_from_version_file")
    def test_exits_if_cannot_resolve(self, mock_vf, mock_releases):
        mock_releases.return_value = None
        mock_vf.return_value = None
        with pytest.raises(SystemExit) as exc_info:
            inst.resolve_version("tool", "owner/tool", "latest", "token")
        assert exc_info.value.code == 1


# ── Tests: install_existing_vendor (update path) ─────────────────────────

class TestInstallExistingVendor:
    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.get_auth_token")
    def test_skip_when_current(self, mock_token, mock_resolve, mock_download, tmp_repo):
        mock_token.return_value = "token"
        mock_resolve.return_value = "1.0.0"
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / ".version").write_text("1.0.0")

        result = inst.install_existing_vendor("tool", SAMPLE_VENDOR, "latest")
        assert result["changed"] is False
        assert result["old_version"] == "1.0.0"
        mock_download.assert_not_called()

    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.get_auth_token")
    def test_installs_new_version(self, mock_token, mock_resolve, mock_download, tmp_repo):
        mock_token.return_value = "token"
        mock_resolve.return_value = "2.0.0"
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / ".version").write_text("1.0.0")

        result = inst.install_existing_vendor("tool", SAMPLE_VENDOR, "latest")
        assert result["changed"] is True
        assert result["old_version"] == "1.0.0"
        assert result["new_version"] == "2.0.0"
        mock_download.assert_called_once()

    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.get_auth_token")
    def test_fresh_install(self, mock_token, mock_resolve, mock_download, tmp_repo):
        mock_token.return_value = "token"
        mock_resolve.return_value = "1.0.0"

        result = inst.install_existing_vendor("tool", SAMPLE_VENDOR, "latest")
        assert result["changed"] is True
        assert result["old_version"] == "none"
        assert result["new_version"] == "1.0.0"

    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.get_auth_token")
    def test_force_reinstall(self, mock_token, mock_resolve, mock_download, tmp_repo):
        """--force should reinstall even when at target version."""
        mock_token.return_value = "token"
        mock_resolve.return_value = "1.0.0"
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / ".version").write_text("1.0.0")

        result = inst.install_existing_vendor("tool", SAMPLE_VENDOR, "latest", force=True)
        assert result["changed"] is True
        mock_download.assert_called_once()


# ── Tests: install_new_vendor (add path) ──────────────────────────────────

class TestInstallNewVendor:
    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.check_install_sh")
    @patch("vendored_install.check_repo_exists")
    def test_add_new_vendor(self, mock_exists, mock_install_sh,
                            mock_version, mock_download, make_config, tmp_repo, capsys):
        mock_version.return_value = "1.0.0"
        make_config({"vendors": {}})

        def fake_download(repo, version, token):
            config = inst.load_config()
            config["vendors"]["new-tool"] = {
                "repo": "owner/new-tool",
                "protected": [".new-tool/**"],
                "install_branch": "chore/install-new-tool",
            }
            inst.save_config(config)

        mock_download.side_effect = fake_download

        result = inst.install_new_vendor("owner/new-tool", "latest", "token")
        assert result["vendor"] == "new-tool"
        assert result["changed"] is True
        assert result["new_version"] == "1.0.0"

        out = capsys.readouterr().out
        assert "Added vendor: new-tool" in out

    @patch("vendored_install.resolve_version")
    @patch("vendored_install.check_install_sh")
    @patch("vendored_install.check_repo_exists")
    def test_add_already_registered_fails(self, mock_exists, mock_install_sh,
                                           mock_version, make_config):
        mock_version.return_value = "1.0.0"
        make_config({"vendors": {"existing": {"repo": "owner/existing-tool"}}})

        with pytest.raises(SystemExit) as exc_info:
            inst.install_new_vendor("owner/existing-tool", "latest", "token")
        assert exc_info.value.code == 1

    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.check_install_sh")
    @patch("vendored_install.check_repo_exists")
    def test_add_with_custom_name(self, mock_exists, mock_install_sh,
                                   mock_version, mock_download, make_config, tmp_repo, capsys):
        mock_version.return_value = "1.0.0"
        make_config({"vendors": {}})

        def fake_download(repo, version, token):
            config = inst.load_config()
            config["vendors"]["my-custom-name"] = {
                "repo": "owner/tool",
                "protected": [".tool/**"],
                "install_branch": "chore/install-tool",
            }
            inst.save_config(config)

        mock_download.side_effect = fake_download

        result = inst.install_new_vendor("owner/tool", "latest", "token", name="my-custom-name")
        out = capsys.readouterr().out
        assert "Added vendor: my-custom-name" in out


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
        output_file = tmp_repo / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        inst.write_github_output({"vendor": "tool", "changed": "true"})
        content = output_file.read_text()
        assert "vendor=tool\n" in content
        assert "changed=true\n" in content

    def test_no_file_when_env_unset(self, tmp_repo, monkeypatch):
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        output_file = tmp_repo / "github_output.txt"
        inst.write_github_output({"vendor": "tool"})
        assert not output_file.exists()

    def test_single_vendor_writes_github_output(self, make_config, tmp_repo, monkeypatch, capsys):
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
        assert "install_branch=chore/install-tool\n" in content

    def test_multi_vendor_writes_github_output(self, tmp_repo, monkeypatch, capsys):
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

    def test_appends_to_existing_file(self, tmp_repo, monkeypatch):
        output_file = tmp_repo / "github_output.txt"
        output_file.write_text("existing=value\n")
        monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
        inst.write_github_output({"new_key": "new_value"})
        content = output_file.read_text()
        assert "existing=value\n" in content
        assert "new_key=new_value\n" in content


# ── Tests: get_pr_metadata ────────────────────────────────────────────────

class TestGetPrMetadata:
    def test_single_vendor_metadata(self, make_config):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        meta = inst.get_pr_metadata(results)
        assert meta["branch"] == "chore/install-tool-v2.0.0"
        assert meta["title"] == "chore: install tool v2.0.0"
        assert "1.0.0" in meta["body"]
        assert "2.0.0" in meta["body"]

    def test_single_vendor_automerge_true(self, make_config):
        vendor = dict(SAMPLE_VENDOR, automerge=True)
        make_config({"vendors": {"tool": vendor}})
        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        meta = inst.get_pr_metadata(results)
        assert meta["automerge"] is True

    def test_single_vendor_automerge_default(self, make_config):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        meta = inst.get_pr_metadata(results)
        assert meta["automerge"] is False

    def test_multi_vendor_metadata(self, make_config):
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
        make_config({"vendors": {"a": SAMPLE_VENDOR, "b": SAMPLE_VENDOR}})
        results = [
            {"vendor": "a", "old_version": "1.0", "new_version": "2.0", "changed": True},
            {"vendor": "b", "old_version": "1.0", "new_version": "1.0", "changed": False},
        ]
        meta = inst.get_pr_metadata(results)
        assert "a v2.0" in meta["title"]
        assert "b" not in meta["title"]

    def test_no_changes_returns_none(self, make_config):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "1.0.0", "changed": False}]
        assert inst.get_pr_metadata(results) is None

    def test_fallback_install_branch(self, make_config):
        vendor = {"repo": "owner/tool", "protected": [".tool/**"]}
        make_config({"vendors": {"tool": vendor}})
        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        meta = inst.get_pr_metadata(results)
        assert meta["branch"] == "chore/install-tool-v2.0.0"


# ── Tests: create_pull_request ────────────────────────────────────────────

class TestCreatePullRequest:
    def _mock_subprocess(self, pr_stdout="https://github.com/o/r/pull/1\n",
                         pr_returncode=0, pr_stderr="",
                         diff_returncode=1):
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
            return MagicMock(returncode=0)
        return side_effect

    @patch("vendored_install.subprocess.run")
    def test_creates_pr_single_vendor(self, mock_run, make_config, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        mock_run.side_effect = self._mock_subprocess()

        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        pr_url = inst.create_pull_request(results)
        assert pr_url == "https://github.com/o/r/pull/1"

        calls = [c[0][0] for c in mock_run.call_args_list]
        git_cmds = [c for c in calls if c[0] == "git"]
        assert ["git", "config", "user.name", "github-actions[bot]"] in git_cmds
        assert ["git", "add", "-A"] in git_cmds

    @patch("vendored_install.subprocess.run")
    def test_no_changes_skips_pr(self, mock_run, make_config, capsys):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "1.0.0", "changed": False}]
        result = inst.create_pull_request(results)
        assert result is None
        out = capsys.readouterr().out
        assert "No vendor changes" in out
        mock_run.assert_not_called()

    @patch("vendored_install.subprocess.run")
    def test_no_staged_changes_returns_early(self, mock_run, make_config, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        mock_run.side_effect = self._mock_subprocess(diff_returncode=0)

        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        result = inst.create_pull_request(results)
        assert result is None
        out = capsys.readouterr().out
        assert "No changes to commit" in out

    @patch("vendored_install.subprocess.run")
    def test_pr_already_exists(self, mock_run, make_config, monkeypatch, capsys):
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

    @patch("vendored_install.subprocess.run")
    def test_pr_create_failure_exits(self, mock_run, make_config, monkeypatch):
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

    @patch("vendored_install.subprocess.run")
    def test_automerge_when_enabled(self, mock_run, make_config, monkeypatch):
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

    @patch("vendored_install.subprocess.run")
    def test_no_automerge_by_default(self, mock_run, make_config, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh-token")
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        mock_run.side_effect = self._mock_subprocess()

        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        inst.create_pull_request(results)

        merge_calls = [c for c in mock_run.call_args_list
                       if c[0][0][0:3] == ["gh", "pr", "merge"]]
        assert len(merge_calls) == 0

    @patch("vendored_install.subprocess.run")
    def test_uses_github_token_for_gh(self, mock_run, make_config, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "repo-token")
        monkeypatch.setenv("GH_TOKEN", "vendor-pat")
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        mock_run.side_effect = self._mock_subprocess()

        results = [{"vendor": "tool", "old_version": "1.0.0",
                     "new_version": "2.0.0", "changed": True}]
        inst.create_pull_request(results)

        pr_create_calls = [c for c in mock_run.call_args_list
                           if c[0][0][0:3] == ["gh", "pr", "create"]]
        assert len(pr_create_calls) == 1
        env = pr_create_calls[0][1].get("env", {})
        assert env.get("GH_TOKEN") == "repo-token"


# ── Tests: CLI routing ────────────────────────────────────────────────────

class TestCLIRouting:
    def test_is_repo_spec(self):
        assert inst._is_repo_spec("owner/repo") is True
        assert inst._is_repo_spec("all") is False
        assert inst._is_repo_spec("my-tool") is False
        assert inst._is_repo_spec("--version") is False

    @patch("vendored_install.install_new_vendor")
    @patch("vendored_install.output_result")
    @patch("vendored_install.get_auth_token")
    def test_main_routes_repo_spec_to_add(self, mock_token, mock_output,
                                           mock_add, make_config):
        mock_token.return_value = "token"
        mock_add.return_value = {"vendor": "tool", "old_version": "none",
                                  "new_version": "1.0.0", "changed": True}
        make_config({"vendors": {}})

        with patch("sys.argv", ["install", "owner/tool"]):
            inst.main()
        mock_add.assert_called_once()

    @patch("vendored_install.install_existing_vendor")
    @patch("vendored_install.output_result")
    def test_main_routes_vendor_name_to_update(self, mock_output, mock_update, make_config):
        mock_update.return_value = {"vendor": "tool", "old_version": "1.0.0",
                                     "new_version": "2.0.0", "changed": True}
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})

        with patch("sys.argv", ["install", "tool"]):
            inst.main()
        mock_update.assert_called_once()

    @patch("vendored_install.install_existing_vendor")
    @patch("vendored_install.output_results")
    def test_main_routes_all_to_update_all(self, mock_output, mock_update, make_config):
        mock_update.return_value = {"vendor": "tool", "old_version": "1.0.0",
                                     "new_version": "2.0.0", "changed": True}
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})

        with patch("sys.argv", ["install", "all"]):
            inst.main()
        mock_update.assert_called_once()

    def test_main_unknown_vendor_exits(self, make_config):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})

        with patch("sys.argv", ["install", "nonexistent"]):
            with pytest.raises(SystemExit) as exc_info:
                inst.main()
            assert exc_info.value.code == 1
