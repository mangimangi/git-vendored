"""Tests for pearls vendor hook scripts (post-install, session-start, session-resume).

These test the actual shell scripts at .vendored/pkg/pearls/hooks/, not the
framework hook infrastructure (tested in test_hooks.py).
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
HOOKS_DIR = ROOT / ".vendored" / "pkg" / "pearls" / "hooks"


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_repo(tmp_path):
    """Create a temporary repo with git init and pearls structure."""
    subprocess.run(["git", "init", str(tmp_path)], check=True,
                   capture_output=True)
    # Create .vendored/pkg/pearls structure with copies of the real hooks
    pkg_dir = tmp_path / ".vendored" / "pkg" / "pearls"
    hooks_dir = pkg_dir / "hooks"
    hooks_dir.mkdir(parents=True)

    # Copy real hook scripts
    for name in ("post-install.sh", "session-start.sh", "session-resume.sh",
                 "pre-push"):
        src = HOOKS_DIR / name
        if src.exists():
            dst = hooks_dir / name
            dst.write_text(src.read_text())
            dst.chmod(src.stat().st_mode)

    # Create a stub merge-driver.py so post-install.sh finds it
    (pkg_dir / "merge-driver.py").write_text("#!/usr/bin/env python3\n")

    # Create a stub prl.py for session hooks
    (pkg_dir / "prl.py").write_text(
        '#!/usr/bin/env python3\n'
        'import sys\n'
        'print("prl stub called with:", " ".join(sys.argv[1:]))\n'
    )

    return tmp_path


def _run_hook(tmp_repo: Path, hook_name: str,
              env_overrides: dict[str, str] | None = None,
              ) -> subprocess.CompletedProcess[str]:
    """Run a hook script in the tmp_repo context."""
    hook_path = tmp_repo / ".vendored" / "pkg" / "pearls" / "hooks" / hook_name
    env = os.environ.copy()
    env["VENDOR_NAME"] = "pearls"
    env["VENDOR_PKG_DIR"] = str(tmp_repo / ".vendored" / "pkg" / "pearls")
    env["PROJECT_DIR"] = str(tmp_repo)
    # Ensure ~/.local/bin is on PATH for session hooks
    local_bin = tmp_repo / "fake_local_bin"
    local_bin.mkdir(exist_ok=True)
    env["HOME"] = str(tmp_repo / "fakehome")
    env["PATH"] = str(local_bin) + ":" + env.get("PATH", "")
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(hook_path)],
        capture_output=True, text=True, cwd=str(tmp_repo), env=env,
    )


# ── Tests: post-install.sh ────────────────────────────────────────────────


class TestPostInstallHook:
    def test_registers_merge_driver(self, tmp_repo):
        """post-install.sh registers the prl-jsonl merge driver in git config."""
        result = _run_hook(tmp_repo, "post-install.sh")
        assert result.returncode == 0

        # Check git config for merge driver
        cfg = subprocess.run(
            ["git", "config", "merge.prl-jsonl.name"],
            capture_output=True, text=True, cwd=str(tmp_repo),
        )
        assert cfg.returncode == 0
        assert "Pearls JSONL merge driver" in cfg.stdout

    def test_merge_driver_command(self, tmp_repo):
        """Merge driver command references merge-driver.py with correct path."""
        _run_hook(tmp_repo, "post-install.sh")

        cfg = subprocess.run(
            ["git", "config", "merge.prl-jsonl.driver"],
            capture_output=True, text=True, cwd=str(tmp_repo),
        )
        assert cfg.returncode == 0
        assert "merge-driver.py" in cfg.stdout

    def test_installs_pre_push_symlink(self, tmp_repo):
        """post-install.sh creates pre-push symlink in .git/hooks/."""
        result = _run_hook(tmp_repo, "post-install.sh")
        assert result.returncode == 0

        pre_push = tmp_repo / ".git" / "hooks" / "pre-push"
        assert pre_push.is_symlink()
        target = os.readlink(str(pre_push))
        assert "pre-push" in target
        assert "pearls" in target

    def test_skips_existing_non_symlink_pre_push(self, tmp_repo):
        """Warns and skips when .git/hooks/pre-push is a regular file."""
        hooks_dir = tmp_repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        pre_push = hooks_dir / "pre-push"
        pre_push.write_text("#!/bin/bash\nexit 0\n")

        result = _run_hook(tmp_repo, "post-install.sh")
        assert result.returncode == 0
        assert "already exists" in result.stderr
        # Should NOT be a symlink (original file preserved)
        assert not pre_push.is_symlink()

    def test_skips_foreign_symlink_pre_push(self, tmp_repo):
        """Warns and skips when pre-push is a symlink to a non-pearls target."""
        hooks_dir = tmp_repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        # Create a symlink pointing somewhere else
        foreign_target = tmp_repo / "other-hook.sh"
        foreign_target.write_text("#!/bin/bash\nexit 0\n")
        pre_push = hooks_dir / "pre-push"
        os.symlink(str(foreign_target), str(pre_push))

        result = _run_hook(tmp_repo, "post-install.sh")
        assert result.returncode == 0
        assert "skipping" in result.stderr.lower()
        # Symlink should still point to original target
        assert os.readlink(str(pre_push)) == str(foreign_target)

    def test_idempotent_with_existing_pearls_symlink(self, tmp_repo):
        """Running twice with existing pearls symlink doesn't error."""
        result1 = _run_hook(tmp_repo, "post-install.sh")
        assert result1.returncode == 0

        result2 = _run_hook(tmp_repo, "post-install.sh")
        assert result2.returncode == 0

        pre_push = tmp_repo / ".git" / "hooks" / "pre-push"
        assert pre_push.is_symlink()

    def test_skips_merge_driver_when_missing(self, tmp_repo):
        """No error when merge-driver.py doesn't exist."""
        md = tmp_repo / ".vendored" / "pkg" / "pearls" / "merge-driver.py"
        md.unlink()

        result = _run_hook(tmp_repo, "post-install.sh")
        assert result.returncode == 0

        # Merge driver should NOT be registered
        cfg = subprocess.run(
            ["git", "config", "merge.prl-jsonl.name"],
            capture_output=True, text=True, cwd=str(tmp_repo),
        )
        assert cfg.returncode != 0  # not found


# ── Tests: session-start.sh ───────────────────────────────────────────────


class TestSessionStartHook:
    def test_creates_prl_shim(self, tmp_repo):
        """session-start.sh creates a prl shim script in ~/.local/bin."""
        result = _run_hook(tmp_repo, "session-start.sh")
        # May fail because prl prompt isn't on PATH, but shim should be created
        shim = tmp_repo / "fakehome" / ".local" / "bin" / "prl"
        assert shim.exists()
        assert os.access(str(shim), os.X_OK)

    def test_shim_content_references_prl_py(self, tmp_repo):
        """The shim delegates to prl.py."""
        _run_hook(tmp_repo, "session-start.sh")
        shim = tmp_repo / "fakehome" / ".local" / "bin" / "prl"
        content = shim.read_text()
        assert "prl.py" in content
        assert "exec python3" in content

    def test_calls_prl_prompt(self, tmp_repo):
        """session-start.sh runs `prl prompt` after creating the shim."""
        # Make prl shim available on PATH so the script finds it
        shim_dir = tmp_repo / "fakehome" / ".local" / "bin"
        shim_dir.mkdir(parents=True, exist_ok=True)
        env = {"PATH": str(shim_dir) + ":" + os.environ.get("PATH", "")}
        result = _run_hook(tmp_repo, "session-start.sh", env_overrides=env)
        assert result.returncode == 0
        assert "prl stub called with: prompt" in result.stdout

    def test_respects_prl_prompt_mode(self, tmp_repo):
        """session-start.sh passes PRL_PROMPT_MODE to prl prompt."""
        shim_dir = tmp_repo / "fakehome" / ".local" / "bin"
        shim_dir.mkdir(parents=True, exist_ok=True)
        env = {
            "PATH": str(shim_dir) + ":" + os.environ.get("PATH", ""),
            "PRL_PROMPT_MODE": "impl",
        }
        result = _run_hook(tmp_repo, "session-start.sh", env_overrides=env)
        assert result.returncode == 0
        assert "prl stub called with: prompt impl" in result.stdout


# ── Tests: session-resume.sh ──────────────────────────────────────────────


class TestSessionResumeHook:
    def test_creates_prl_shim(self, tmp_repo):
        """session-resume.sh creates a prl shim script in ~/.local/bin."""
        result = _run_hook(tmp_repo, "session-resume.sh")
        shim = tmp_repo / "fakehome" / ".local" / "bin" / "prl"
        assert shim.exists()
        assert os.access(str(shim), os.X_OK)

    def test_calls_prl_prompt_resume(self, tmp_repo):
        """session-resume.sh runs `prl prompt --resume`."""
        shim_dir = tmp_repo / "fakehome" / ".local" / "bin"
        shim_dir.mkdir(parents=True, exist_ok=True)
        env = {"PATH": str(shim_dir) + ":" + os.environ.get("PATH", "")}
        result = _run_hook(tmp_repo, "session-resume.sh", env_overrides=env)
        assert result.returncode == 0
        assert "prl stub called with: prompt --resume" in result.stdout

    def test_shim_identical_to_session_start(self, tmp_repo):
        """Both session hooks create the same shim content."""
        shim_dir = tmp_repo / "fakehome" / ".local" / "bin"
        shim_dir.mkdir(parents=True, exist_ok=True)
        env = {"PATH": str(shim_dir) + ":" + os.environ.get("PATH", "")}

        _run_hook(tmp_repo, "session-start.sh", env_overrides=env)
        shim = tmp_repo / "fakehome" / ".local" / "bin" / "prl"
        start_content = shim.read_text()

        _run_hook(tmp_repo, "session-resume.sh", env_overrides=env)
        resume_content = shim.read_text()

        assert start_content == resume_content
