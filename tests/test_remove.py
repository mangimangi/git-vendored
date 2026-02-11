"""Tests for the templates/remove script."""

import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Import remove script as module ────────────────────────────────────────

ROOT = Path(__file__).parent.parent


def _import_remove():
    filepath = str(ROOT / "templates" / "remove")
    loader = importlib.machinery.SourceFileLoader("vendored_remove", filepath)
    spec = importlib.util.spec_from_loader("vendored_remove", loader, origin=filepath)
    module = importlib.util.module_from_spec(spec)
    sys.modules["vendored_remove"] = module
    spec.loader.exec_module(module)
    return module


rem = _import_remove()


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


# ── Tests: load_config ────────────────────────────────────────────────────

class TestLoadConfig:
    def test_loads_valid_config(self, make_config):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        config = rem.load_config()
        assert "vendors" in config

    def test_missing_config_exits(self, tmp_repo):
        with pytest.raises(SystemExit) as exc_info:
            rem.load_config("/nonexistent/config.json")
        assert exc_info.value.code == 1


# ── Tests: read_manifest ─────────────────────────────────────────────────

class TestReadManifest:
    def test_reads_manifest(self, tmp_repo):
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n.tool/lib.py\n")
        result = rem.read_manifest("tool")
        assert result == [".tool/script.sh", ".tool/lib.py"]

    def test_returns_none_when_missing(self, tmp_repo):
        assert rem.read_manifest("nonexistent") is None


# ── Tests: find_files_by_patterns ─────────────────────────────────────────

class TestFindFilesByPatterns:
    def test_finds_glob_matches(self, tmp_repo):
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")
        (tmp_repo / ".tool" / "lib.py").write_text("# lib")
        files = rem.find_files_by_patterns([".tool/**"])
        assert ".tool/script.sh" in files
        assert ".tool/lib.py" in files

    def test_no_matches(self, tmp_repo):
        files = rem.find_files_by_patterns([".nonexistent/**"])
        assert files == []


# ── Tests: get_files_to_remove ────────────────────────────────────────────

class TestGetFilesToRemove:
    def test_manifest_source(self, tmp_repo):
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")
        (manifests_dir / "tool.version").write_text("1.0.0\n")

        files, source = rem.get_files_to_remove("tool", SAMPLE_VENDOR)
        assert source == "manifest"
        assert ".tool/script.sh" in files
        assert ".vendored/manifests/tool.files" in files
        assert ".vendored/manifests/tool.version" in files

    def test_pattern_fallback(self, tmp_repo):
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")
        (tmp_repo / ".tool" / "config.json").write_text("{}")

        files, source = rem.get_files_to_remove("tool", SAMPLE_VENDOR)
        assert source == "patterns"
        assert ".tool/script.sh" in files
        # config.json is in allowed, should be excluded
        assert ".tool/config.json" not in files

    def test_empty_protected(self, tmp_repo):
        vendor_config = {"repo": "owner/tool", "protected": []}
        files, source = rem.get_files_to_remove("tool", vendor_config)
        assert files == []
        assert source == "patterns"


# ── Tests: remove_files ───────────────────────────────────────────────────

class TestRemoveFiles:
    def test_removes_existing_files(self, tmp_repo):
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")
        (tmp_repo / ".tool" / "lib.py").write_text("# lib")

        removed = rem.remove_files([".tool/script.sh", ".tool/lib.py"])
        assert removed == 2
        assert not (tmp_repo / ".tool" / "script.sh").exists()
        assert not (tmp_repo / ".tool" / "lib.py").exists()

    def test_handles_already_missing(self, tmp_repo):
        removed = rem.remove_files([".tool/nonexistent.sh"])
        assert removed == 0


# ── Tests: cleanup_empty_dirs ─────────────────────────────────────────────

class TestCleanupEmptyDirs:
    def test_removes_empty_parent(self, tmp_repo):
        (tmp_repo / ".tool" / "sub").mkdir(parents=True)
        (tmp_repo / ".tool" / "sub" / "file.sh").write_text("#!/bin/bash")
        os.remove(str(tmp_repo / ".tool" / "sub" / "file.sh"))

        rem.cleanup_empty_dirs([".tool/sub/file.sh"])
        assert not (tmp_repo / ".tool" / "sub").exists()
        assert not (tmp_repo / ".tool").exists()

    def test_preserves_non_empty_parent(self, tmp_repo):
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")
        (tmp_repo / ".tool" / "keep.txt").write_text("keep")
        os.remove(str(tmp_repo / ".tool" / "script.sh"))

        rem.cleanup_empty_dirs([".tool/script.sh"])
        # .tool should still exist because keep.txt is there
        assert (tmp_repo / ".tool").exists()


# ── Tests: main (integration) ────────────────────────────────────────────

class TestMain:
    def test_remove_with_manifest(self, make_config, tmp_repo, capsys):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})

        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")
        (manifests_dir / "tool.version").write_text("1.0.0\n")

        with patch("sys.argv", ["remove", "tool", "--force"]):
            rem.main()

        # Verify files removed
        assert not (tmp_repo / ".tool" / "script.sh").exists()
        assert not (manifests_dir / "tool.files").exists()
        assert not (manifests_dir / "tool.version").exists()

        # Verify config updated
        config = json.loads((tmp_repo / ".vendored" / "config.json").read_text())
        assert "tool" not in config["vendors"]

        out = capsys.readouterr().out
        assert "Removed" in out

    def test_remove_with_pattern_fallback(self, make_config, tmp_repo, capsys):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})

        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")

        with patch("sys.argv", ["remove", "tool", "--force"]):
            rem.main()

        assert not (tmp_repo / ".tool" / "script.sh").exists()
        config = json.loads((tmp_repo / ".vendored" / "config.json").read_text())
        assert "tool" not in config["vendors"]

    def test_remove_unknown_vendor_exits(self, make_config):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})

        with patch("sys.argv", ["remove", "nonexistent"]):
            with pytest.raises(SystemExit) as exc_info:
                rem.main()
            assert exc_info.value.code == 1

    def test_remove_no_files_still_removes_config(self, make_config, tmp_repo, capsys):
        vendor_config = {"repo": "owner/empty", "protected": []}
        make_config({"vendors": {"empty": vendor_config}})

        with patch("sys.argv", ["remove", "empty", "--force"]):
            rem.main()

        config = json.loads((tmp_repo / ".vendored" / "config.json").read_text())
        assert "empty" not in config["vendors"]

    def test_abort_without_force(self, make_config, tmp_repo, capsys):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")

        with patch("sys.argv", ["remove", "tool"]):
            with patch("builtins.input", return_value="n"):
                with pytest.raises(SystemExit) as exc_info:
                    rem.main()
                assert exc_info.value.code == 0

        # Files should still exist
        assert (tmp_repo / ".tool" / "script.sh").exists()

    def test_confirm_with_yes(self, make_config, tmp_repo, capsys):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")

        with patch("sys.argv", ["remove", "tool"]):
            with patch("builtins.input", return_value="y"):
                rem.main()

        assert not (tmp_repo / ".tool" / "script.sh").exists()

    def test_cleans_up_empty_directories(self, make_config, tmp_repo, capsys):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})

        (tmp_repo / ".tool" / "sub").mkdir(parents=True)
        (tmp_repo / ".tool" / "sub" / "deep.sh").write_text("#!/bin/bash")
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/sub/deep.sh\n")
        (manifests_dir / "tool.version").write_text("1.0.0\n")

        with patch("sys.argv", ["remove", "tool", "--force"]):
            rem.main()

        assert not (tmp_repo / ".tool").exists()
