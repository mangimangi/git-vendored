"""Suite-wide test setup.

Coverage of subprocess runs: ci/test.sh exports COVERAGE_PROCESS_START and
GIT_VENDORED_ROOT, and the .pth hook ci/setup.sh installs starts coverage in
any Python process that inherits them. A test that passes its own ``env=``
dict to subprocess would drop them, so that child's run would silently not be
counted. This wraps ``subprocess.Popen`` (which ``run``, ``call`` and
``check_output`` all use) to copy those variables into such an env when the
test did not set them itself.

Tokens: no test may read a token from the ambient environment. In CI the
job's environment holds real secrets (CICD_WRITE_TOKEN, CICD_READ_TOKEN,
VENDOR_PAT), and a failed assertion that compares against one prints part of
it, which GitHub does not mask. So CICD_WRITE_TOKEN, CICD_READ_TOKEN,
VENDOR_PAT, GH_TOKEN and GITHUB_TOKEN are removed from os.environ when
this file is imported (before collection and any session fixture), and again
before every test by an autouse fixture; a test that needs one sets a fake
value with monkeypatch.

Network: every test runs with GIT_ALLOW_PROTOCOL=file, so git reads only
local repositories (the ``vendor_repo`` fixture's file:// URLs) and a test
that would reach a real host fails.

CI marker: GITHUB_ACTIONS is set in CI, and the installer's --pr mode refuses
to run there without a write token. Each test starts without it, so a test
behaves the same locally and in CI; a test of the CI behaviour sets it.
"""

import os
import subprocess

import pytest

TOKEN_ENV_VARS = ("CICD_WRITE_TOKEN", "CICD_READ_TOKEN", "VENDOR_PAT",
                  "GH_TOKEN", "GITHUB_TOKEN")


def clear_token_env():
    """Remove every token variable from os.environ."""
    for name in TOKEN_ENV_VARS:
        os.environ.pop(name, None)


clear_token_env()


@pytest.fixture(autouse=True)
def _no_ambient_tokens(monkeypatch):
    """Each test starts with no token variable set."""
    for name in TOKEN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    # git may only read local repositories: a test that would reach a real
    # host (an owner/repo shorthand means github.com) fails instead.
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")


COVERAGE_ENV_VARS = ("COVERAGE_PROCESS_START", "GIT_VENDORED_ROOT", "COVERAGE_RCFILE")


def with_coverage_env(env):
    """Return ``env`` with the coverage variables from os.environ added."""
    if env is None:
        return None
    merged = dict(env)
    for name in COVERAGE_ENV_VARS:
        if name in os.environ and name not in merged:
            merged[name] = os.environ[name]
    return merged


_original_popen_init = subprocess.Popen.__init__


def _popen_init(self, *args, **kwargs):
    if kwargs.get("env") is not None:
        kwargs["env"] = with_coverage_env(kwargs["env"])
    _original_popen_init(self, *args, **kwargs)


subprocess.Popen.__init__ = _popen_init


# ── Local git repositories used as vendors ────────────────────────────────

GIT_ISOLATION_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class VendorRepo:
    """A local git repository used as a vendor, addressed by a file:// URL.

    Nothing reaches the network: the installer, validate and the tests read
    it with git the way they would read a vendor on any host.
    """

    def __init__(self, path):
        self.path = path
        self.url = path.as_uri()
        path.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *args):
        env = dict(os.environ, **GIT_ISOLATION_ENV)
        result = subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t",
             "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
            cwd=str(self.path), capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def write(self, relpath, content, mode=None):
        target = self.path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)
        if mode is not None:
            target.chmod(mode)
        return target

    def remove(self, relpath):
        self.git("rm", "-q", "-r", relpath)

    def commit(self, message="change"):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.rev("HEAD")

    def tag(self, name, annotated=False, ref="HEAD"):
        """Tag `ref`; returns the commit the tag points at."""
        if annotated:
            self.git("tag", "-a", name, "-m", name, ref)
        else:
            self.git("tag", name, ref)
        return self.rev(f"{name}^{{commit}}")

    def move_tag(self, name, ref="HEAD"):
        self.git("tag", "-f", name, ref)
        return self.rev(f"{name}^{{commit}}")

    def rev(self, ref):
        return self.git("rev-parse", ref)


@pytest.fixture
def vendor_repo(tmp_path_factory, monkeypatch):
    """Factory for local git vendor repositories (file:// URLs).

    Also isolates every git command the test runs from the user's and the
    system's git config.
    """
    for key, value in GIT_ISOLATION_ENV.items():
        monkeypatch.setenv(key, value)
    base = tmp_path_factory.mktemp("vendors")

    def _make(name="tool"):
        return VendorRepo(base / name)
    return _make
