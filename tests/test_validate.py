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


# ── Tests: decode failures, empty/large manifests ───────────────────────

def _b64(text):
    return base64.b64encode(text.encode() if isinstance(text, str) else text).decode()


class TestDecodeFailures:
    @patch("vendored_validate.subprocess.run")
    def test_undecodable_version_file_fails(self, mock_run):
        """Releases missing and VERSION content is not valid base64 -> fail."""
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=0, stdout="abc\n"),  # bad padding
        ]
        r = val.ValidationResult()
        assert val.check_version_resolvable("owner/repo", "tok", "latest", r) is None
        assert r.checks == [("FAIL", "  [FAIL] Version resolvable -- "
                                     "no releases or VERSION file found")]

    @patch("vendored_validate.subprocess.run")
    def test_non_utf8_version_file_fails(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=0, stdout=_b64(b"\xff\xfe")),
        ]
        r = val.ValidationResult()
        assert val.check_version_resolvable("owner/repo", "tok", "latest", r) is None
        assert r.fail_count == 1

    @patch("vendored_validate.subprocess.run")
    def test_empty_version_file_fails(self, mock_run):
        """A VERSION file holding only whitespace does not resolve a version."""
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=0, stdout=_b64("\n")),
        ]
        r = val.ValidationResult()
        assert val.check_version_resolvable("owner/repo", "tok", "latest", r) is None
        assert r.pass_count == 0
        assert r.fail_count == 1

    @patch("vendored_validate.subprocess.run")
    def test_undecodable_install_sh_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="abc\n")
        assert val.download_install_sh("owner/repo", "1.0.0", "tok") is None
        assert mock_run.call_count == 1  # first ref returned content; no retry

    @patch("vendored_validate.subprocess.run")
    def test_both_refs_tried_before_giving_up(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert val.download_install_sh("owner/repo", "1.0.0", "tok") is None
        refs = [c[0][0][2] for c in mock_run.call_args_list]
        assert refs == ["repos/owner/repo/contents/install.sh?ref=v1.0.0",
                        "repos/owner/repo/contents/install.sh?ref=1.0.0"]


class TestDryrunManifestEdgeCases:
    def test_empty_manifest(self):
        script = "#!/bin/bash\nprintf '\\n  \\n' > \"$VENDOR_MANIFEST\"\n"
        r = val.ValidationResult()
        val.run_dryrun_install("owner/repo", "1.0.0", script, "tok", r)
        assert [m for _, m in r.checks] == [
            "  [PASS] Dry-run install (exit code 0)",
            "  [FAIL] Manifest written -- manifest file is empty",
            "  [FAIL] Manifest files exist -- skipped (empty manifest)",
        ]

    def test_more_than_five_missing_truncated(self):
        script = "#!/bin/bash\nfor i in 1 2 3 4 5 6 7; do echo \"m$i\"; done " \
                 "> \"$VENDOR_MANIFEST\"\n"
        r = val.ValidationResult()
        val.run_dryrun_install("owner/repo", "1.0.0", script, "tok", r)
        status, msg = r.checks[-1]
        assert status == "FAIL"
        assert msg == ("  [FAIL] Manifest files exist -- 7 missing: "
                       "m1, m2, m3, m4, m5 (and 2 more)")

    @patch("vendored_validate.subprocess.run")
    def test_failure_detail_includes_stderr_and_env(self, mock_run):
        mock_run.return_value = MagicMock(returncode=3, stderr="boom\n", stdout="")
        r = val.ValidationResult()
        val.run_dryrun_install("owner/tool", "1.2.0", "#!/bin/bash\n", "tok", r)
        assert r.checks[0] == ("FAIL", "  [FAIL] Dry-run install -- exit code 3: boom")
        env = mock_run.call_args[1]["env"]
        assert env["VENDOR_REPO"] == "owner/tool"
        assert env["VENDOR_REF"] == "v1.2.0"
        assert env["VENDOR_INSTALL_DIR"] == os.path.join(".vendored", "pkg", "tool")
        assert env["GH_TOKEN"] == "tok"


# ── Tests: end-to-end validate with subprocess.run faked at the boundary ─

GOOD_SCRIPT = (
    "#!/bin/bash\n"
    "mkdir -p \"$VENDOR_INSTALL_DIR\"\n"
    "touch \"$VENDOR_INSTALL_DIR/tool\"\n"
    "echo \"$VENDOR_INSTALL_DIR/tool\" > \"$VENDOR_MANIFEST\"\n"
)


_REAL_RUN = _real_subprocess.run  # captured before any test patches it


def _fake_run(script=GOOD_SCRIPT, repo_ok=True, tag="v1.2.0", calls=None):
    """Answer gh api calls from canned data; run bash for real (local only)."""
    def run(cmd, **kwargs):
        if calls is not None:
            calls.append((cmd, kwargs))
        if cmd[0] == "bash":
            return _REAL_RUN(cmd, **kwargs)
        assert cmd[:2] == ["gh", "api"]
        path = cmd[2]
        if path == "repos/owner/tool":
            return MagicMock(returncode=0 if repo_ok else 1, stdout="owner/tool\n")
        if path == "repos/owner/tool/contents/install.sh":
            return MagicMock(returncode=0, stdout="install.sh\n")
        if path == "repos/owner/tool/releases/latest":
            return MagicMock(returncode=0 if tag else 1, stdout=(tag or "") + "\n")
        if path.startswith("repos/owner/tool/contents/install.sh?ref="):
            return MagicMock(returncode=0, stdout=_b64(script) + "\n")
        return MagicMock(returncode=1, stdout="")
    return run


class TestValidateEndToEnd:
    def test_compliant_repo_passes_all_eight(self, monkeypatch, capsys):
        monkeypatch.setenv("GH_TOKEN", "gh-tok")
        with patch("vendored_validate.subprocess.run", side_effect=_fake_run()):
            assert val.validate("owner/tool") == 0
        out = capsys.readouterr().out
        assert "Validating vendor contract: owner/tool" in out
        assert "  [PASS] Version resolvable (1.2.0)" in out
        assert "Result: PASS (8/8 checks passed)" in out

    def test_broken_script_collects_failures(self, monkeypatch, capsys):
        monkeypatch.setenv("GH_TOKEN", "gh-tok")
        script = "#!/bin/sh\nif then\n"
        with patch("vendored_validate.subprocess.run",
                   side_effect=_fake_run(script=script)):
            assert val.validate("owner/tool", "2.0.0") == 1
        out = capsys.readouterr().out
        assert "[FAIL] Valid shebang -- got: #!/bin/sh" in out
        assert "[FAIL] Syntax valid" in out
        assert "[FAIL] Dry-run install" in out
        assert "[FAIL] Manifest written" in out
        assert "Result: FAIL (5/8 checks failed)" in out

    def test_inaccessible_repo_stops_early(self, monkeypatch, capsys):
        calls = []
        with patch("vendored_validate.subprocess.run",
                   side_effect=_fake_run(repo_ok=False, calls=calls)):
            assert val.validate("owner/tool") == 1
        assert len(calls) == 1
        out = capsys.readouterr().out
        assert "[FAIL] Repo exists -- cannot access owner/tool" in out
        assert "Result: FAIL (1/1 checks failed)" in out

    def test_unresolvable_version_stops_early(self, capsys):
        calls = []
        with patch("vendored_validate.subprocess.run",
                   side_effect=_fake_run(tag=None, calls=calls)):
            assert val.validate("owner/tool") == 1
        assert not any(c[0][0] == "bash" for c in calls)
        assert "Result: FAIL (1/3 checks failed)" in capsys.readouterr().out


class TestTokenSelection:
    def _gh_envs(self, calls):
        return [kw["env"] for cmd, kw in calls if cmd[0] == "gh"]

    def test_gh_token_wins_over_github_token(self, monkeypatch):
        monkeypatch.setenv("GH_TOKEN", "gh-tok")
        monkeypatch.setenv("GITHUB_TOKEN", "github-tok")
        calls = []
        with patch("vendored_validate.subprocess.run",
                   side_effect=_fake_run(calls=calls)):
            val.validate("owner/tool")
        envs = self._gh_envs(calls)
        assert envs and all(e["GH_TOKEN"] == "gh-tok" for e in envs)

    def test_github_token_exported_as_gh_token(self, monkeypatch):
        """gh only reads GH_TOKEN, so GITHUB_TOKEN is passed through under that name."""
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "github-tok")
        calls = []
        with patch("vendored_validate.subprocess.run",
                   side_effect=_fake_run(calls=calls)):
            val.validate("owner/tool")
        envs = self._gh_envs(calls)
        assert envs and all(e["GH_TOKEN"] == "github-tok" for e in envs)
        dryrun_env = [kw["env"] for cmd, kw in calls
                      if cmd[0] == "bash" and cmd[1] != "-n"][0]
        assert dryrun_env["GH_TOKEN"] == "github-tok"

    def test_no_token_leaves_env_unset(self, monkeypatch):
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        calls = []
        with patch("vendored_validate.subprocess.run",
                   side_effect=_fake_run(calls=calls)):
            val.validate("owner/tool")
        assert all("GH_TOKEN" not in e for e in self._gh_envs(calls))
