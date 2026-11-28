#!/bin/bash
# ci/test.sh - the step of git-vendored's own `test` job: run pytest under
# coverage and print the per-file line coverage of the shipped Python scripts.
#
# Uses the virtualenv ci/setup.sh creates for the Python floor. When setup was
# skipped (a local `git-cicd check` without --setup), falls back to a python3
# that already has pytest, pyyaml and coverage.
#
# Which files are measured is set in [tool.coverage.run] in pyproject.toml.
# COVERAGE_PROCESS_START makes the .pth hook ci/setup.sh installs start
# coverage in every Python subprocess a test runs, so those runs count too.
set -euo pipefail

FLOOR="$(sed -n 's/^requires-python *= *">= *\([0-9][0-9.]*\)".*/\1/p' pyproject.toml | head -n1)"
VENV="${XDG_CACHE_HOME:-$HOME/.cache}/git-vendored-ci/venv-$FLOOR"
SETUP_HINT="run: .vendored/pkg/git-cicd/git-cicd check --setup"

if [ -x "$VENV/bin/python" ]; then
    PYTHON="$VENV/bin/python"
elif python3 -c "import pytest, yaml, coverage" 2>/dev/null; then
    PYTHON=python3
else
    echo "ci/test.sh: pytest, pyyaml or coverage is not installed; $SETUP_HINT" >&2
    exit 1
fi

"$PYTHON" --version
if ! "$PYTHON" -c "import coverage" 2>/dev/null; then
    echo "ci/test.sh: coverage is not installed in $PYTHON; $SETUP_HINT" >&2
    exit 1
fi
if ! "$PYTHON" -c 'import sys, sysconfig, os; sys.exit(not os.path.exists(os.path.join(sysconfig.get_paths()["purelib"], "git-vendored-coverage.pth")))'; then
    echo "ci/test.sh: warning: the coverage subprocess hook is not installed for $PYTHON," >&2
    echo "ci/test.sh: so subprocess runs are not counted and the figures will differ from CI; $SETUP_HINT" >&2
fi

export COVERAGE_PROCESS_START="$PWD/pyproject.toml"
export GIT_VENDORED_ROOT="$PWD"
"$PYTHON" -m coverage erase
status=0
"$PYTHON" -m coverage run -m pytest tests/ -v || status=$?
"$PYTHON" -m coverage combine --quiet
"$PYTHON" -m coverage report
exit "$status"
