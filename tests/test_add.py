"""Tests for the vendored/add script."""

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── Import add script as module ───────────────────────────────────────────

ROOT = Path(__file__).parent.parent


def _import_add():
    filepath = str(ROOT / "vendored" / "add")
    loader = importlib.machinery.SourceFileLoader("vendored_add", filepath)
    spec = importlib.util.spec_from_loader("vendored_add", loader, origin=filepath)
    module = importlib.util.module_from_spec(spec)
    sys.modules["vendored_add"] = module
    spec.loader.exec_module(module)
    return module


add_mod = _import_add()


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


EXISTING_VENDOR = {
    "repo": "owner/existing-tool",
    "install_branch": "chore/install-existing-tool",
    "protected": [".existing-tool/**"],
}


# ── Tests: PreValidate ────────────────────────────────────────────────────

class TestPreValidate:
    @patch("vendored_add.subprocess.run")
    def test_repo_with_install_sh_passes(self, mock_run):
        """Mock GitHub API returns install.sh — no error."""
        mock_run.return_value = MagicMock(returncode=0, stdout="install.sh\n")
        # Should not raise
        add_mod.check_install_sh("owner/tool", "token")

    @patch("vendored_add.subprocess.run")
    def test_repo_without_install_sh_fails(self, mock_run):
        """Mock API returns 404 — exits with 'does not implement git-vendored'."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Not Found")
        with pytest.raises(SystemExit) as exc_info:
            add_mod.check_install_sh("owner/tool", "token")
        assert exc_info.value.code == 1

    @patch("vendored_add.subprocess.run")
    def test_repo_not_found_fails(self, mock_run):
        """Mock API returns 404 for repo — exits with auth hint."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Not Found")
        with pytest.raises(SystemExit) as exc_info:
            add_mod.check_repo_exists("owner/nonexistent", "token")
        assert exc_info.value.code == 1

    @patch("vendored_add.subprocess.run")
    def test_version_resolvable_from_releases(self, mock_run):
        """Mock releases API returns tag — version resolved."""
        mock_run.return_value = MagicMock(returncode=0, stdout="v1.2.3\n")
        version = add_mod.resolve_version("owner/tool", "token")
        assert version == "1.2.3"

    @patch("vendored_add.subprocess.run")
    def test_version_resolvable_from_version_file(self, mock_run):
        """Mock releases fails, VERSION file fallback works."""
        import base64
        encoded = base64.b64encode(b"2.0.0\n").decode()

        def side_effect(cmd, **kwargs):
            if "releases/latest" in cmd[2]:
                return MagicMock(returncode=1, stdout="")
            if "contents/VERSION" in cmd[2]:
                return MagicMock(returncode=0, stdout=encoded + "\n")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = side_effect
        version = add_mod.resolve_version("owner/tool", "token")
        assert version == "2.0.0"

    @patch("vendored_add.subprocess.run")
    def test_version_not_resolvable_fails(self, mock_run):
        """Both methods fail — exits with error."""
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        with pytest.raises(SystemExit) as exc_info:
            add_mod.resolve_version("owner/tool", "token")
        assert exc_info.value.code == 1


# ── Tests: SnapshotAndDiff ────────────────────────────────────────────────

class TestSnapshotAndDiff:
    def test_detects_new_config_entry(self):
        """Config before has 1 vendor, after has 2 — new entry found."""
        before = {"existing": EXISTING_VENDOR}
        after = {
            "existing": EXISTING_VENDOR,
            "new-tool": {"repo": "owner/new-tool", "protected": [".new-tool/**"], "install_branch": "chore/install-new-tool"},
        }
        key, entry = add_mod.find_new_entry(before, after)
        assert key == "new-tool"
        assert entry["repo"] == "owner/new-tool"

    def test_no_new_entry_fails(self):
        """Config unchanged after install.sh — returns None."""
        before = {"existing": EXISTING_VENDOR}
        after = {"existing": EXISTING_VENDOR}
        key, entry = add_mod.find_new_entry(before, after)
        assert key is None
        assert entry is None


# ── Tests: PostValidate ───────────────────────────────────────────────────

class TestPostValidate:
    def test_valid_entry_passes(self):
        """New entry has repo, protected, install_branch — success."""
        entry = {
            "repo": "owner/tool",
            "protected": [".tool/**"],
            "install_branch": "chore/install-tool",
        }
        # Should not raise
        add_mod.validate_entry("tool", entry)

    def test_missing_repo_fails(self):
        """Missing repo — exits with clear message."""
        entry = {"protected": [".tool/**"], "install_branch": "chore/install-tool"}
        with pytest.raises(SystemExit) as exc_info:
            add_mod.validate_entry("tool", entry)
        assert exc_info.value.code == 1

    def test_missing_protected_fails(self):
        """Missing protected — exits with clear message."""
        entry = {"repo": "owner/tool", "install_branch": "chore/install-tool"}
        with pytest.raises(SystemExit) as exc_info:
            add_mod.validate_entry("tool", entry)
        assert exc_info.value.code == 1

    def test_missing_install_branch_fails(self):
        """Missing install_branch — exits with clear message."""
        entry = {"repo": "owner/tool", "protected": [".tool/**"]}
        with pytest.raises(SystemExit) as exc_info:
            add_mod.validate_entry("tool", entry)
        assert exc_info.value.code == 1


# ── Tests: AddVendor (integration) ───────────────────────────────────────

class TestAddVendor:
    @patch("vendored_add.download_and_run_install")
    @patch("vendored_add.resolve_version")
    @patch("vendored_add.check_install_sh")
    @patch("vendored_add.check_repo_exists")
    @patch("vendored_add.get_auth_token")
    def test_add_new_vendor(self, mock_token, mock_exists, mock_install_sh,
                            mock_version, mock_download, make_config, tmp_repo, capsys):
        """Full flow: pre-validate -> run install.sh -> post-validate -> success output."""
        mock_token.return_value = "token"
        mock_version.return_value = "1.0.0"

        # Start with empty vendors
        make_config({"vendors": {}})

        # Simulate install.sh adding a vendor entry to config
        def fake_download(repo, version, token):
            config = add_mod.load_config()
            config["vendors"]["new-tool"] = {
                "repo": "owner/new-tool",
                "protected": [".new-tool/**"],
                "install_branch": "chore/install-new-tool",
            }
            add_mod.save_config(config)

        mock_download.side_effect = fake_download

        # Run main with args
        with patch("sys.argv", ["add", "owner/new-tool"]):
            add_mod.main()

        out = capsys.readouterr().out
        assert "Added vendor: new-tool" in out
        assert "owner/new-tool" in out

    @patch("vendored_add.get_auth_token")
    def test_add_already_registered_fails(self, mock_token, make_config):
        """Vendor already in config — exits with 'already registered'."""
        mock_token.return_value = "token"
        make_config({"vendors": {"existing": {"repo": "owner/existing-tool"}}})

        with patch("sys.argv", ["add", "owner/existing-tool"]):
            with patch("vendored_add.check_repo_exists"):
                with patch("vendored_add.check_install_sh"):
                    with patch("vendored_add.resolve_version", return_value="1.0.0"):
                        with pytest.raises(SystemExit) as exc_info:
                            add_mod.main()
                        assert exc_info.value.code == 1

    @patch("vendored_add.download_and_run_install")
    @patch("vendored_add.resolve_version")
    @patch("vendored_add.check_install_sh")
    @patch("vendored_add.check_repo_exists")
    @patch("vendored_add.get_auth_token")
    def test_add_with_custom_name(self, mock_token, mock_exists, mock_install_sh,
                                   mock_version, mock_download, make_config, tmp_repo, capsys):
        """--name flag overrides vendor key in config lookup."""
        mock_token.return_value = "token"
        mock_version.return_value = "1.0.0"

        # Existing vendor with different name but same repo should not conflict
        make_config({"vendors": {}})

        def fake_download(repo, version, token):
            config = add_mod.load_config()
            config["vendors"]["my-custom-name"] = {
                "repo": "owner/tool",
                "protected": [".tool/**"],
                "install_branch": "chore/install-tool",
            }
            add_mod.save_config(config)

        mock_download.side_effect = fake_download

        with patch("sys.argv", ["add", "owner/tool", "--name", "my-custom-name"]):
            add_mod.main()

        out = capsys.readouterr().out
        assert "Added vendor: my-custom-name" in out


# ── Tests: AddOutput ─────────────────────────────────────────────────────

class TestAddOutput:
    @patch("vendored_add.download_and_run_install")
    @patch("vendored_add.resolve_version")
    @patch("vendored_add.check_install_sh")
    @patch("vendored_add.check_repo_exists")
    @patch("vendored_add.get_auth_token")
    def test_summary_shows_vendor_name(self, mock_token, mock_exists, mock_install_sh,
                                        mock_version, mock_download, make_config, tmp_repo, capsys):
        """Output includes vendor name."""
        mock_token.return_value = "token"
        mock_version.return_value = "1.0.0"
        make_config({"vendors": {}})

        def fake_download(repo, version, token):
            config = add_mod.load_config()
            config["vendors"]["mytool"] = {
                "repo": "owner/mytool",
                "protected": [".mytool/**"],
                "install_branch": "chore/install-mytool",
            }
            add_mod.save_config(config)

        mock_download.side_effect = fake_download

        with patch("sys.argv", ["add", "owner/mytool"]):
            add_mod.main()

        out = capsys.readouterr().out
        assert "mytool" in out

    @patch("vendored_add.download_and_run_install")
    @patch("vendored_add.resolve_version")
    @patch("vendored_add.check_install_sh")
    @patch("vendored_add.check_repo_exists")
    @patch("vendored_add.get_auth_token")
    def test_summary_shows_version(self, mock_token, mock_exists, mock_install_sh,
                                    mock_version, mock_download, make_config, tmp_repo, capsys):
        """Output includes installed version."""
        mock_token.return_value = "token"
        mock_version.return_value = "3.5.0"
        make_config({"vendors": {}})

        def fake_download(repo, version, token):
            config = add_mod.load_config()
            config["vendors"]["tool"] = {
                "repo": "owner/tool",
                "protected": [".tool/**"],
                "install_branch": "chore/install-tool",
            }
            add_mod.save_config(config)

        mock_download.side_effect = fake_download

        with patch("sys.argv", ["add", "owner/tool"]):
            add_mod.main()

        out = capsys.readouterr().out
        assert "3.5.0" in out

    @patch("vendored_add.download_and_run_install")
    @patch("vendored_add.resolve_version")
    @patch("vendored_add.check_install_sh")
    @patch("vendored_add.check_repo_exists")
    @patch("vendored_add.get_auth_token")
    def test_summary_shows_registered_files(self, mock_token, mock_exists, mock_install_sh,
                                             mock_version, mock_download, make_config, tmp_repo, capsys):
        """Output includes what install.sh added to config."""
        mock_token.return_value = "token"
        mock_version.return_value = "1.0.0"
        make_config({"vendors": {}})

        def fake_download(repo, version, token):
            config = add_mod.load_config()
            config["vendors"]["tool"] = {
                "repo": "owner/tool",
                "protected": [".tool/**", ".github/workflows/tool.yml"],
                "install_branch": "chore/install-tool",
                "allowed": [".tool/config.json"],
            }
            add_mod.save_config(config)

        mock_download.side_effect = fake_download

        with patch("sys.argv", ["add", "owner/tool"]):
            add_mod.main()

        out = capsys.readouterr().out
        assert ".tool/**" in out
        assert ".tool/config.json" in out
