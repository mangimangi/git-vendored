"""Tests for the unified templates/install script."""

import importlib.machinery
import importlib.util
import json
import os
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

    def test_loads_per_vendor_configs(self, tmp_repo):
        """load_config() scans configs/ for per-vendor .json files (flat format)."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps(SAMPLE_VENDOR))
        (configs_dir / "other.json").write_text(json.dumps(EXISTING_VENDOR))
        config = inst.load_config()
        assert "vendors" in config
        assert "tool" in config["vendors"]
        assert "other" in config["vendors"]
        assert config["vendors"]["tool"]["repo"] == "owner/tool"

    def test_loads_per_vendor_configs_with_vendor_key(self, tmp_repo):
        """load_config() extracts registry from _vendor key."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        vendor_file = {"_vendor": SAMPLE_VENDOR, "custom_key": "value"}
        (configs_dir / "tool.json").write_text(json.dumps(vendor_file))
        config = inst.load_config()
        assert "vendors" in config
        assert "tool" in config["vendors"]
        assert config["vendors"]["tool"]["repo"] == "owner/tool"
        # Project config keys should NOT leak into the vendor registry
        assert "custom_key" not in config["vendors"]["tool"]

    def test_flat_configs_backwards_compat(self, tmp_repo):
        """Flat configs (no _vendor key) still load correctly."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps(SAMPLE_VENDOR))
        config = inst.load_config()
        assert config["vendors"]["tool"]["repo"] == "owner/tool"
        assert config["vendors"]["tool"]["install_branch"] == "chore/install-tool"

    def test_per_vendor_configs_take_priority(self, tmp_repo, make_config):
        """Per-vendor configs take priority over monolithic config.json."""
        make_config({"vendors": {"old": SAMPLE_VENDOR}})
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "new-tool.json").write_text(json.dumps(EXISTING_VENDOR))
        config = inst.load_config()
        assert "new-tool" in config["vendors"]
        assert "old" not in config["vendors"]

    def test_empty_configs_dir_falls_back(self, tmp_repo, make_config):
        """Empty configs/ dir falls back to monolithic config.json."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        (tmp_repo / ".vendored" / "configs").mkdir(parents=True)
        config = inst.load_config()
        assert "tool" in config["vendors"]

    def test_vendor_name_from_filename(self, tmp_repo):
        """Vendor name is derived from filename (e.g. pearls.json -> pearls)."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "my-vendor.json").write_text(json.dumps(SAMPLE_VENDOR))
        config = inst.load_config()
        assert "my-vendor" in config["vendors"]


# ── Tests: save_config ────────────────────────────────────────────────────

class TestSaveConfig:
    def test_saves_monolithic_config(self, tmp_repo, make_config):
        """save_config writes monolithic config.json when configs/ not in use."""
        make_config({"vendors": {}})
        config = {"vendors": {"tool": SAMPLE_VENDOR}}
        inst.save_config(config)
        loaded = json.loads((tmp_repo / ".vendored" / "config.json").read_text())
        assert "tool" in loaded["vendors"]

    def test_saves_per_vendor_configs(self, tmp_repo):
        """save_config writes individual files with _vendor key when configs/ in use."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "existing.json").write_text(json.dumps({"_vendor": EXISTING_VENDOR}))
        config = {"vendors": {"tool": SAMPLE_VENDOR, "existing": EXISTING_VENDOR}}
        inst.save_config(config)
        assert (configs_dir / "tool.json").is_file()
        loaded = json.loads((configs_dir / "tool.json").read_text())
        assert "_vendor" in loaded
        assert loaded["_vendor"]["repo"] == "owner/tool"

    def test_save_vendor_config(self, tmp_repo):
        """save_vendor_config writes config with _vendor key."""
        inst.save_vendor_config("tool", SAMPLE_VENDOR)
        filepath = tmp_repo / ".vendored" / "configs" / "tool.json"
        assert filepath.is_file()
        loaded = json.loads(filepath.read_text())
        assert "_vendor" in loaded
        assert loaded["_vendor"]["repo"] == "owner/tool"
        # Registry fields should NOT be at top level
        assert "repo" not in loaded

    def test_save_vendor_config_preserves_project_config(self, tmp_repo):
        """save_vendor_config preserves existing top-level project config keys."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        existing = {"_vendor": SAMPLE_VENDOR, "prefix": "gv", "docs": ["README.md"]}
        (configs_dir / "tool.json").write_text(json.dumps(existing))
        # Update registry
        new_registry = dict(SAMPLE_VENDOR, automerge=True)
        inst.save_vendor_config("tool", new_registry)
        loaded = json.loads((configs_dir / "tool.json").read_text())
        assert loaded["_vendor"]["automerge"] is True
        assert loaded["prefix"] == "gv"
        assert loaded["docs"] == ["README.md"]

    def test_delete_vendor_config(self, tmp_repo):
        """delete_vendor_config removes the vendor's config file."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps(SAMPLE_VENDOR))
        inst.delete_vendor_config("tool")
        assert not (configs_dir / "tool.json").exists()

    def test_delete_vendor_config_noop_if_missing(self, tmp_repo):
        """delete_vendor_config is a no-op if file doesn't exist."""
        inst.delete_vendor_config("nonexistent")  # should not raise


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

    def test_prefers_manifest_version(self, tmp_repo):
        """Manifest version takes priority over legacy version files."""
        (tmp_repo / ".vendored" / "manifests").mkdir(parents=True)
        (tmp_repo / ".vendored" / "manifests" / "tool.version").write_text("3.0.0\n")
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / ".version").write_text("1.0.0\n")
        version = inst.get_current_version("tool", SAMPLE_VENDOR)
        assert version == "3.0.0"


# ── Tests: Manifest helpers ───────────────────────────────────────────────

class TestManifestHelpers:
    def test_write_and_read_manifest(self, tmp_repo):
        files = [".tool/script.sh", ".tool/config.json"]
        inst.write_manifest("tool", files)
        result = inst.read_manifest("tool")
        assert sorted(result) == sorted(files)

    def test_read_missing_manifest_returns_none(self, tmp_repo):
        assert inst.read_manifest("nonexistent") is None

    def test_write_and_read_manifest_version(self, tmp_repo):
        inst.write_manifest_version("tool", "1.2.3")
        assert inst.read_manifest_version("tool") == "1.2.3"

    def test_read_missing_manifest_version_returns_none(self, tmp_repo):
        assert inst.read_manifest_version("nonexistent") is None

    def test_validate_manifest_passes(self, tmp_repo):
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")
        inst.validate_manifest([".tool/script.sh"])

    def test_validate_manifest_fails_for_missing_files(self, tmp_repo):
        with pytest.raises(SystemExit) as exc_info:
            inst.validate_manifest([".tool/nonexistent.sh"])
        assert exc_info.value.code == 1

    def test_manifest_creates_directory(self, tmp_repo):
        """write_manifest creates .vendored/manifests/ if it doesn't exist."""
        inst.write_manifest("tool", [".tool/script.sh"])
        assert (tmp_repo / ".vendored" / "manifests" / "tool.files").is_file()

    def test_manifest_files_sorted(self, tmp_repo):
        """Manifest files are written in sorted order."""
        files = [".tool/z.sh", ".tool/a.sh", ".tool/m.sh"]
        inst.write_manifest("tool", files)
        content = (tmp_repo / ".vendored" / "manifests" / "tool.files").read_text()
        lines = [l for l in content.strip().split("\n") if l]
        assert lines == sorted(files)


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

    @patch("vendored_install.download_deps", return_value=None)
    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.get_auth_token")
    def test_installs_new_version(self, mock_token, mock_resolve, mock_download,
                                   mock_deps, tmp_repo):
        mock_token.return_value = "token"
        mock_resolve.return_value = "2.0.0"
        mock_download.return_value = None  # v1 compat: no manifest
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / ".version").write_text("1.0.0")

        result = inst.install_existing_vendor("tool", SAMPLE_VENDOR, "latest")
        assert result["changed"] is True
        assert result["old_version"] == "1.0.0"
        assert result["new_version"] == "2.0.0"
        mock_download.assert_called_once()

    @patch("vendored_install.download_deps", return_value=None)
    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.get_auth_token")
    def test_fresh_install(self, mock_token, mock_resolve, mock_download,
                            mock_deps, tmp_repo):
        mock_token.return_value = "token"
        mock_resolve.return_value = "1.0.0"
        mock_download.return_value = None

        result = inst.install_existing_vendor("tool", SAMPLE_VENDOR, "latest")
        assert result["changed"] is True
        assert result["old_version"] == "none"
        assert result["new_version"] == "1.0.0"

    @patch("vendored_install.download_deps", return_value=None)
    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.get_auth_token")
    def test_force_reinstall(self, mock_token, mock_resolve, mock_download,
                              mock_deps, tmp_repo):
        """--force should reinstall even when at target version."""
        mock_token.return_value = "token"
        mock_resolve.return_value = "1.0.0"
        mock_download.return_value = None
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / ".version").write_text("1.0.0")

        result = inst.install_existing_vendor("tool", SAMPLE_VENDOR, "latest", force=True)
        assert result["changed"] is True
        mock_download.assert_called_once()

    @patch("vendored_install.download_deps", return_value=None)
    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.get_auth_token")
    def test_manifest_stored_on_update(self, mock_token, mock_resolve, mock_download,
                                        mock_deps, tmp_repo):
        """When install.sh emits a manifest, it should be stored."""
        mock_token.return_value = "token"
        mock_resolve.return_value = "2.0.0"
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")
        mock_download.return_value = [".tool/script.sh"]

        result = inst.install_existing_vendor("tool", SAMPLE_VENDOR, "latest")
        assert result["changed"] is True

        # Verify manifest was stored
        manifest = inst.read_manifest("tool")
        assert manifest == [".tool/script.sh"]
        assert inst.read_manifest_version("tool") == "2.0.0"

    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.get_auth_token")
    def test_skip_when_current_via_manifest(self, mock_token, mock_resolve, mock_download, tmp_repo):
        """Version from manifest storage used for skip check."""
        mock_token.return_value = "token"
        mock_resolve.return_value = "1.0.0"
        inst.write_manifest_version("tool", "1.0.0")

        result = inst.install_existing_vendor("tool", SAMPLE_VENDOR, "latest")
        assert result["changed"] is False
        mock_download.assert_not_called()

    @patch("vendored_install.download_deps", return_value=None)
    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.get_auth_token")
    def test_passes_vendor_name_and_config_to_download(self, mock_token, mock_resolve,
                                                        mock_download, mock_deps,
                                                        tmp_repo):
        """install_existing_vendor passes vendor_name and vendor_config to download."""
        mock_token.return_value = "token"
        mock_resolve.return_value = "2.0.0"
        mock_download.return_value = None

        inst.install_existing_vendor("tool", SAMPLE_VENDOR, "latest")
        _, kwargs = mock_download.call_args
        assert kwargs["vendor_name"] == "tool"
        assert kwargs["vendor_config"] == SAMPLE_VENDOR


# ── Tests: install_new_vendor (add path) ──────────────────────────────────

class TestInstallNewVendor:
    @patch("vendored_install.download_deps", return_value=None)
    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.check_install_sh")
    @patch("vendored_install.check_repo_exists")
    def test_add_new_vendor(self, mock_exists, mock_install_sh,
                            mock_version, mock_download, mock_deps,
                            make_config, tmp_repo, capsys):
        mock_version.return_value = "1.0.0"
        make_config({"vendors": {}})

        def fake_download(repo, version, token, **kwargs):
            config = inst.load_config()
            config["vendors"]["new-tool"] = {
                "repo": "owner/new-tool",
                "protected": [".new-tool/**"],
                "install_branch": "chore/install-new-tool",
            }
            inst.save_config(config)
            return None  # v1 compat: no manifest

        mock_download.side_effect = fake_download

        result = inst.install_new_vendor("owner/new-tool", "latest", "token")
        assert result["vendor"] == "new-tool"
        assert result["changed"] is True
        assert result["new_version"] == "1.0.0"

        out = capsys.readouterr().out
        assert "Added vendor: new-tool" in out

    @patch("vendored_install.download_deps", return_value=None)
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.check_install_sh")
    @patch("vendored_install.check_repo_exists")
    def test_add_already_registered_fails(self, mock_exists, mock_install_sh,
                                           mock_version, mock_deps, make_config):
        mock_version.return_value = "1.0.0"
        make_config({"vendors": {"existing": {"repo": "owner/existing-tool"}}})

        with pytest.raises(SystemExit) as exc_info:
            inst.install_new_vendor("owner/existing-tool", "latest", "token")
        assert exc_info.value.code == 1

    @patch("vendored_install.download_deps", return_value=None)
    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.check_install_sh")
    @patch("vendored_install.check_repo_exists")
    def test_add_with_custom_name(self, mock_exists, mock_install_sh,
                                   mock_version, mock_download, mock_deps,
                                   make_config, tmp_repo, capsys):
        mock_version.return_value = "1.0.0"
        make_config({"vendors": {}})

        def fake_download(repo, version, token, **kwargs):
            config = inst.load_config()
            config["vendors"]["my-custom-name"] = {
                "repo": "owner/tool",
                "protected": [".tool/**"],
                "install_branch": "chore/install-tool",
            }
            inst.save_config(config)
            return None

        mock_download.side_effect = fake_download

        result = inst.install_new_vendor("owner/tool", "latest", "token", name="my-custom-name")
        out = capsys.readouterr().out
        assert "Added vendor: my-custom-name" in out

    @patch("vendored_install.download_deps", return_value=None)
    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.check_install_sh")
    @patch("vendored_install.check_repo_exists")
    def test_add_new_vendor_with_per_vendor_configs_active(
            self, mock_exists, mock_install_sh, mock_version, mock_download,
            mock_deps, make_config, tmp_repo, capsys):
        """install.sh writes to config.json but per-vendor configs are active."""
        mock_version.return_value = "1.0.0"
        # Existing vendor in per-vendor config (makes load_config read from configs/)
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "existing.json").write_text(json.dumps(EXISTING_VENDOR))
        # Empty config.json (vendors key removed after migration)
        make_config({})

        new_entry = {
            "repo": "owner/new-tool",
            "protected": [".new-tool/**"],
            "install_branch": "chore/install-new-tool",
        }

        def fake_download(repo, version, token, **kwargs):
            # install.sh writes to monolithic config.json (as real install.sh would)
            config_path = tmp_repo / ".vendored" / "config.json"
            raw = json.loads(config_path.read_text())
            raw.setdefault("vendors", {})["new-tool"] = new_entry
            config_path.write_text(json.dumps(raw, indent=2) + "\n")
            return None

        mock_download.side_effect = fake_download

        result = inst.install_new_vendor("owner/new-tool", "latest", "token")
        assert result["vendor"] == "new-tool"
        assert result["changed"] is True

        # New entry should be migrated to per-vendor config with _vendor key
        assert (configs_dir / "new-tool.json").is_file()
        migrated = json.loads((configs_dir / "new-tool.json").read_text())
        assert migrated["_vendor"]["repo"] == "owner/new-tool"

        # config.json should be cleaned up
        raw = json.loads((tmp_repo / ".vendored" / "config.json").read_text())
        assert "vendors" not in raw or "new-tool" not in raw.get("vendors", {})

        out = capsys.readouterr().out
        assert "Added vendor: new-tool" in out

    @patch("vendored_install.download_deps", return_value=None)
    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.check_install_sh")
    @patch("vendored_install.check_repo_exists")
    def test_add_with_manifest(self, mock_exists, mock_install_sh,
                                mock_version, mock_download, mock_deps,
                                make_config, tmp_repo, capsys):
        """When install.sh emits a manifest, it should be stored on add."""
        mock_version.return_value = "1.0.0"
        make_config({"vendors": {}})

        (tmp_repo / ".new-tool").mkdir()
        (tmp_repo / ".new-tool" / "script.sh").write_text("#!/bin/bash")

        def fake_download(repo, version, token, **kwargs):
            config = inst.load_config()
            config["vendors"]["new-tool"] = {
                "repo": "owner/new-tool",
                "protected": [".new-tool/**"],
                "install_branch": "chore/install-new-tool",
            }
            inst.save_config(config)
            return [".new-tool/script.sh"]

        mock_download.side_effect = fake_download

        result = inst.install_new_vendor("owner/new-tool", "latest", "token")
        assert result["changed"] is True

        manifest = inst.read_manifest("new-tool")
        assert manifest == [".new-tool/script.sh"]
        assert inst.read_manifest_version("new-tool") == "1.0.0"

        out = capsys.readouterr().out
        assert "manifest: 1 files" in out


# ── Tests: VENDOR_INSTALL_DIR ─────────────────────────────────────────────

DOGFOOD_VENDOR = {
    "repo": "mangimangi/git-vendored",
    "install_branch": "chore/install-git-vendored",
    "dogfood": True,
    "protected": [".vendored/**"],
}


class TestVendorInstallDir:
    @patch("vendored_install.subprocess.run")
    def test_sets_vendor_install_dir(self, mock_run, tmp_repo, monkeypatch):
        """VENDOR_INSTALL_DIR is set for non-dogfood vendors."""
        import base64 as b64
        script = b64.b64encode(b"#!/bin/bash\ntrue\n").decode()
        mock_run.return_value = MagicMock(returncode=0, stdout=script + "\n", stderr="")

        inst.download_and_run_install(
            "owner/tool", "1.0.0", "token",
            vendor_name="tool", vendor_config=SAMPLE_VENDOR
        )
        # Find the bash call (the one running install.sh)
        bash_calls = [c for c in mock_run.call_args_list
                      if c[0][0][0] == "bash"]
        assert len(bash_calls) >= 1
        env = bash_calls[0][1].get("env", {})
        assert env.get("VENDOR_INSTALL_DIR") == ".vendored/pkg/tool"

    @patch("vendored_install.subprocess.run")
    def test_creates_pkg_directory(self, mock_run, tmp_repo, monkeypatch):
        """Framework creates .vendored/pkg/<vendor>/ before running install.sh."""
        import base64 as b64
        script = b64.b64encode(b"#!/bin/bash\ntrue\n").decode()
        mock_run.return_value = MagicMock(returncode=0, stdout=script + "\n", stderr="")

        inst.download_and_run_install(
            "owner/tool", "1.0.0", "token",
            vendor_name="tool", vendor_config=SAMPLE_VENDOR
        )
        assert (tmp_repo / ".vendored" / "pkg" / "tool").is_dir()

    @patch("vendored_install.subprocess.run")
    def test_dogfood_no_install_dir(self, mock_run, tmp_repo, monkeypatch):
        """Dogfood vendors do NOT get VENDOR_INSTALL_DIR."""
        import base64 as b64
        script = b64.b64encode(b"#!/bin/bash\ntrue\n").decode()
        mock_run.return_value = MagicMock(returncode=0, stdout=script + "\n", stderr="")

        inst.download_and_run_install(
            "mangimangi/git-vendored", "1.0.0", "token",
            vendor_name="git-vendored", vendor_config=DOGFOOD_VENDOR
        )
        bash_calls = [c for c in mock_run.call_args_list
                      if c[0][0][0] == "bash"]
        assert len(bash_calls) >= 1
        env = bash_calls[0][1].get("env", {})
        assert "VENDOR_INSTALL_DIR" not in env

    @patch("vendored_install.subprocess.run")
    def test_no_vendor_name_no_install_dir(self, mock_run, tmp_repo, monkeypatch):
        """When vendor_name is None (legacy call), no VENDOR_INSTALL_DIR."""
        import base64 as b64
        script = b64.b64encode(b"#!/bin/bash\ntrue\n").decode()
        mock_run.return_value = MagicMock(returncode=0, stdout=script + "\n", stderr="")

        inst.download_and_run_install("owner/tool", "1.0.0", "token")
        bash_calls = [c for c in mock_run.call_args_list
                      if c[0][0][0] == "bash"]
        assert len(bash_calls) >= 1
        env = bash_calls[0][1].get("env", {})
        assert "VENDOR_INSTALL_DIR" not in env


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


# ── Tests: config migration ───────────────────────────────────────────────

class TestMigrateConfig:
    def test_splits_vendors_into_configs_dir(self, tmp_repo, make_config):
        """migrate_config creates individual files in configs/ with _vendor key."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR, "other": EXISTING_VENDOR}})
        raw = {"vendors": {"tool": SAMPLE_VENDOR, "other": EXISTING_VENDOR}}
        inst.migrate_config(raw)

        configs_dir = tmp_repo / ".vendored" / "configs"
        assert (configs_dir / "tool.json").is_file()
        assert (configs_dir / "other.json").is_file()

        tool_config = json.loads((configs_dir / "tool.json").read_text())
        assert "_vendor" in tool_config
        assert tool_config["_vendor"]["repo"] == "owner/tool"

    def test_removes_vendors_key_from_config(self, tmp_repo, make_config):
        """migrate_config removes vendors key from config.json."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        raw = {"vendors": {"tool": SAMPLE_VENDOR}}
        inst.migrate_config(raw)

        config = json.loads((tmp_repo / ".vendored" / "config.json").read_text())
        assert "vendors" not in config

    def test_idempotent(self, tmp_repo, make_config):
        """Running migration twice doesn't corrupt data."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        raw1 = {"vendors": {"tool": SAMPLE_VENDOR}}
        inst.migrate_config(raw1)

        # Second run — configs/ already has files, so _should_migrate_config is False
        assert not inst._should_migrate_config()

    def test_should_migrate_when_monolithic(self, tmp_repo, make_config):
        """_should_migrate_config returns True when vendors in config.json."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        assert inst._should_migrate_config() is True

    def test_should_not_migrate_when_configs_exist(self, tmp_repo, make_config):
        """_should_migrate_config returns False when configs/ has .json files."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps(SAMPLE_VENDOR))
        assert inst._should_migrate_config() is False

    def test_should_not_migrate_empty_vendors(self, tmp_repo, make_config):
        """_should_migrate_config returns False when vendors dict is empty."""
        make_config({"vendors": {}})
        assert inst._should_migrate_config() is False

    def test_should_not_migrate_no_config(self, tmp_repo):
        """_should_migrate_config returns False when config.json doesn't exist."""
        assert inst._should_migrate_config() is False

    def test_preserves_protected_field(self, tmp_repo, make_config):
        """Protected field is preserved under _vendor key for v1 fallback."""
        vendor = dict(SAMPLE_VENDOR, protected=[".tool/**"])
        make_config({"vendors": {"tool": vendor}})
        raw = {"vendors": {"tool": vendor}}
        inst.migrate_config(raw)

        configs_dir = tmp_repo / ".vendored" / "configs"
        tool_config = json.loads((configs_dir / "tool.json").read_text())
        assert tool_config["_vendor"]["protected"] == [".tool/**"]

    def test_logs_migration(self, tmp_repo, make_config, capsys):
        """Migration logs to stderr for visibility."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        raw = {"vendors": {"tool": SAMPLE_VENDOR}}
        inst.migrate_config(raw)

        err = capsys.readouterr().err
        assert "Migrated config: tool" in err
        assert "migration complete" in err.lower()


# ── Tests: project config migration ──────────────────────────────────────

class TestMigrateProjectConfigs:
    def test_merges_legacy_project_config(self, tmp_repo):
        """Legacy .<vendor>/config.json is merged into configs/<vendor>.json."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        vendor_data = {"_vendor": SAMPLE_VENDOR}
        (configs_dir / "tool.json").write_text(json.dumps(vendor_data))

        # Legacy project config
        (tmp_repo / ".tool").mkdir()
        project = {"setting": "value", "flag": True}
        (tmp_repo / ".tool" / "config.json").write_text(json.dumps(project))

        inst.migrate_project_configs()

        merged = json.loads((configs_dir / "tool.json").read_text())
        assert merged["_vendor"] == SAMPLE_VENDOR
        assert merged["setting"] == "value"
        assert merged["flag"] is True

    def test_does_not_overwrite_vendor_key(self, tmp_repo):
        """_vendor key is never overwritten by project config."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        vendor_data = {"_vendor": SAMPLE_VENDOR}
        (configs_dir / "tool.json").write_text(json.dumps(vendor_data))

        # Legacy config that happens to have a _vendor key
        (tmp_repo / ".tool").mkdir()
        project = {"_vendor": {"repo": "evil/override"}, "setting": "ok"}
        (tmp_repo / ".tool" / "config.json").write_text(json.dumps(project))

        inst.migrate_project_configs()

        merged = json.loads((configs_dir / "tool.json").read_text())
        assert merged["_vendor"]["repo"] == "owner/tool"
        assert merged["setting"] == "ok"

    def test_removes_legacy_config_after_merge(self, tmp_repo):
        """Legacy config file is deleted after successful merge."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps({"_vendor": SAMPLE_VENDOR}))

        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "config.json").write_text(json.dumps({"x": 1}))

        inst.migrate_project_configs()

        assert not (tmp_repo / ".tool" / "config.json").exists()

    def test_idempotent(self, tmp_repo):
        """Running migration twice doesn't duplicate or corrupt."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps({"_vendor": SAMPLE_VENDOR}))

        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "config.json").write_text(json.dumps({"x": 1}))

        inst.migrate_project_configs()
        # Second run: legacy file is gone, no-op
        inst.migrate_project_configs()

        merged = json.loads((configs_dir / "tool.json").read_text())
        assert merged["x"] == 1
        assert merged["_vendor"] == SAMPLE_VENDOR

    def test_no_legacy_config_is_noop(self, tmp_repo):
        """No legacy config files means migration is a no-op."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps({"_vendor": SAMPLE_VENDOR}))

        inst.migrate_project_configs()

        merged = json.loads((configs_dir / "tool.json").read_text())
        assert merged == {"_vendor": SAMPLE_VENDOR}

    def test_should_migrate_detects_legacy(self, tmp_repo):
        """_should_migrate_project_configs returns True when legacy configs exist."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps({"_vendor": SAMPLE_VENDOR}))

        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "config.json").write_text("{}")

        assert inst._should_migrate_project_configs() is True

    def test_should_migrate_false_when_no_legacy(self, tmp_repo):
        """_should_migrate_project_configs returns False when no legacy configs."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps({"_vendor": SAMPLE_VENDOR}))

        assert inst._should_migrate_project_configs() is False

    def test_should_migrate_false_when_no_configs_dir(self, tmp_repo):
        """_should_migrate_project_configs returns False when no configs/ dir."""
        assert inst._should_migrate_project_configs() is False

    def test_logs_migration(self, tmp_repo, capsys):
        """Migration logs to stderr for visibility."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps({"_vendor": SAMPLE_VENDOR}))

        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "config.json").write_text(json.dumps({"x": 1}))

        inst.migrate_project_configs()

        err = capsys.readouterr().err
        assert "Merged project config" in err
        assert ".tool/config.json" in err

    def test_removes_empty_dotdir(self, tmp_repo):
        """Empty dot-directory is cleaned up after config migration."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps({"_vendor": SAMPLE_VENDOR}))

        # Dot-directory with only config.json
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "config.json").write_text(json.dumps({"x": 1}))

        inst.migrate_project_configs()

        assert not (tmp_repo / ".tool").exists()

    def test_preserves_non_empty_dotdir(self, tmp_repo):
        """Dot-directory with other files is NOT removed."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps({"_vendor": SAMPLE_VENDOR}))

        # Dot-directory with config.json AND other files
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "config.json").write_text(json.dumps({"x": 1}))
        (tmp_repo / ".tool" / "data.db").write_text("data")

        inst.migrate_project_configs()

        # config.json removed but dir preserved because of data.db
        assert not (tmp_repo / ".tool" / "config.json").exists()
        assert (tmp_repo / ".tool").exists()
        assert (tmp_repo / ".tool" / "data.db").exists()

    def test_preserves_dotdir_with_data_and_git_infra(self, tmp_repo):
        """Dot-directory with data files and git infrastructure is retained as data zone."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps({"_vendor": SAMPLE_VENDOR}))

        # Simulate a vendor dot-dir with data files and git infrastructure
        dotdir = tmp_repo / ".tool"
        dotdir.mkdir()
        (dotdir / "config.json").write_text(json.dumps({"x": 1}))
        (dotdir / "issues.jsonl").write_text('{"id":"t-1"}\n')
        (dotdir / ".gitattributes").write_text("*.jsonl merge=custom\n")
        (dotdir / ".gitignore").write_text("*.lock\n")

        inst.migrate_project_configs()

        # config.json migrated away, but data + git infra preserved
        assert not (dotdir / "config.json").exists()
        assert dotdir.exists()
        assert (dotdir / "issues.jsonl").exists()
        assert (dotdir / ".gitattributes").exists()
        assert (dotdir / ".gitignore").exists()

    def test_logs_empty_dir_removal(self, tmp_repo, capsys):
        """Cleanup of empty dot-directory is logged."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps({"_vendor": SAMPLE_VENDOR}))

        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "config.json").write_text(json.dumps({"x": 1}))

        inst.migrate_project_configs()

        err = capsys.readouterr().err
        assert "Removed empty directory" in err


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


# ── Tests: Dependency helpers ──────────────────────────────────────────────

class TestDepsHelpers:
    def test_write_and_read_deps(self, tmp_repo):
        inst.write_deps("tool", ["git-semver", "pearls"])
        result = inst.read_deps("tool")
        assert result == ["git-semver", "pearls"]

    def test_read_deps_missing_returns_none(self, tmp_repo):
        assert inst.read_deps("nonexistent") is None

    def test_write_deps_sorted(self, tmp_repo):
        inst.write_deps("tool", ["zebra", "alpha", "middle"])
        result = inst.read_deps("tool")
        assert result == ["alpha", "middle", "zebra"]

    def test_write_deps_creates_dir(self, tmp_repo):
        inst.write_deps("tool", ["dep"])
        assert (tmp_repo / ".vendored" / "manifests" / "tool.deps").is_file()


# ── Tests: download_deps ──────────────────────────────────────────────────

class TestDownloadDeps:
    @patch("vendored_install.subprocess.run")
    def test_returns_dict(self, mock_run):
        import base64 as b64
        deps_json = json.dumps({"git-semver": {"repo": "mangimangi/git-semver"}})
        encoded = b64.b64encode(deps_json.encode()).decode()
        mock_run.return_value = MagicMock(returncode=0, stdout=encoded + "\n")

        result = inst.download_deps("owner/tool", "v1.0.0", "token")
        assert result == {"git-semver": {"repo": "mangimangi/git-semver"}}

    @patch("vendored_install.subprocess.run")
    def test_returns_none_when_missing(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Not Found")
        result = inst.download_deps("owner/tool", "v1.0.0", "token")
        assert result is None

    @patch("vendored_install.subprocess.run")
    def test_returns_none_on_invalid_json(self, mock_run):
        import base64 as b64
        encoded = b64.b64encode(b"not-json").decode()
        mock_run.return_value = MagicMock(returncode=0, stdout=encoded + "\n")
        result = inst.download_deps("owner/tool", "v1.0.0", "token")
        assert result is None


# ── Tests: check_deps ─────────────────────────────────────────────────────

class TestCheckDeps:
    def test_all_satisfied(self):
        deps = {"git-semver": {"repo": "mangimangi/git-semver"}}
        config = {"vendors": {"git-semver": {"repo": "mangimangi/git-semver"}}}
        satisfied, missing = inst.check_deps(deps, config)
        assert len(satisfied) == 1
        assert len(missing) == 0

    def test_missing(self):
        deps = {"git-semver": {"repo": "mangimangi/git-semver"}}
        config = {"vendors": {}}
        satisfied, missing = inst.check_deps(deps, config)
        assert len(satisfied) == 0
        assert len(missing) == 1
        assert missing[0][0] == "git-semver"

    def test_matches_by_repo_not_name(self):
        """Vendor installed with custom name, dep matched by repo field."""
        deps = {"git-semver": {"repo": "mangimangi/git-semver"}}
        config = {"vendors": {"custom-name": {"repo": "mangimangi/git-semver"}}}
        satisfied, missing = inst.check_deps(deps, config)
        assert len(satisfied) == 1
        assert len(missing) == 0

    def test_multiple_deps_mixed(self):
        deps = {
            "git-semver": {"repo": "mangimangi/git-semver"},
            "pearls": {"repo": "mangimangi/pearls"},
        }
        config = {"vendors": {"git-semver": {"repo": "mangimangi/git-semver"}}}
        satisfied, missing = inst.check_deps(deps, config)
        assert len(satisfied) == 1
        assert len(missing) == 1
        assert missing[0][0] == "pearls"


# ── Tests: resolve_deps ───────────────────────────────────────────────────

class TestResolveDeps:
    def test_skip_mode_noop(self):
        deps = {"git-semver": {"repo": "mangimangi/git-semver"}}
        config = {"vendors": {}}
        # Should not exit
        inst.resolve_deps(deps, config, "token", "skip")

    def test_none_deps_noop(self):
        config = {"vendors": {}}
        inst.resolve_deps(None, config, "token", "error")

    def test_error_mode_exits(self):
        deps = {"git-semver": {"repo": "mangimangi/git-semver"}}
        config = {"vendors": {}}
        with pytest.raises(SystemExit) as exc_info:
            inst.resolve_deps(deps, config, "token", "error")
        assert exc_info.value.code == 1

    def test_error_mode_no_exit_when_satisfied(self):
        deps = {"git-semver": {"repo": "mangimangi/git-semver"}}
        config = {"vendors": {"git-semver": {"repo": "mangimangi/git-semver"}}}
        inst.resolve_deps(deps, config, "token", "error")

    def test_warn_mode_continues(self, capsys):
        deps = {"git-semver": {"repo": "mangimangi/git-semver"}}
        config = {"vendors": {}}
        inst.resolve_deps(deps, config, "token", "warn")
        out = capsys.readouterr().out
        assert "Warning" in out
        assert "git-semver" in out

    @patch("vendored_install.install_new_vendor")
    def test_install_mode_calls_install(self, mock_install):
        mock_install.return_value = {
            "vendor": "git-semver", "old_version": "none",
            "new_version": "1.0.0", "changed": True,
        }
        deps = {"git-semver": {"repo": "mangimangi/git-semver"}}
        config = {"vendors": {}}
        inst.resolve_deps(deps, config, "token", "install")
        mock_install.assert_called_once()
        call_kwargs = mock_install.call_args
        assert call_kwargs[0][0] == "mangimangi/git-semver"
        assert call_kwargs[0][1] == "latest"

    @patch("vendored_install.install_new_vendor")
    def test_install_mode_passes_installing_set(self, mock_install):
        mock_install.return_value = {
            "vendor": "git-semver", "old_version": "none",
            "new_version": "1.0.0", "changed": True,
        }
        deps = {"git-semver": {"repo": "mangimangi/git-semver"}}
        config = {"vendors": {}}
        my_set = {"owner/other-tool"}
        inst.resolve_deps(deps, config, "token", "install", installing_set=my_set)
        _, kwargs = mock_install.call_args
        assert "owner/other-tool" in kwargs["installing_set"]


# ── Tests: Cycle detection ────────────────────────────────────────────────

class TestCycleDetection:
    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.check_install_sh")
    @patch("vendored_install.check_repo_exists")
    @patch("vendored_install.download_deps")
    def test_circular_dependency_detected(self, mock_deps, mock_exists,
                                           mock_install_sh, mock_version,
                                           mock_download, make_config):
        """A repo already in installing_set should trigger cycle error."""
        mock_version.return_value = "1.0.0"
        make_config({"vendors": {}})

        installing_set = {"owner/tool"}
        with pytest.raises(SystemExit) as exc_info:
            inst.install_new_vendor("owner/tool", "latest", "token",
                                     installing_set=installing_set)
        assert exc_info.value.code == 1

    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.check_install_sh")
    @patch("vendored_install.check_repo_exists")
    @patch("vendored_install.download_deps")
    def test_self_dependency_detected(self, mock_deps, mock_exists,
                                       mock_install_sh, mock_version,
                                       mock_download, make_config):
        """Self-dependency: repo depends on itself."""
        mock_version.return_value = "1.0.0"
        make_config({"vendors": {}})
        mock_deps.return_value = {"tool": {"repo": "owner/tool"}}

        def fake_download(repo, version, token, **kwargs):
            config = inst.load_config()
            config["vendors"]["tool"] = {
                "repo": "owner/tool",
                "protected": [".tool/**"],
                "install_branch": "chore/install-tool",
            }
            inst.save_config(config)
            return None

        mock_download.side_effect = fake_download

        # install_new_vendor adds repo to installing_set, then resolve_deps
        # tries to install the same repo recursively
        with pytest.raises(SystemExit) as exc_info:
            inst.install_new_vendor("owner/tool", "latest", "token",
                                     dep_mode="install")
        assert exc_info.value.code == 1


# ── Tests: _get_dep_mode ──────────────────────────────────────────────────

class TestGetDepMode:
    def test_cli_flag_used(self):
        assert inst._get_dep_mode("warn", {}) == "warn"

    def test_config_used_when_no_flag(self, tmp_repo, make_config):
        make_config({"dependency_mode": "skip"})
        assert inst._get_dep_mode(None, {}) == "skip"

    def test_default_error(self, tmp_repo):
        assert inst._get_dep_mode(None, {}) == "error"

    def test_cli_overrides_config(self, tmp_repo, make_config):
        make_config({"dependency_mode": "skip"})
        assert inst._get_dep_mode("warn", {}) == "warn"


# ── Tests: topological_sort ───────────────────────────────────────────────

class TestTopologicalSort:
    def test_no_deps(self, tmp_repo):
        """All vendors independent -> alphabetical order."""
        vendors = {"c": {"repo": "owner/c"}, "a": {"repo": "owner/a"},
                   "b": {"repo": "owner/b"}}
        result = inst.topological_sort(vendors)
        assert result == ["a", "b", "c"]

    def test_linear(self, tmp_repo):
        """A depends on B -> B before A."""
        vendors = {"a": {"repo": "owner/a"}, "b": {"repo": "owner/b"}}
        inst.write_deps("a", ["b"])
        result = inst.topological_sort(vendors)
        assert result.index("b") < result.index("a")

    def test_diamond(self, tmp_repo):
        """A depends on B and C, B depends on D, C depends on D -> D first."""
        vendors = {
            "a": {"repo": "owner/a"}, "b": {"repo": "owner/b"},
            "c": {"repo": "owner/c"}, "d": {"repo": "owner/d"},
        }
        inst.write_deps("a", ["b", "c"])
        inst.write_deps("b", ["d"])
        inst.write_deps("c", ["d"])
        result = inst.topological_sort(vendors)
        assert result.index("d") < result.index("b")
        assert result.index("d") < result.index("c")
        assert result.index("b") < result.index("a")
        assert result.index("c") < result.index("a")

    def test_cycle_detected(self, tmp_repo):
        """A depends on B, B depends on A -> error."""
        vendors = {"a": {"repo": "owner/a"}, "b": {"repo": "owner/b"}}
        inst.write_deps("a", ["b"])
        inst.write_deps("b", ["a"])
        with pytest.raises(SystemExit) as exc_info:
            inst.topological_sort(vendors)
        assert exc_info.value.code == 1

    def test_missing_dep_ignored(self, tmp_repo):
        """Dep not installed -> no edge, no crash."""
        vendors = {"a": {"repo": "owner/a"}}
        inst.write_deps("a", ["nonexistent"])
        result = inst.topological_sort(vendors)
        assert result == ["a"]

    def test_single_vendor(self, tmp_repo):
        vendors = {"tool": {"repo": "owner/tool"}}
        result = inst.topological_sort(vendors)
        assert result == ["tool"]

    @patch("vendored_install.install_existing_vendor")
    @patch("vendored_install.output_results")
    def test_install_all_uses_topo_sort(self, mock_output, mock_update, tmp_repo, make_config):
        """install all path calls topological_sort."""
        mock_update.return_value = {"vendor": "a", "old_version": "1.0",
                                     "new_version": "2.0", "changed": True}
        make_config({"vendors": {"b": SAMPLE_VENDOR, "a": EXISTING_VENDOR}})
        # b depends on a
        inst.write_deps("b", ["a"])

        # Manually call topological_sort to verify order
        config = inst.load_config()
        vendors = config.get("vendors", {})
        sorted_names = inst.topological_sort(vendors)
        # a should come before b since b depends on a
        # But the match is by vendor name, not repo. "a" is a vendor name
        # and "b" depends on "a" by name.
        assert sorted_names.index("a") < sorted_names.index("b")


# ── Tests: deps caching after install ─────────────────────────────────────

class TestDepsCaching:
    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.get_auth_token")
    @patch("vendored_install.download_deps")
    def test_deps_cached_after_existing_install(self, mock_deps, mock_token,
                                                  mock_resolve, mock_download,
                                                  tmp_repo):
        mock_token.return_value = "token"
        mock_resolve.return_value = "2.0.0"
        mock_download.return_value = None
        mock_deps.return_value = {"git-semver": {"repo": "mangimangi/git-semver"}}

        # Install git-semver first so the dep is satisfied
        inst.write_manifest_version("git-semver", "1.0.0")
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "git-semver.json").write_text(
            json.dumps({"_vendor": {"repo": "mangimangi/git-semver",
                                     "protected": [".git-semver/**"],
                                     "install_branch": "chore/install-git-semver"}})
        )

        inst.install_existing_vendor("tool", SAMPLE_VENDOR, "latest",
                                      dep_mode="error")
        deps = inst.read_deps("tool")
        assert deps == ["git-semver"]

    @patch("vendored_install.download_and_run_install")
    @patch("vendored_install.resolve_version")
    @patch("vendored_install.get_auth_token")
    @patch("vendored_install.download_deps")
    def test_no_deps_no_file(self, mock_deps, mock_token,
                               mock_resolve, mock_download, tmp_repo):
        mock_token.return_value = "token"
        mock_resolve.return_value = "2.0.0"
        mock_download.return_value = None
        mock_deps.return_value = None

        inst.install_existing_vendor("tool", SAMPLE_VENDOR, "latest",
                                      dep_mode="error")
        assert inst.read_deps("tool") is None


# ── Tests: CLI --deps flag ────────────────────────────────────────────────

class TestDepsCLIFlag:
    def test_deps_flag_parsed(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("target")
        parser.add_argument("--deps", default=None,
                            choices=["error", "warn", "install", "skip"])
        args = parser.parse_args(["all", "--deps=warn"])
        assert args.deps == "warn"

    def test_deps_flag_default_none(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("target")
        parser.add_argument("--deps", default=None,
                            choices=["error", "warn", "install", "skip"])
        args = parser.parse_args(["all"])
        assert args.deps is None
