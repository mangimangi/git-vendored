"""Tests for the validate script."""

import base64
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import subprocess as _real_subprocess

import pytest

# ── Import validate script as module ─────────────────────────────────────

ROOT = Path(__file__).parent.parent


def _import_validate():
    filepath = str(ROOT / "validate")
    loader = importlib.machinery.SourceFileLoader("vendored_validate", filepath)
    spec = importlib.util.spec_from_file_location("vendored_validate", filepath, loader=loader)
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


SHA = "a" * 40


def _resolved(version="1.0.0", tag=None, commit=SHA):
    return val.INSTALL.Resolved(version, tag or f"v{version}", commit)


# ── Tests: check_repo_exists (Check 1) ──────────────────────────────────

class TestCheckRepoExists:
    def test_pass(self, vendor_repo):
        repo = vendor_repo()
        commit = repo.commit("one")
        repo.tag("v1.0.0")
        r = val.ValidationResult()
        assert val.check_repo_exists(repo.url, None, r) == {"v1.0.0": commit}
        assert r.checks == [("PASS", "  [PASS] Repo exists")]

    def test_fail(self, vendor_repo, tmp_path):
        url = (tmp_path / "missing").as_uri()
        r = val.ValidationResult()
        assert val.check_repo_exists(url, "tok", r) is None
        assert r.checks == [("FAIL", f"  [FAIL] Repo exists -- cannot access {url}")]


# ── Tests: check_install_sh_exists (Check 2) ────────────────────────────

class TestCheckInstallShExists:
    def test_pass(self, tmp_path):
        (tmp_path / "install.sh").write_text("#!/bin/bash\n")
        r = val.ValidationResult()
        assert val.check_install_sh_exists("owner/repo", str(tmp_path), r) is True
        assert r.checks == [("PASS", "  [PASS] install.sh exists")]

    def test_fail_not_found(self, tmp_path):
        r = val.ValidationResult()
        assert val.check_install_sh_exists("owner/repo", str(tmp_path), r) is False
        assert r.checks == [("FAIL", "  [FAIL] install.sh exists -- "
                                     "no install.sh at root of owner/repo")]

    def test_fail_no_checkout(self):
        r = val.ValidationResult()
        assert val.check_install_sh_exists("owner/repo", None, r) is False
        assert r.fail_count == 1


# ── Tests: check_version_resolvable (Check 3) ───────────────────────────

class TestCheckVersionResolvable:
    def test_explicit_version(self):
        r = val.ValidationResult()
        resolved, reason = val.resolve({"v1.2.3": SHA}, "1.2.3")
        assert val.check_version_resolvable(resolved, reason, r) == "1.2.3"
        assert r.checks == [("PASS", "  [PASS] Version resolvable (1.2.3)")]

    def test_latest_is_highest_version_tag(self):
        resolved, _ = val.resolve({"v0.0.9": SHA, "v0.0.10": "b" * 40,
                                   "latest": SHA}, "latest")
        assert resolved == _resolved("0.0.10", commit="b" * 40)

    def test_none_version_treated_as_latest(self):
        resolved, _ = val.resolve({"v1.0.0": SHA}, None)
        assert resolved.version == "1.0.0"

    def test_fail_no_version_tags(self):
        r = val.ValidationResult()
        resolved, reason = val.resolve({"latest": SHA}, "latest")
        assert val.check_version_resolvable(resolved, reason, r) is None
        assert r.checks == [("FAIL", "  [FAIL] Version resolvable -- "
                                     "no version tags found")]

    def test_fail_explicit_without_tag(self):
        r = val.ValidationResult()
        resolved, reason = val.resolve({"v1.0.0": SHA}, "2.0.0")
        val.check_version_resolvable(resolved, reason, r)
        assert r.checks == [("FAIL", "  [FAIL] Version resolvable -- "
                                     "no tag for 2.0.0")]


# ── Tests: read_install_sh ───────────────────────────────────────────────

class TestReadInstallSh:
    def test_reads_checkout(self, tmp_path):
        (tmp_path / "install.sh").write_text("#!/bin/bash\necho hi\n")
        assert val.read_install_sh(str(tmp_path)) == "#!/bin/bash\necho hi\n"

    def test_missing_or_undecodable_is_none(self, tmp_path):
        assert val.read_install_sh(str(tmp_path)) is None
        (tmp_path / "install.sh").write_bytes(b"\xff\xfe\xfa")
        assert val.read_install_sh(str(tmp_path)) is None


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


# ── Tests: empty/large manifests ─────────────────────────────────────────

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


# ── Tests: end-to-end validate against local git vendors ────────────────

GOOD_SCRIPT = (
    "#!/bin/bash\n"
    "mkdir -p \"$VENDOR_INSTALL_DIR\"\n"
    "touch \"$VENDOR_INSTALL_DIR/tool\"\n"
    "echo \"$VENDOR_INSTALL_DIR/tool\" > \"$VENDOR_MANIFEST\"\n"
)

HELPER_SCRIPT = (
    "#!/bin/bash\n"
    "set -euo pipefail\n"
    "source \"$VENDOR_LIB\"\n"
    "fetch_file tool \"$VENDOR_INSTALL_DIR/tool\" +x\n"
    "fetch_dir templates \"$VENDOR_INSTALL_DIR/templates\"\n"
)


def _vendor(vendor_repo, script=GOOD_SCRIPT, tag="v1.2.0", name="tool"):
    repo = vendor_repo(name)
    repo.write("install.sh", script)
    repo.write("tool", "#!/bin/bash\necho tool\n")
    repo.write("templates/a.txt", "a\n")
    repo.commit("v1")
    if tag:
        repo.tag(tag)
    return repo


def _no_tmp_left(before):
    after = {p for p in os.listdir(tempfile.gettempdir())
             if p.startswith(("gv-vendor-", "gv-validate-"))}
    return after <= before


def _tmp_entries():
    return {p for p in os.listdir(tempfile.gettempdir())
            if p.startswith(("gv-vendor-", "gv-validate-"))}


class TestValidateEndToEnd:
    def test_compliant_repo_passes_all_eight(self, vendor_repo, capsys):
        repo = _vendor(vendor_repo)
        before = _tmp_entries()
        assert val.validate(repo.url) == 0
        out = capsys.readouterr().out
        assert f"Validating vendor contract: {repo.url}" in out
        assert [l for l in out.splitlines() if l.startswith("  [")] == [
            "  [PASS] Repo exists",
            "  [PASS] install.sh exists",
            "  [PASS] Version resolvable (1.2.0)",
            "  [PASS] Valid shebang (#!/bin/bash)",
            "  [PASS] Syntax valid (bash -n passed)",
            "  [PASS] Dry-run install (exit code 0)",
            "  [PASS] Manifest written (1 files)",
            "  [PASS] Manifest files exist (all 1 files found on disk)",
        ]
        assert "Result: PASS (8/8 checks passed)" in out
        assert _no_tmp_left(before)

    def test_helper_vendor_validates_from_checkout(self, vendor_repo, capsys):
        repo = _vendor(vendor_repo, script=HELPER_SCRIPT)
        assert val.validate(repo.url) == 0, capsys.readouterr().out
        assert "Manifest written (2 files)" in capsys.readouterr().out

    def test_url_with_dot_git_names_sandbox_vendor(self, vendor_repo, capsys):
        script = ("#!/bin/bash\n"
                  "[ \"$VENDOR_INSTALL_DIR\" = .vendored/pkg/tool ] || exit 7\n"
                  + GOOD_SCRIPT.split("\n", 1)[1])
        repo = _vendor(vendor_repo, script=script, name="tool.git")
        assert val.validate(repo.url) == 0, capsys.readouterr().out

    def test_broken_script_collects_failures(self, vendor_repo, capsys):
        repo = _vendor(vendor_repo, script="#!/bin/sh\nif then\n", tag="2.0.0")
        assert val.validate(repo.url, "2.0.0") == 1
        out = capsys.readouterr().out
        assert "[FAIL] Valid shebang -- got: #!/bin/sh" in out
        assert "[FAIL] Syntax valid" in out
        assert "[FAIL] Dry-run install" in out
        assert "[FAIL] Manifest written" in out
        assert "Result: FAIL (5/8 checks failed)" in out

    def test_no_manifest_written(self, vendor_repo, capsys):
        repo = _vendor(vendor_repo, script="#!/bin/bash\necho ok\n")
        assert val.validate(repo.url) == 1
        out = capsys.readouterr().out
        assert ("[FAIL] Manifest written -- install.sh did not write to "
                "$VENDOR_MANIFEST") in out

    def test_manifest_lists_missing_file(self, vendor_repo, capsys):
        repo = _vendor(vendor_repo,
                       script="#!/bin/bash\necho gone.txt > \"$VENDOR_MANIFEST\"\n")
        assert val.validate(repo.url) == 1
        assert "[FAIL] Manifest files exist -- 1 missing: gone.txt" in \
            capsys.readouterr().out

    def test_inaccessible_repo_stops_early(self, vendor_repo, tmp_path, capsys):
        url = (tmp_path / "missing").as_uri()
        assert val.validate(url) == 1
        out = capsys.readouterr().out
        assert f"[FAIL] Repo exists -- cannot access {url}" in out
        assert "Result: FAIL (1/1 checks failed)" in out

    def test_no_version_tags_stops_early(self, vendor_repo, capsys):
        repo = _vendor(vendor_repo, tag="latest")
        assert val.validate(repo.url) == 1
        out = capsys.readouterr().out
        assert "[FAIL] install.sh exists -- skipped (no version)" in out
        assert "[FAIL] Version resolvable -- no version tags found" in out
        assert "Result: FAIL (2/3 checks failed)" in out

    def test_explicit_version_without_tag(self, vendor_repo, capsys):
        repo = _vendor(vendor_repo)
        assert val.validate(repo.url, "9.9.9") == 1
        assert "[FAIL] Version resolvable -- no tag for 9.9.9" in \
            capsys.readouterr().out

    def test_no_install_sh_at_tag(self, vendor_repo, capsys):
        repo = vendor_repo()
        repo.write("README", "x\n")
        repo.commit("one")
        repo.tag("v1.0.0")
        repo.write("install.sh", GOOD_SCRIPT)
        repo.commit("installer after the tag")
        before = _tmp_entries()
        assert val.validate(repo.url) == 1
        out = capsys.readouterr().out
        assert f"[FAIL] install.sh exists -- no install.sh at root of {repo.url}" in out
        assert "Result: FAIL (1/2 checks failed)" in out
        assert _no_tmp_left(before)

    def test_fetch_failure_fails_check_2(self, vendor_repo, capsys):
        repo = _vendor(vendor_repo)
        with patch.object(val, "resolve",
                          return_value=(_resolved("1.2.0", tag="v-gone"), None)):
            assert val.validate(repo.url) == 1
        assert "[FAIL] install.sh exists" in capsys.readouterr().out

    def test_same_resolution_as_the_installer(self, vendor_repo):
        repo = _vendor(vendor_repo)
        repo.commit("two")
        repo.tag("v1.10.0", annotated=True)
        tags = val.check_repo_exists(repo.url, None, val.ValidationResult())
        resolved, _ = val.resolve(tags, "latest")
        installed = val.INSTALL.resolve_version("tool", repo.url, "latest", "")
        assert resolved == installed
        assert resolved.commit == repo.rev("v1.10.0^{commit}")


class TestValidateNoGh:
    def test_program_passes_with_gh_absent(self, vendor_repo, tmp_path):
        repo = _vendor(vendor_repo, script=HELPER_SCRIPT)
        bindir = tmp_path / "bin-no-gh"
        bindir.mkdir()
        for d in os.environ.get("PATH", "").split(os.pathsep):
            if not os.path.isdir(d):
                continue
            for entry in os.listdir(d):
                src = os.path.join(d, entry)
                dst = bindir / entry
                if entry != "gh" and not dst.exists() and os.path.isfile(src) \
                        and os.access(src, os.X_OK):
                    dst.symlink_to(src)
        env = dict(os.environ, PATH=str(bindir))
        proc = _real_subprocess.run(
            [sys.executable, str(ROOT / "validate"), repo.url],
            cwd=str(tmp_path), capture_output=True, text=True, env=env,
            timeout=120)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "Result: PASS (8/8 checks passed)" in proc.stdout


class TestTokenSelection:
    def _envs(self, monkeypatch):
        calls = []
        real = val.INSTALL.subprocess.run

        def spy(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return real(cmd, **kwargs)
        monkeypatch.setattr(val.INSTALL.subprocess, "run", spy)
        return calls

    @pytest.fixture(autouse=True)
    def _no_ambient_git_config(self, monkeypatch):
        for key in list(os.environ):
            if key.startswith("GIT_CONFIG_") and key not in (
                    "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"):
                monkeypatch.delenv(key)

    def test_gh_token_wins_and_goes_to_git_as_header(self, vendor_repo,
                                                     monkeypatch, capsys):
        repo = _vendor(vendor_repo)
        monkeypatch.setenv("GH_TOKEN", "gh-tok")
        monkeypatch.setenv("GITHUB_TOKEN", "github-tok")
        calls = self._envs(monkeypatch)
        assert val.validate(repo.url) == 0
        git_calls = [(c, k) for c, k in calls if c[0] == "git" and "-C" not in c]
        assert git_calls
        for cmd, kw in git_calls:
            assert not any("gh-tok" in part for part in cmd)
            value = kw["env"]["GIT_CONFIG_VALUE_0"]
            assert base64.b64decode(value.split()[-1]).decode() == \
                "x-access-token:gh-tok"
        assert "gh-tok" not in capsys.readouterr().out

    def test_github_token_exported_as_gh_token_to_dryrun(self, vendor_repo,
                                                         monkeypatch):
        repo = _vendor(vendor_repo,
                       script="#!/bin/bash\necho \"$GH_TOKEN\" > \"$VENDOR_MANIFEST\"\n")
        monkeypatch.setenv("GITHUB_TOKEN", "github-tok")
        with patch.object(val.subprocess, "run",
                          wraps=_real_subprocess.run) as mock_run:
            val.validate(repo.url)
        dryrun_env = [c[1]["env"] for c in mock_run.call_args_list
                      if c[0][0][0] == "bash" and c[0][0][1] != "-n"][0]
        assert dryrun_env["GH_TOKEN"] == "github-tok"

    def test_no_token_reads_anonymously(self, vendor_repo, monkeypatch):
        repo = _vendor(vendor_repo)
        calls = self._envs(monkeypatch)
        assert val.validate(repo.url) == 0
        assert all("GIT_CONFIG_COUNT" not in k["env"]
                   for c, k in calls if "env" in k and k["env"])
