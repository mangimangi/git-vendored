"""Tests for the .vendored/feedback command."""

import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path
from io import StringIO

import pytest

ROOT = Path(__file__).parent.parent


def _import_feedback():
    filepath = str(ROOT / "templates" / "feedback")
    loader = importlib.machinery.SourceFileLoader("vendored_feedback", filepath)
    spec = importlib.util.spec_from_file_location("vendored_feedback", filepath, loader=loader)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = filepath
    sys.modules["vendored_feedback"] = module
    spec.loader.exec_module(module)
    return module


fb = _import_feedback()


@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """Create a temporary directory with .vendored/ and chdir into it."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".vendored" / "configs").mkdir(parents=True)
    (tmp_path / ".vendored" / "manifests").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def make_vendor(tmp_repo):
    """Create a vendor config and version file."""
    def _make(name, config, version="1.0.0"):
        config_path = tmp_repo / ".vendored" / "configs" / f"{name}.json"
        config_path.write_text(json.dumps({"_vendor": config}, indent=2) + "\n")
        version_path = tmp_repo / ".vendored" / "manifests" / f"{name}.version"
        version_path.write_text(f"{version}\n")
    return _make


class TestGetSupportInfo:
    def test_smart_default_from_repo(self):
        config = {"repo": "owner/my-tool"}
        info = fb.get_support_info("my-tool", config)
        assert info["issues"] == "https://github.com/owner/my-tool/issues"

    def test_explicit_support_url(self):
        config = {
            "repo": "owner/my-tool",
            "support": {
                "issues": "https://custom.example.com/issues",
                "instructions": "Include logs",
                "labels": ["bug"],
            },
        }
        info = fb.get_support_info("my-tool", config)
        assert info["issues"] == "https://custom.example.com/issues"
        assert info["instructions"] == "Include logs"
        assert info["labels"] == ["bug"]

    def test_no_repo_no_support(self):
        info = fb.get_support_info("orphan", {})
        assert info["issues"] == ""
        assert info["instructions"] == ""
        assert info["labels"] == []

    def test_support_without_issues_uses_repo(self):
        config = {
            "repo": "owner/tool",
            "support": {"instructions": "Run diagnostics"},
        }
        info = fb.get_support_info("tool", config)
        assert info["issues"] == "https://github.com/owner/tool/issues"
        assert info["instructions"] == "Run diagnostics"


class TestLoadVendors:
    def test_loads_per_vendor_configs(self, make_vendor):
        make_vendor("tool-a", {"repo": "owner/tool-a"})
        make_vendor("tool-b", {"repo": "owner/tool-b"})
        vendors = fb.load_vendors()
        assert "tool-a" in vendors
        assert "tool-b" in vendors
        assert vendors["tool-a"]["repo"] == "owner/tool-a"

    def test_empty_configs_dir(self, tmp_repo):
        vendors = fb.load_vendors()
        assert vendors == {}

    def test_prefers_registry_file(self, tmp_repo):
        """load_vendors reads from .registry file when available."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True, exist_ok=True)
        (configs_dir / "tool.json").write_text(json.dumps(
            {"_vendor": {"repo": "owner/old"}}
        ))

        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True, exist_ok=True)
        (manifests_dir / "tool.registry").write_text(json.dumps(
            {"repo": "owner/new"}
        ))

        vendors = fb.load_vendors()
        assert vendors["tool"]["repo"] == "owner/new"


class TestGetInstalledVendors:
    def test_finds_installed(self, make_vendor):
        make_vendor("tool-a", {"repo": "owner/tool-a"})
        installed = fb.get_installed_vendors()
        assert "tool-a" in installed

    def test_no_manifests_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        installed = fb.get_installed_vendors()
        assert installed == set()


class TestPrintVendorFeedback:
    def test_prints_basic_info(self, make_vendor, capsys):
        make_vendor("my-tool", {"repo": "owner/my-tool"}, version="2.1.0")
        config = fb.load_vendors()["my-tool"]
        fb.print_vendor_feedback("my-tool", config)
        output = capsys.readouterr().out
        assert "my-tool" in output
        assert "owner/my-tool" in output
        assert "2.1.0" in output
        assert "https://github.com/owner/my-tool/issues" in output

    def test_prints_explicit_support(self, make_vendor, capsys):
        make_vendor("my-tool", {
            "repo": "owner/my-tool",
            "support": {
                "issues": "https://custom.url/issues",
                "instructions": "Include logs",
                "labels": ["bug", "help"],
            },
        })
        config = fb.load_vendors()["my-tool"]
        fb.print_vendor_feedback("my-tool", config)
        output = capsys.readouterr().out
        assert "https://custom.url/issues" in output
        assert "Include logs" in output
        assert "bug, help" in output


class TestMain:
    def test_shows_all_vendors(self, make_vendor, capsys, monkeypatch):
        make_vendor("alpha", {"repo": "owner/alpha"})
        make_vendor("beta", {"repo": "owner/beta"})
        monkeypatch.setattr(sys, "argv", ["feedback"])
        fb.main()
        output = capsys.readouterr().out
        assert "alpha" in output
        assert "beta" in output

    def test_shows_specific_vendor(self, make_vendor, capsys, monkeypatch):
        make_vendor("alpha", {"repo": "owner/alpha"})
        make_vendor("beta", {"repo": "owner/beta"})
        monkeypatch.setattr(sys, "argv", ["feedback", "alpha"])
        fb.main()
        output = capsys.readouterr().out
        assert "alpha" in output

    def test_unknown_vendor_errors(self, make_vendor, monkeypatch):
        make_vendor("alpha", {"repo": "owner/alpha"})
        monkeypatch.setattr(sys, "argv", ["feedback", "nonexistent"])
        with pytest.raises(SystemExit, match="1"):
            fb.main()

    def test_no_vendors_installed(self, tmp_repo, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["feedback"])
        fb.main()
        output = capsys.readouterr().out
        assert "No installed vendors" in output


class TestLoadVendorsFallbacks:
    def test_flat_config_without_vendor_key(self, tmp_repo):
        (tmp_repo / ".vendored" / "configs" / "tool.json").write_text(
            json.dumps({"repo": "owner/tool"}))
        assert fb.load_vendors() == {"tool": {"repo": "owner/tool"}}

    def test_monolithic_config_json(self, tmp_repo):
        (tmp_repo / ".vendored" / "config.json").write_text(json.dumps(
            {"vendors": {"legacy": {"repo": "owner/legacy"}}}))
        assert fb.load_vendors() == {"legacy": {"repo": "owner/legacy"}}

    def test_monolithic_config_without_vendors_key(self, tmp_repo):
        (tmp_repo / ".vendored" / "config.json").write_text("{}")
        assert fb.load_vendors() == {}

    def test_no_vendored_dir_at_all(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert fb.load_vendors() == {}


class TestMainOutput:
    def test_specific_vendor_full_output(self, make_vendor, capsys, monkeypatch):
        make_vendor("alpha", {
            "repo": "owner/alpha",
            "support": {"instructions": "Attach logs", "labels": ["bug", "vendored"]},
        }, version="1.4.2")
        make_vendor("beta", {"repo": "owner/beta"})
        monkeypatch.setattr(sys, "argv", ["feedback", "alpha"])
        fb.main()
        out = capsys.readouterr().out
        assert out == (
            "Vendor support info:\n\n"
            "  alpha\n"
            "    repo:    owner/alpha\n"
            "    version: 1.4.2\n"
            "    issues:  https://github.com/owner/alpha/issues\n"
            "    info:    Attach logs\n"
            "    labels:  bug, vendored\n"
            "\n"
        )

    def test_specific_vendor_not_installed_has_no_version(
            self, tmp_repo, capsys, monkeypatch):
        """A configured vendor without a .version file still shows; no version line."""
        (tmp_repo / ".vendored" / "configs" / "tool.json").write_text(
            json.dumps({"_vendor": {}}))
        monkeypatch.setattr(sys, "argv", ["feedback", "tool"])
        fb.main()
        out = capsys.readouterr().out
        assert "  tool\n    repo:    unknown\n" in out
        assert "version:" not in out
        assert "issues:" not in out

    def test_all_vendors_sorted_and_only_installed(self, make_vendor, tmp_repo,
                                                   capsys, monkeypatch):
        make_vendor("zeta", {"repo": "owner/zeta"}, version="3.0.0")
        make_vendor("alpha", {"repo": "owner/alpha"}, version="1.0.0")
        # configured but not installed (no .version)
        (tmp_repo / ".vendored" / "configs" / "ghost.json").write_text(
            json.dumps({"_vendor": {"repo": "owner/ghost"}}))
        monkeypatch.setattr(sys, "argv", ["feedback"])
        fb.main()
        out = capsys.readouterr().out
        assert out.startswith("Vendor support info:\n\n")
        assert out.index("  alpha\n") < out.index("  zeta\n")
        assert "ghost" not in out
        assert "version: 3.0.0" in out

    def test_unknown_vendor_message(self, make_vendor, capsys, monkeypatch):
        make_vendor("beta", {"repo": "owner/beta"})
        make_vendor("alpha", {"repo": "owner/alpha"})
        monkeypatch.setattr(sys, "argv", ["feedback", "nope"])
        with pytest.raises(SystemExit) as exc_info:
            fb.main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Unknown vendor: nope" in captured.err
        assert "Installed vendors: alpha, beta" in captured.err

    def test_no_manifests_dir(self, tmp_path, capsys, monkeypatch):
        """Configs present but manifests/ missing: nothing counts as installed."""
        monkeypatch.chdir(tmp_path)
        configs = tmp_path / ".vendored" / "configs"
        configs.mkdir(parents=True)
        (configs / "tool.json").write_text(json.dumps({"_vendor": {"repo": "o/tool"}}))
        monkeypatch.setattr(sys, "argv", ["feedback"])
        fb.main()
        assert capsys.readouterr().out == "No installed vendors found.\n"

    def test_installed_but_unconfigured_is_skipped(self, tmp_repo, capsys,
                                                   monkeypatch):
        (tmp_repo / ".vendored" / "manifests" / "orphan.version").write_text("1\n")
        monkeypatch.setattr(sys, "argv", ["feedback"])
        fb.main()
        assert capsys.readouterr().out == "No installed vendors found.\n"
