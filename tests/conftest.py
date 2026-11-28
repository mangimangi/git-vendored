"""Suite-wide test setup.

Coverage of subprocess runs: ci/test.sh exports COVERAGE_PROCESS_START and
GIT_VENDORED_ROOT, and the .pth hook ci/setup.sh installs starts coverage in
any Python process that inherits them. A test that passes its own ``env=``
dict to subprocess would drop them, so that child's run would silently not be
counted. This wraps ``subprocess.Popen`` (which ``run``, ``call`` and
``check_output`` all use) to copy those variables into such an env when the
test did not set them itself.
"""

import os
import subprocess

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
