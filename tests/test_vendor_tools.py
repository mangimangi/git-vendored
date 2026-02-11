"""Tests for vendor tool config loading (prl.py and git-semver).

Verifies that vendored tools read project config from .vendored/configs/
with fallback to legacy dot-directory config files, and that they ignore
the _vendor key when loading from vendored config.
"""

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


# ── Import prl.py as module ────────────────────────────────────────────────

def _import_prl():
    filepath = str(ROOT / ".pearls" / "prl.py")
    loader = importlib.machinery.SourceFileLoader("prl", filepath)
    spec = importlib.util.spec_from_loader("prl", loader, origin=filepath)
    module = importlib.util.module_from_spec(spec)
    sys.modules["prl"] = module
    spec.loader.exec_module(module)
    return module


prl = _import_prl()


# ── Import git-semver as module ────────────────────────────────────────────

def _import_semver():
    filepath = str(ROOT / ".semver" / "git-semver")
    loader = importlib.machinery.SourceFileLoader("git_semver", filepath)
    spec = importlib.util.spec_from_loader("git_semver", loader, origin=filepath)
    module = importlib.util.module_from_spec(spec)
    sys.modules["git_semver"] = module
    spec.loader.exec_module(module)
    return module


semver = _import_semver()


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """Create a temporary repo directory and chdir into it."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ── Tests: prl.py config loading ──────────────────────────────────────────

class TestPrlConfigLoading:
    def test_reads_from_vendored_configs(self, tmp_repo, monkeypatch):
        """prl reads project config from .vendored/configs/pearls.json."""
        # Set up .pearls dir (needed for find_pearls_dir)
        pearls_dir = tmp_repo / ".pearls"
        pearls_dir.mkdir()
        (pearls_dir / "issues.jsonl").touch()

        # Vendored config with _vendor + project keys
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        vendored_config = {
            "_vendor": {"repo": "owner/pearls", "install_branch": "chore/install-pearls"},
            "prefix": "test",
            "description": "Test project",
        }
        (configs_dir / "pearls.json").write_text(json.dumps(vendored_config))

        # Monkeypatch find_pearls_dir to use tmp_path
        monkeypatch.setattr(prl, "find_pearls_dir", lambda: pearls_dir)

        config = prl.load_config()
        assert config["prefix"] == "test"
        assert config["description"] == "Test project"
        assert "_vendor" not in config

    def test_falls_back_to_legacy_config(self, tmp_repo, monkeypatch):
        """prl falls back to .pearls/config.json when vendored config doesn't exist."""
        pearls_dir = tmp_repo / ".pearls"
        pearls_dir.mkdir()
        legacy_config = {"prefix": "legacy", "docs": ["README.md"]}
        (pearls_dir / "config.json").write_text(json.dumps(legacy_config))

        monkeypatch.setattr(prl, "find_pearls_dir", lambda: pearls_dir)

        config = prl.load_config()
        assert config["prefix"] == "legacy"
        assert config["docs"] == ["README.md"]

    def test_vendored_config_takes_priority(self, tmp_repo, monkeypatch):
        """Vendored config takes priority over legacy .pearls/config.json."""
        pearls_dir = tmp_repo / ".pearls"
        pearls_dir.mkdir()
        (pearls_dir / "config.json").write_text(json.dumps({"prefix": "old"}))

        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        vendored = {"_vendor": {}, "prefix": "new", "description": "Updated"}
        (configs_dir / "pearls.json").write_text(json.dumps(vendored))

        monkeypatch.setattr(prl, "find_pearls_dir", lambda: pearls_dir)

        config = prl.load_config()
        assert config["prefix"] == "new"

    def test_load_prefix_from_vendored(self, tmp_repo, monkeypatch):
        """load_prefix reads from vendored config."""
        pearls_dir = tmp_repo / ".pearls"
        pearls_dir.mkdir()

        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "pearls.json").write_text(json.dumps({
            "_vendor": {"repo": "owner/pearls"},
            "prefix": "myproject",
        }))

        monkeypatch.setattr(prl, "find_pearls_dir", lambda: pearls_dir)

        assert prl.load_prefix() == "myproject"

    def test_missing_prefix_exits(self, tmp_repo, monkeypatch):
        """Missing prefix in config exits with error."""
        pearls_dir = tmp_repo / ".pearls"
        pearls_dir.mkdir()
        (pearls_dir / "config.json").write_text(json.dumps({"docs": ["x"]}))

        monkeypatch.setattr(prl, "find_pearls_dir", lambda: pearls_dir)

        with pytest.raises(SystemExit):
            prl.load_prefix()


# ── Tests: git-semver config loading ──────────────────────────────────────

SAMPLE_SEMVER_CONFIG = {
    "version_file": "VERSION",
    "files": ["install.sh"],
    "updates": {},
    "changelog": True,
}


class TestSemverConfigLoading:
    def test_reads_from_vendored_configs(self, tmp_repo):
        """git-semver reads project config from .vendored/configs/semver.json."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        vendored = {
            "_vendor": {"repo": "owner/semver", "install_branch": "chore/install-semver"},
            **SAMPLE_SEMVER_CONFIG,
        }
        (configs_dir / "semver.json").write_text(json.dumps(vendored))

        config = semver.load_config()
        assert config["files"] == ["install.sh"]
        assert config["version_file"] == "VERSION"
        assert "_vendor" not in config

    def test_falls_back_to_legacy_config(self, tmp_repo):
        """git-semver falls back to .semver/config.json when vendored config missing."""
        semver_dir = tmp_repo / ".semver"
        semver_dir.mkdir()
        (semver_dir / "config.json").write_text(json.dumps(SAMPLE_SEMVER_CONFIG))

        config = semver.load_config()
        assert config["files"] == ["install.sh"]

    def test_vendored_config_takes_priority(self, tmp_repo):
        """Vendored config takes priority over legacy .semver/config.json."""
        semver_dir = tmp_repo / ".semver"
        semver_dir.mkdir()
        (semver_dir / "config.json").write_text(json.dumps(SAMPLE_SEMVER_CONFIG))

        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        vendored = {
            "_vendor": {},
            "version_file": "CUSTOM_VERSION",
            "files": ["src/**"],
            "updates": {"custom": True},
        }
        (configs_dir / "semver.json").write_text(json.dumps(vendored))

        config = semver.load_config()
        assert config["version_file"] == "CUSTOM_VERSION"
        assert config["files"] == ["src/**"]

    def test_ignores_vendor_key(self, tmp_repo):
        """_vendor key is filtered out of loaded config."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        vendored = {
            "_vendor": {"repo": "owner/semver"},
            **SAMPLE_SEMVER_CONFIG,
        }
        (configs_dir / "semver.json").write_text(json.dumps(vendored))

        config = semver.load_config()
        assert "_vendor" not in config

    def test_explicit_path_overrides(self, tmp_repo):
        """Explicit config_path overrides vendored and legacy paths."""
        custom_dir = tmp_repo / "custom"
        custom_dir.mkdir()
        (custom_dir / "my-config.json").write_text(json.dumps(SAMPLE_SEMVER_CONFIG))

        config = semver.load_config(str(custom_dir / "my-config.json"))
        assert config["files"] == ["install.sh"]

    def test_missing_config_exits(self, tmp_repo):
        """Missing config file exits with error."""
        with pytest.raises(SystemExit):
            semver.load_config("/nonexistent/config.json")
