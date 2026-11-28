"""Run each shipped Python script as a program, the way a consumer does.

The other test files load the scripts in-process with SourceFileLoader, so
their ``if __name__ == "__main__":`` lines only run here. That makes this file
the proof that coverage counts subprocess runs: those lines show as covered in
the report only because these child processes were measured (ci/test.sh sets
COVERAGE_PROCESS_START; ci/setup.sh installs the startup hook).

Every invocation is harmless and offline: ``--help`` for the argparse scripts,
an empty temporary repo for the others.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def run_script(relpath, args, cwd):
    return subprocess.run(
        [sys.executable, str(ROOT / relpath), *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=60,
    )


@pytest.mark.parametrize("relpath", [
    "templates/install",
    "templates/check",
    "templates/remove",
    "validate",
])
def test_help_exits_zero(relpath, tmp_path):
    result = run_script(relpath, ["--help"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("usage:")


def test_feedback_with_no_vendors(tmp_path):
    (tmp_path / ".vendored").mkdir()
    result = run_script("templates/feedback", [], tmp_path)
    assert result.returncode == 0, result.stderr
    assert "No installed vendors found." in result.stdout


def test_audit_with_no_schemas(tmp_path):
    (tmp_path / ".vendored").mkdir()
    result = run_script("templates/audit", [], tmp_path)
    assert result.returncode == 0, result.stderr
    assert "No vendor schemas installed." in result.stdout
