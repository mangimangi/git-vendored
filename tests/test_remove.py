"""Tests for the templates/remove script."""

import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Reload module for each test run to pick up code changes

# ── Import remove script as module ────────────────────────────────────────

ROOT = Path(__file__).parent.parent


def _import_remove():
    filepath = str(ROOT / "templates" / "remove")
    loader = importlib.machinery.SourceFileLoader("vendored_remove", filepath)
    spec = importlib.util.spec_from_file_location("vendored_remove", filepath, loader=loader)
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

    def test_loads_per_vendor_configs(self, tmp_repo):
        """load_config() scans configs/ for per-vendor .json files (flat format)."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps(SAMPLE_VENDOR))
        config = rem.load_config()
        assert "vendors" in config
        assert "tool" in config["vendors"]

    def test_loads_per_vendor_configs_with_vendor_key(self, tmp_repo):
        """load_config() extracts registry from _vendor key."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        vendor_file = {"_vendor": SAMPLE_VENDOR, "custom": "data"}
        (configs_dir / "tool.json").write_text(json.dumps(vendor_file))
        config = rem.load_config()
        assert config["vendors"]["tool"]["repo"] == "owner/tool"
        assert "custom" not in config["vendors"]["tool"]

    def test_empty_configs_dir_falls_back(self, tmp_repo, make_config):
        """Empty configs/ dir falls back to monolithic config.json."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        (tmp_repo / ".vendored" / "configs").mkdir(parents=True)
        config = rem.load_config()
        assert "tool" in config["vendors"]


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


# ── Tests: get_files_to_remove ────────────────────────────────────────────

class TestGetFilesToRemove:
    def test_manifest_source(self, tmp_repo):
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")
        (manifests_dir / "tool.version").write_text("1.0.0\n")

        files = rem.get_files_to_remove("tool")
        assert ".tool/script.sh" in files
        assert ".vendored/manifests/tool.files" in files
        assert ".vendored/manifests/tool.version" in files

    def test_includes_commit_file(self, tmp_repo):
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")
        (manifests_dir / "tool.commit").write_text("a" * 40 + "\n")

        files = rem.get_files_to_remove("tool")
        assert ".vendored/manifests/tool.commit" in files

    def test_includes_schema_file(self, tmp_repo):
        """get_files_to_remove includes .schema file when it exists."""
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")
        (manifests_dir / "tool.version").write_text("1.0.0\n")
        (manifests_dir / "tool.schema").write_text('{"vendor": "tool"}\n')

        files = rem.get_files_to_remove("tool")
        assert ".vendored/manifests/tool.schema" in files

    def test_skips_missing_schema_file(self, tmp_repo):
        """get_files_to_remove does not include .schema when it doesn't exist."""
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")

        files = rem.get_files_to_remove("tool")
        assert ".vendored/manifests/tool.schema" not in files

    def test_includes_registry_file(self, tmp_repo):
        """get_files_to_remove includes .registry file when it exists."""
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")
        (manifests_dir / "tool.registry").write_text('{"repo": "owner/tool"}\n')

        files = rem.get_files_to_remove("tool")
        assert ".vendored/manifests/tool.registry" in files

    def test_error_when_no_manifest(self, tmp_repo):
        """Without a manifest, get_files_to_remove should exit with error."""
        with pytest.raises(SystemExit) as exc_info:
            rem.get_files_to_remove("tool")
        assert exc_info.value.code == 1


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
        (manifests_dir / "tool.commit").write_text("a" * 40 + "\n")

        with patch("sys.argv", ["remove", "tool", "--force"]):
            rem.main()

        # Verify files removed
        assert not (tmp_repo / ".tool" / "script.sh").exists()
        assert not (manifests_dir / "tool.files").exists()
        assert not (manifests_dir / "tool.version").exists()
        assert not (manifests_dir / "tool.commit").exists()

        # Verify config updated
        config = json.loads((tmp_repo / ".vendored" / "config.json").read_text())
        assert "tool" not in config["vendors"]

        out = capsys.readouterr().out
        assert "Removed" in out

    def test_remove_without_manifest_errors(self, make_config, tmp_repo, capsys):
        """Remove should error when no manifest exists (no pattern fallback)."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})

        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")

        with patch("sys.argv", ["remove", "tool", "--force"]):
            with pytest.raises(SystemExit) as exc_info:
                rem.main()
            assert exc_info.value.code == 1

        # Files should NOT have been deleted (no manifest = no removal)
        assert (tmp_repo / ".tool" / "script.sh").exists()
        # Config should NOT have been modified
        config = json.loads((tmp_repo / ".vendored" / "config.json").read_text())
        assert "tool" in config["vendors"]

    def test_remove_unknown_vendor_exits(self, make_config):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})

        with patch("sys.argv", ["remove", "nonexistent"]):
            with pytest.raises(SystemExit) as exc_info:
                rem.main()
            assert exc_info.value.code == 1

    def test_remove_no_manifest_errors(self, make_config, tmp_repo, capsys):
        """Even if vendor exists in config, no manifest = error."""
        vendor_config = {"repo": "owner/empty", "protected": []}
        make_config({"vendors": {"empty": vendor_config}})

        with patch("sys.argv", ["remove", "empty", "--force"]):
            with pytest.raises(SystemExit) as exc_info:
                rem.main()
            assert exc_info.value.code == 1

        # Config should NOT have been modified
        config = json.loads((tmp_repo / ".vendored" / "config.json").read_text())
        assert "empty" in config["vendors"]

    def test_abort_without_force(self, make_config, tmp_repo, capsys):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")

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
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")

        with patch("sys.argv", ["remove", "tool"]):
            with patch("builtins.input", return_value="y"):
                rem.main()

        assert not (tmp_repo / ".tool" / "script.sh").exists()

    def test_remove_with_per_vendor_config(self, tmp_repo, capsys):
        """Remove deletes the per-vendor config file from configs/."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps(SAMPLE_VENDOR))
        (configs_dir / "other.json").write_text(json.dumps({"repo": "owner/other"}))

        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")
        (manifests_dir / "tool.version").write_text("1.0.0\n")

        with patch("sys.argv", ["remove", "tool", "--force"]):
            rem.main()

        # Verify per-vendor config deleted
        assert not (configs_dir / "tool.json").exists()
        # Other vendor config preserved
        assert (configs_dir / "other.json").exists()

        out = capsys.readouterr().out
        assert "Removed" in out

    def test_cleans_up_pkg_directory(self, make_config, tmp_repo, capsys):
        """Remove cleans up .vendored/pkg/<vendor>/ directory."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})

        pkg_dir = tmp_repo / ".vendored" / "pkg" / "tool"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "script.sh").write_text("#!/bin/bash")
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".vendored/pkg/tool/script.sh\n")
        (manifests_dir / "tool.version").write_text("1.0.0\n")

        with patch("sys.argv", ["remove", "tool", "--force"]):
            rem.main()

        # Verify pkg directory cleaned up
        assert not (tmp_repo / ".vendored" / "pkg" / "tool").exists()
        # pkg/ parent should be cleaned up if empty
        assert not (tmp_repo / ".vendored" / "pkg").exists()

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


# ── Tests: Reverse dependency check ──────────────────────────────────────

class TestReverseDeps:
    def test_check_reverse_deps_none(self, tmp_repo):
        """No .deps files returns empty list."""
        result = rem.check_reverse_deps("tool")
        assert result == []

    def test_check_reverse_deps_found(self, tmp_repo):
        """Vendor-a.deps contains 'tool' -> ['vendor-a']."""
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "vendor-a.deps").write_text("tool\n")

        result = rem.check_reverse_deps("tool")
        assert result == ["vendor-a"]

    def test_check_reverse_deps_multiple(self, tmp_repo):
        """Two vendors depend on same tool."""
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "vendor-a.deps").write_text("tool\n")
        (manifests_dir / "vendor-b.deps").write_text("tool\nother\n")

        result = rem.check_reverse_deps("tool")
        assert sorted(result) == ["vendor-a", "vendor-b"]

    def test_check_reverse_deps_skips_self(self, tmp_repo):
        """Tool's own .deps file is ignored."""
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.deps").write_text("tool\n")

        result = rem.check_reverse_deps("tool")
        assert result == []

    def test_remove_warns_on_reverse_deps(self, make_config, tmp_repo, capsys):
        """Removing a dep'd-on vendor prints warning."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR, "other": SAMPLE_VENDOR}})
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")
        (manifests_dir / "other.deps").write_text("tool\n")

        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")

        with patch("sys.argv", ["remove", "tool"]):
            with patch("builtins.input", return_value="n"):
                with pytest.raises(SystemExit) as exc_info:
                    rem.main()
                assert exc_info.value.code == 0

        out = capsys.readouterr().out
        assert "Warning" in out
        assert "other" in out
        # Files should still exist (aborted)
        assert (tmp_repo / ".tool" / "script.sh").exists()

    def test_remove_force_skips_reverse_dep_prompt(self, make_config, tmp_repo, capsys):
        """--force bypasses the reverse dep prompt."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR, "other": SAMPLE_VENDOR}})
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")
        (manifests_dir / "tool.version").write_text("1.0.0\n")
        (manifests_dir / "other.deps").write_text("tool\n")

        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")

        with patch("sys.argv", ["remove", "tool", "--force"]):
            rem.main()

        out = capsys.readouterr().out
        assert "Warning" in out
        assert "Removed" in out
        assert not (tmp_repo / ".tool" / "script.sh").exists()

    def test_remove_cleans_up_deps_file(self, make_config, tmp_repo, capsys):
        """.deps file deleted during removal."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")
        (manifests_dir / "tool.version").write_text("1.0.0\n")
        (manifests_dir / "tool.deps").write_text("some-dep\n")

        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")

        with patch("sys.argv", ["remove", "tool", "--force"]):
            rem.main()

        assert not (manifests_dir / "tool.deps").exists()

    def test_remove_without_deps_file_still_works(self, make_config, tmp_repo, capsys):
        """Vendor with no .deps file removes cleanly."""
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        manifests_dir = tmp_repo / ".vendored" / "manifests"
        manifests_dir.mkdir(parents=True)
        (manifests_dir / "tool.files").write_text(".tool/script.sh\n")
        (manifests_dir / "tool.version").write_text("1.0.0\n")

        (tmp_repo / ".tool").mkdir()
        (tmp_repo / ".tool" / "script.sh").write_text("#!/bin/bash")

        with patch("sys.argv", ["remove", "tool", "--force"]):
            rem.main()

        assert "Removed" in capsys.readouterr().out
        assert not (tmp_repo / ".tool" / "script.sh").exists()


# ── Tests: registry file, config deletion, prompts, what removal leaves ──

def _write_manifests(tmp_repo, vendor, files, **extra):
    manifests_dir = tmp_repo / ".vendored" / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    (manifests_dir / f"{vendor}.files").write_text("".join(f + "\n" for f in files))
    for suffix, content in extra.items():
        (manifests_dir / f"{vendor}.{suffix}").write_text(content)
    return manifests_dir


def _write_file(tmp_repo, rel, content="x"):
    path = tmp_repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


class TestRegistryFile:
    def test_load_config_prefers_registry_file(self, tmp_repo):
        """The .registry manifest wins over the config's _vendor block."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps(
            {"_vendor": {"repo": "owner/old"}, "custom": 1}))
        _write_manifests(tmp_repo, "tool", [],
                         registry=json.dumps({"repo": "owner/new"}))
        config = rem.load_config()
        assert config["vendors"]["tool"] == {"repo": "owner/new"}

    def test_vendor_known_only_via_registry_is_removable(self, tmp_repo, capsys):
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps({"prefix": "t"}))
        _write_file(tmp_repo, ".vendored/pkg/tool/run.sh")
        manifests_dir = _write_manifests(
            tmp_repo, "tool", [".vendored/pkg/tool/run.sh"],
            registry=json.dumps({"repo": "owner/tool"}), version="1.0.0\n")

        with patch("sys.argv", ["remove", "tool", "--force"]):
            rem.main()

        assert not (manifests_dir / "tool.registry").exists()
        assert not (configs_dir / "tool.json").exists()
        assert "(4 files deleted)" in capsys.readouterr().out


class TestDeleteVendorConfig:
    def test_deletes_existing_config(self, tmp_repo):
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text("{}")
        (configs_dir / "other.json").write_text("{}")
        rem.delete_vendor_config("tool")
        assert not (configs_dir / "tool.json").exists()
        assert (configs_dir / "other.json").exists()

    def test_missing_config_is_noop(self, tmp_repo):
        rem.delete_vendor_config("tool")  # no configs dir at all: no error


class TestPrompts:
    def _setup(self, make_config, tmp_repo, with_dependent=False):
        vendors = {"tool": SAMPLE_VENDOR}
        extra = {"version": "1.0.0\n"}
        if with_dependent:
            vendors["other"] = SAMPLE_VENDOR
        make_config({"vendors": vendors})
        _write_file(tmp_repo, ".tool/script.sh")
        manifests_dir = _write_manifests(tmp_repo, "tool", [".tool/script.sh"], **extra)
        if with_dependent:
            (manifests_dir / "other.deps").write_text("tool\n")
        return manifests_dir

    def test_eof_on_confirm_aborts(self, make_config, tmp_repo, capsys):
        """No stdin (EOF) at the confirm prompt is treated as 'no'."""
        self._setup(make_config, tmp_repo)
        with patch("sys.argv", ["remove", "tool"]):
            with patch("builtins.input", side_effect=EOFError):
                with pytest.raises(SystemExit) as exc_info:
                    rem.main()
        assert exc_info.value.code == 0
        assert "Aborted." in capsys.readouterr().out
        assert (tmp_repo / ".tool" / "script.sh").exists()
        config = json.loads((tmp_repo / ".vendored" / "config.json").read_text())
        assert "tool" in config["vendors"]

    def test_eof_on_reverse_dep_prompt_aborts(self, make_config, tmp_repo, capsys):
        manifests_dir = self._setup(make_config, tmp_repo, with_dependent=True)
        with patch("sys.argv", ["remove", "tool"]):
            with patch("builtins.input", side_effect=EOFError) as mock_input:
                with pytest.raises(SystemExit) as exc_info:
                    rem.main()
        assert exc_info.value.code == 0
        assert mock_input.call_count == 1  # never reaches the second prompt
        out = capsys.readouterr().out
        assert "  - other" in out
        assert "Aborted." in out
        assert (manifests_dir / "tool.files").exists()

    def test_yes_to_both_prompts_removes(self, make_config, tmp_repo, capsys):
        self._setup(make_config, tmp_repo, with_dependent=True)
        with patch("sys.argv", ["remove", "tool"]):
            with patch("builtins.input", return_value="YES") as mock_input:
                rem.main()
        assert mock_input.call_count == 2
        assert not (tmp_repo / ".tool" / "script.sh").exists()
        config = json.loads((tmp_repo / ".vendored" / "config.json").read_text())
        assert config["vendors"] == {"other": SAMPLE_VENDOR}

    def test_listing_marks_missing_files(self, make_config, tmp_repo, capsys):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        _write_file(tmp_repo, ".tool/present.sh")
        _write_manifests(tmp_repo, "tool", [".tool/present.sh", ".tool/gone.sh"])
        with patch("sys.argv", ["remove", "tool", "--force"]):
            rem.main()
        out = capsys.readouterr().out
        assert "    .tool/present.sh" in out
        assert "  ? .tool/gone.sh" in out
        assert "(2 files deleted)" in out  # present.sh + tool.files


class TestUnknownVendorMessage:
    def test_lists_registered_vendors(self, make_config, capsys):
        make_config({"vendors": {"zeta": SAMPLE_VENDOR, "alpha": SAMPLE_VENDOR}})
        with patch("sys.argv", ["remove", "nope", "--force"]):
            with pytest.raises(SystemExit) as exc_info:
                rem.main()
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "::error::Unknown vendor: nope" in out
        assert "Registered vendors: alpha, zeta" in out

    def test_missing_manifest_message(self, make_config, capsys):
        make_config({"vendors": {"tool": SAMPLE_VENDOR}})
        with patch("sys.argv", ["remove", "tool", "--force"]):
            with pytest.raises(SystemExit) as exc_info:
                rem.main()
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "::error::No manifest found for vendor 'tool'" in out
        assert "Expected: .vendored/manifests/tool.files" in out

    def test_no_config_at_all(self, tmp_repo, capsys):
        with patch("sys.argv", ["remove", "tool", "--force"]):
            with pytest.raises(SystemExit) as exc_info:
                rem.main()
        assert exc_info.value.code == 1
        assert "::error::Config not found: .vendored/config.json" in capsys.readouterr().out


class TestWhatRemovalLeaves:
    def test_full_removal_scope(self, tmp_repo, capsys):
        """Deletes manifest-listed files, its manifests and config; keeps the rest."""
        configs_dir = tmp_repo / ".vendored" / "configs"
        configs_dir.mkdir(parents=True)
        (configs_dir / "tool.json").write_text(json.dumps({"_vendor": SAMPLE_VENDOR}))
        (configs_dir / "other.json").write_text(json.dumps({"_vendor": {"repo": "o/other"}}))

        listed = [
            ".vendored/pkg/tool/bin/tool",
            ".vendored/pkg/tool/lib/x.py",
            ".github/workflows/tool.yml",
        ]
        for rel in listed:
            _write_file(tmp_repo, rel)
        other_workflow = _write_file(tmp_repo, ".github/workflows/ci.yml")
        other_pkg = _write_file(tmp_repo, ".vendored/pkg/other/run.sh")
        untracked = _write_file(tmp_repo, ".vendored/pkg/tool/local-notes.txt")

        manifests_dir = _write_manifests(
            tmp_repo, "tool", listed, version="1.0.0\n", deps="other\n",
            schema="{}\n", registry=json.dumps(SAMPLE_VENDOR))
        (manifests_dir / "other.files").write_text(".vendored/pkg/other/run.sh\n")
        (manifests_dir / "other.version").write_text("2.0.0\n")

        with patch("sys.argv", ["remove", "tool", "--force"]):
            rem.main()

        for rel in listed:
            assert not (tmp_repo / rel).exists()
        for suffix in ("files", "version", "deps", "schema", "registry"):
            assert not (manifests_dir / f"tool.{suffix}").exists()
        assert not (configs_dir / "tool.json").exists()
        assert not (tmp_repo / ".vendored/pkg/tool/bin").exists()
        assert not (tmp_repo / ".vendored/pkg/tool/lib").exists()

        # Left alone: other vendors, unrelated workflows, files not in manifest
        assert (configs_dir / "other.json").exists()
        assert (manifests_dir / "other.files").exists()
        assert (manifests_dir / "other.version").exists()
        assert other_workflow.exists()
        assert other_pkg.exists()
        assert untracked.exists()
        assert "(8 files deleted)" in capsys.readouterr().out
