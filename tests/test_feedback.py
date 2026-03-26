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
    spec = importlib.util.spec_from_loader("vendored_feedback", loader, origin=filepath)
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
