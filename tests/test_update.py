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
    def test_single_result_format(self, capsys):
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

    def test_output_results_single(self, capsys):
        results = [{
            "vendor": "tool",
            "old_version": "1.0.0",
            "new_version": "2.0.0",
            "changed": True,
        }]
        inst.output_results(results)
        out = capsys.readouterr().out
        assert "vendor=tool" in out

    def test_output_results_multiple(self, capsys):
        results = [
            {"vendor": "a", "old_version": "1.0", "new_version": "2.0", "changed": True},
            {"vendor": "b", "old_version": "1.0", "new_version": "1.0", "changed": False},
        ]
        inst.output_results(results)
        out = capsys.readouterr().out
        assert "changed_count=1" in out
        assert "results=" in out
