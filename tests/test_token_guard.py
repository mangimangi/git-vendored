"""The suite-wide token guard in conftest.py (gv-895e).

No test may read a real token from the ambient environment: in CI it holds
the repository's VENDOR_PAT, and a failed comparison against it prints part
of the value in a public log. These tests fail if the guard is removed.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import conftest

TESTS_DIR = Path(__file__).resolve().parent


def test_test_body_sees_no_token():
    for name in conftest.TOKEN_ENV_VARS:
        assert name not in os.environ, f"{name} leaked into a test body"


def test_guard_covers_all_token_variables():
    assert set(conftest.TOKEN_ENV_VARS) == {"VENDOR_PAT", "GH_TOKEN",
                                            "GITHUB_TOKEN"}


def test_outer_vendor_pat_is_not_seen_by_a_test(tmp_path):
    """Run a test under this conftest with tokens in the outer environment."""
    shutil.copy(TESTS_DIR / "conftest.py", tmp_path / "conftest.py")
    (tmp_path / "test_inner.py").write_text(
        "import os\n"
        "def test_inner():\n"
        "    for name in ('VENDOR_PAT', 'GH_TOKEN', 'GITHUB_TOKEN'):\n"
        "        assert name not in os.environ, name\n"
    )
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PYTEST_")}
    env.update(VENDOR_PAT="outer-fake-pat", GH_TOKEN="outer-fake-gh",
               GITHUB_TOKEN="outer-fake-gt",
               # The inner run measures nothing: keep coverage out of it.
               COVERAGE_PROCESS_START="")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         str(tmp_path)],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
