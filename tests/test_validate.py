"""Tests for the validate script."""

import base64
import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import subprocess as _real_subprocess

import pytest

# ── Import validate script as module ─────────────────────────────────────

ROOT = Path(__file__).parent.parent


def _import_validate():
    filepath = str(ROOT / "validate")
    loader = importlib.machinery.SourceFileLoader("vendored_validate", filepath)
    spec = importlib.util.spec_from_loader("vendored_validate", loader, origin=filepath)
    module = importlib.util.module_from_spec(spec)
    sys.modules["vendored_validate"] = module
    spec.loader.exec_module(module)
    return module


val = _import_validate()


# ── Tests: get_auth_token ────────────────────────────────────────────────

class TestGetAuthToken:
    def test_prefers_gh_token(self, monkeypatch):
        monkeypatch.setenv("GH_TOKEN", "gh-tok")
        monkeypatch.setenv("GITHUB_TOKEN", "github-tok")
        assert val.get_auth_token() == "gh-tok"

    def test_falls_back_to_github_token(self, monkeypatch):
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "github-tok")
        assert val.get_auth_token() == "github-tok"

    def test_returns_none_when_no_token(self, monkeypatch):
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert val.get_auth_token() is None


# ── Tests: ValidationResult ──────────────────────────────────────────────

class TestValidationResult:
    def test_empty_result(self):
        r = val.ValidationResult()
        assert r.pass_count == 0
        assert r.fail_count == 0
        assert r.total == 0
        assert r.all_passed is True

    def test_all_pass(self):
        r = val.ValidationResult()
        r.passed("Check A")
        r.passed("Check B", "detail")
        assert r.pass_count == 2
        assert r.fail_count == 0
        assert r.all_passed is True
        assert "PASS (2/2" in r.summary()

    def test_mixed_results(self):
        r = val.ValidationResult()
        r.passed("Check A")
        r.failed("Check B", "reason")
        assert r.pass_count == 1
        assert r.fail_count == 1
        assert r.all_passed is False
        assert "FAIL (1/2" in r.summary()

    def test_all_fail(self):
        r = val.ValidationResult()
        r.failed("Check A")
        r.failed("Check B")
        assert r.pass_count == 0
        assert r.fail_count == 2
        assert r.all_passed is False


# ── Tests: check_repo_exists (Check 1) ──────────────────────────────────

class TestCheckRepoExists:
    @patch("vendored_validate.subprocess.run")
    def test_pass(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="owner/repo\n")
        r = val.ValidationResult()
        assert val.check_repo_exists("owner/repo", "tok", r) is True
        assert r.pass_count == 1

    @patch("vendored_validate.subprocess.run")
    def test_fail(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Not found")
        r = val.ValidationResult()
        assert val.check_repo_exists("owner/repo", "tok", r) is False
        assert r.fail_count == 1


# ── Tests: check_install_sh_exists (Check 2) ────────────────────────────

class TestCheckInstallShExists:
    @patch("vendored_validate.subprocess.run")
    def test_pass(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="install.sh\n")
        r = val.ValidationResult()
        assert val.check_install_sh_exists("owner/repo", "tok", r) is True
        assert r.pass_count == 1

    @patch("vendored_validate.subprocess.run")
    def test_fail_not_found(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        r = val.ValidationResult()
        assert val.check_install_sh_exists("owner/repo", "tok", r) is False
        assert r.fail_count == 1

    @patch("vendored_validate.subprocess.run")
    def test_fail_empty_stdout(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        r = val.ValidationResult()
        assert val.check_install_sh_exists("owner/repo", "tok", r) is False
        assert r.fail_count == 1


# ── Tests: check_version_resolvable (Check 3) ───────────────────────────

class TestCheckVersionResolvable:
    def test_explicit_version(self):
        """Explicit version (not 'latest') passes immediately."""
        r = val.ValidationResult()
        v = val.check_version_resolvable("owner/repo", "tok", "1.2.3", r)
        assert v == "1.2.3"
        assert r.pass_count == 1

    @patch("vendored_validate.subprocess.run")
    def test_resolves_from_releases(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="v2.0.0\n")
        r = val.ValidationResult()
        v = val.check_version_resolvable("owner/repo", "tok", "latest", r)
        assert v == "2.0.0"
        assert r.pass_count == 1

    @patch("vendored_validate.subprocess.run")
    def test_resolves_from_version_file(self, mock_run):
        """Falls back to VERSION file when no releases."""
        encoded = base64.b64encode(b"3.0.0").decode()

        def side_effect(cmd, **kwargs):
            if "releases/latest" in cmd[2]:
                return MagicMock(returncode=1, stdout="")
            if "contents/VERSION" in cmd[2]:
                return MagicMock(returncode=0, stdout=encoded + "\n")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = side_effect
        r = val.ValidationResult()
        v = val.check_version_resolvable("owner/repo", "tok", "latest", r)
        assert v == "3.0.0"
        assert r.pass_count == 1

    @patch("vendored_validate.subprocess.run")
    def test_fail_no_version(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        r = val.ValidationResult()
        v = val.check_version_resolvable("owner/repo", "tok", "latest", r)
        assert v is None
        assert r.fail_count == 1

    def test_none_version_treated_as_latest(self):
        """None version should try to resolve (same as 'latest')."""
        r = val.ValidationResult()
        with patch("vendored_validate.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="v1.0.0\n")
            v = val.check_version_resolvable("owner/repo", "tok", None, r)
            assert v == "1.0.0"


# ── Tests: download_install_sh ───────────────────────────────────────────

class TestDownloadInstallSh:
    @patch("vendored_validate.subprocess.run")
    def test_download_with_v_prefix(self, mock_run):
        content = base64.b64encode(b"#!/bin/bash\necho hi\n").decode()
        mock_run.return_value = MagicMock(returncode=0, stdout=content + "\n")
        result = val.download_install_sh("owner/repo", "1.0.0", "tok")
        assert result == "#!/bin/bash\necho hi\n"
        # Should use v prefix
        assert "ref=v1.0.0" in mock_run.call_args_list[0][0][0][2]

    @patch("vendored_validate.subprocess.run")
    def test_fallback_without_v_prefix(self, mock_run):
        content = base64.b64encode(b"#!/bin/bash\necho hi\n").decode()
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=0, stdout=content + "\n"),
        ]
        result = val.download_install_sh("owner/repo", "1.0.0", "tok")
        assert result == "#!/bin/bash\necho hi\n"

    @patch("vendored_validate.subprocess.run")
    def test_returns_none_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = val.download_install_sh("owner/repo", "1.0.0", "tok")
        assert result is None


# ── Tests: check_valid_shebang (Check 4) ────────────────────────────────

class TestCheckValidShebang:
    def test_pass_bin_bash(self):
        r = val.ValidationResult()
        assert val.check_valid_shebang("#!/bin/bash\necho hi\n", r) is True
        assert r.pass_count == 1

    def test_pass_env_bash(self):
        r = val.ValidationResult()
        assert val.check_valid_shebang("#!/usr/bin/env bash\necho hi\n", r) is True
        assert r.pass_count == 1

    def test_fail_wrong_shebang(self):
        r = val.ValidationResult()
        assert val.check_valid_shebang("#!/bin/sh\necho hi\n", r) is False
        assert r.fail_count == 1

    def test_fail_no_content(self):
        r = val.ValidationResult()
        assert val.check_valid_shebang(None, r) is False
        assert r.fail_count == 1


# ── Tests: check_syntax_valid (Check 5) ─────────────────────────────────

class TestCheckSyntaxValid:
    @patch("vendored_validate.subprocess.run")
    def test_pass(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        r = val.ValidationResult()
        assert val.check_syntax_valid("#!/bin/bash\necho hi\n", r) is True
        assert r.pass_count == 1

    @patch("vendored_validate.subprocess.run")
    def test_fail_syntax_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="syntax error")
        r = val.ValidationResult()
        assert val.check_syntax_valid("#!/bin/bash\nif\n", r) is False
        assert r.fail_count == 1

    def test_fail_no_content(self):
        r = val.ValidationResult()
        assert val.check_syntax_valid(None, r) is False
        assert r.fail_count == 1


# ── Tests: run_dryrun_install (Checks 6-8) ──────────────────────────────

class TestRunDryrunInstall:
    def test_fail_no_content(self):
        """All three checks fail when script_content is None."""
        r = val.ValidationResult()
        val.run_dryrun_install("owner/repo", "1.0.0", None, "tok", r)
        assert r.fail_count == 3
        assert r.pass_count == 0

    def test_all_pass(self):
        """Full passing dry-run: install succeeds, manifest written, files exist."""
        script = (
            "#!/bin/bash\n"
            "mkdir -p \"$VENDOR_INSTALL_DIR\"\n"
            "touch \"$VENDOR_INSTALL_DIR/file.txt\"\n"
            "echo \"$VENDOR_INSTALL_DIR/file.txt\" > \"$VENDOR_MANIFEST\"\n"
        )
        r = val.ValidationResult()
        val.run_dryrun_install("owner/repo", "1.0.0", script, "tok", r)
        assert r.pass_count == 3
        assert r.fail_count == 0

    @patch("vendored_validate.subprocess.run")
    def test_install_fails(self, mock_run):
        """Dry-run fails with non-zero exit code."""
        mock_run.return_value = MagicMock(returncode=1, stderr="error", stdout="")
        r = val.ValidationResult()
        val.run_dryrun_install("owner/repo", "1.0.0", "#!/bin/bash\nexit 1\n",
                               "tok", r)
        assert r.fail_count >= 1
        # Check 6 failed
        assert any("Dry-run install" in msg for _, msg in r.checks
                    if _ == "FAIL")

    @patch("vendored_validate.subprocess.run")
    def test_no_manifest_written(self, mock_run):
        """Install succeeds but no manifest is written."""
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        r = val.ValidationResult()
        val.run_dryrun_install("owner/repo", "1.0.0", "#!/bin/bash\necho ok\n",
                               "tok", r)
        # Check 6 passes, check 7 and 8 fail
        assert any("Dry-run install" in msg for _, msg in r.checks
                    if _ == "PASS")
        assert any("Manifest written" in msg for _, msg in r.checks
                    if _ == "FAIL")

    def test_manifest_files_missing(self):
        """Manifest lists files that don't exist on disk."""
        script = (
            "#!/bin/bash\n"
            "echo \"nonexistent/file.txt\" > \"$VENDOR_MANIFEST\"\n"
        )
        r = val.ValidationResult()
        val.run_dryrun_install("owner/repo", "1.0.0", script, "tok", r)
        # Check 6 passes, 7 passes (manifest written), 8 fails (files missing)
        assert any("Manifest files exist" in msg for _, msg in r.checks
                    if _ == "FAIL")


# ── Tests: validate (integration) ────────────────────────────────────────

class TestValidate:
    @patch("vendored_validate.get_auth_token", return_value="tok")
    @patch("vendored_validate.check_repo_exists", return_value=False)
    def test_fail_fast_repo_not_found(self, mock_check, mock_auth):
        """Stops after check 1 failure."""
        exit_code = val.validate("owner/repo")
        assert exit_code == 1
        mock_check.assert_called_once()

    @patch("vendored_validate.get_auth_token", return_value="tok")
    @patch("vendored_validate.check_repo_exists", return_value=True)
    @patch("vendored_validate.check_install_sh_exists", return_value=False)
    def test_fail_fast_no_install_sh(self, mock_install, mock_repo, mock_auth):
        """Stops after check 2 failure."""
        exit_code = val.validate("owner/repo")
        assert exit_code == 1
        mock_install.assert_called_once()

    @patch("vendored_validate.get_auth_token", return_value="tok")
    @patch("vendored_validate.check_repo_exists", return_value=True)
    @patch("vendored_validate.check_install_sh_exists", return_value=True)
    @patch("vendored_validate.check_version_resolvable", return_value=None)
    def test_fail_fast_no_version(self, mock_ver, mock_install, mock_repo,
                                  mock_auth):
        """Stops after check 3 failure."""
        exit_code = val.validate("owner/repo")
        assert exit_code == 1

    @patch("vendored_validate.get_auth_token", return_value="tok")
    @patch("vendored_validate.check_repo_exists", return_value=True)
    @patch("vendored_validate.check_install_sh_exists", return_value=True)
    @patch("vendored_validate.check_version_resolvable", return_value="1.0.0")
    @patch("vendored_validate.download_install_sh",
           return_value="#!/bin/bash\necho hi\n")
    @patch("vendored_validate.check_valid_shebang", return_value=True)
    @patch("vendored_validate.check_syntax_valid", return_value=True)
    @patch("vendored_validate.run_dryrun_install")
    def test_all_checks_run(self, mock_dryrun, mock_syntax, mock_shebang,
                            mock_download, mock_ver, mock_install, mock_repo,
                            mock_auth):
        """All checks run when fail-fast checks pass."""
        exit_code = val.validate("owner/repo")
        assert exit_code == 0
        mock_shebang.assert_called_once()
        mock_syntax.assert_called_once()
        mock_dryrun.assert_called_once()

    @patch("vendored_validate.get_auth_token", return_value="tok")
    @patch("vendored_validate.check_repo_exists", return_value=True)
    @patch("vendored_validate.check_install_sh_exists", return_value=True)
    @patch("vendored_validate.check_version_resolvable", return_value="1.0.0")
    @patch("vendored_validate.download_install_sh", return_value=None)
    def test_collect_and_report_on_download_failure(self, mock_download,
                                                     mock_ver, mock_install,
                                                     mock_repo, mock_auth):
        """Checks 4-8 all run even when download fails (collect-and-report)."""
        exit_code = val.validate("owner/repo")
        assert exit_code == 1

    @patch("vendored_validate.get_auth_token", return_value="tok")
    @patch("vendored_validate.check_repo_exists", return_value=True)
    @patch("vendored_validate.check_install_sh_exists", return_value=True)
    @patch("vendored_validate.check_version_resolvable", return_value="2.0.0")
    @patch("vendored_validate.download_install_sh",
           return_value="#!/bin/bash\necho hi\n")
    @patch("vendored_validate.check_valid_shebang", return_value=True)
    @patch("vendored_validate.check_syntax_valid", return_value=False)
    @patch("vendored_validate.run_dryrun_install")
    def test_returns_1_on_partial_failure(self, mock_dryrun, mock_syntax,
                                          mock_shebang, mock_download,
                                          mock_ver, mock_install, mock_repo,
                                          mock_auth):
        """Returns exit code 1 when some collect-and-report checks fail."""
        # Simulate: syntax check failed but dryrun modifies result
        def dryrun_side_effect(repo, version, script, token, result):
            result.failed("Dry-run install", "exit code 1")
            result.failed("Manifest written", "no manifest")
            result.failed("Manifest files exist", "skipped")
        mock_dryrun.side_effect = dryrun_side_effect
        exit_code = val.validate("owner/repo")
        assert exit_code == 1


# ── Tests: main / CLI ───────────────────────────────────────────────────

class TestMain:
    @patch("vendored_validate.validate", return_value=0)
    def test_main_calls_validate(self, mock_validate):
        with patch("sys.argv", ["validate", "owner/repo"]):
            with pytest.raises(SystemExit) as exc_info:
                val.main()
            assert exc_info.value.code == 0
        mock_validate.assert_called_once_with("owner/repo", "latest")

    @patch("vendored_validate.validate", return_value=0)
    def test_main_with_version(self, mock_validate):
        with patch("sys.argv", ["validate", "owner/repo", "--version", "1.0.0"]):
            with pytest.raises(SystemExit) as exc_info:
                val.main()
            assert exc_info.value.code == 0
        mock_validate.assert_called_once_with("owner/repo", "1.0.0")

    @patch("vendored_validate.validate", return_value=1)
    def test_main_propagates_exit_code(self, mock_validate):
        with patch("sys.argv", ["validate", "owner/repo"]):
            with pytest.raises(SystemExit) as exc_info:
                val.main()
            assert exc_info.value.code == 1
