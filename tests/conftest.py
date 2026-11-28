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
