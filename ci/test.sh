#!/bin/bash
# ci/test.sh - the step of git-vendored's own `test` job: run pytest under
# coverage, print the per-file line coverage of the shipped Python scripts,
# and fail when the total or any one file is below 99% (fail_under in
# pyproject.toml; the per-file check is below, coverage has no setting for it).
# Then runs the bats tests for the shell scripts (tests/bats/); the step fails
# when either suite fails.
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
BATS_VERSION="$(sed -n 's/^BATS_VERSION="\(.*\)"$/\1/p' ci/setup.sh | head -n1)"
BATS_CACHED="${XDG_CACHE_HOME:-$HOME/.cache}/git-vendored-ci/bats-$BATS_VERSION/bin/bats"

if [ -x "$VENV/bin/python" ]; then
    PYTHON="$VENV/bin/python"
elif python3 -c "import pytest, yaml, coverage" 2>/dev/null; then
    PYTHON=python3
else
    echo "ci/test.sh: pytest, pyyaml or coverage is not installed; $SETUP_HINT" >&2
    exit 1
fi

if command -v bats >/dev/null 2>&1; then
    BATS="$(command -v bats)"
elif [ -x "$BATS_CACHED" ]; then
    BATS="$BATS_CACHED"
else
    echo "ci/test.sh: bats is not installed; $SETUP_HINT" >&2
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
# The full report is always printed; its exit code is non-zero when the total
# is below fail_under.
"$PYTHON" -m coverage report || status=$?

# Per file: each measured script must be at the threshold too, so one file
# below it fails the job even when the total is above.
JSON="$(mktemp)"
trap 'rm -f "$JSON"' EXIT
"$PYTHON" -m coverage json --quiet --fail-under=0 -o "$JSON"
THRESHOLD="$(sed -n 's/^fail_under *= *\([0-9][0-9.]*\).*/\1/p' pyproject.toml | head -n1)"
"$PYTHON" - "$JSON" "${THRESHOLD:-99}" <<'PY' || status=$?
import json, sys
data = json.load(open(sys.argv[1]))
threshold = float(sys.argv[2])
low = []
for name, info in sorted(data["files"].items()):
    pct = info["summary"]["percent_covered"]
    if pct < threshold:
        low.append((name, pct, info["missing_lines"]))
def ranges(lines):
    out, start, prev = [], None, None
    for n in lines + [None]:
        if start is not None and n != prev + 1:
            out.append(str(start) if start == prev else f"{start}-{prev}")
            start = None
        if start is None:
            start = n
        prev = n
    return ", ".join(out)
for name, pct, missing in low:
    print(f"ci/test.sh: {name} is at {pct:.2f}% line coverage, below {threshold:g}%; "
          f"missing lines: {ranges(missing)}", file=sys.stderr)
if low:
    print("ci/test.sh: add tests for those lines in this pull request "
          "(see Coverage in AGENTS.md)", file=sys.stderr)
sys.exit(1 if low else 0)
PY

"$BATS" --version
"$BATS" tests/bats/ || status=$?
exit "$status"
