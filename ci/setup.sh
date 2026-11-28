#!/bin/bash
# ci/setup.sh - setup for git-vendored's own `test` job.
#
# Reads the Python floor from requires-python in pyproject.toml, uses that
# Python if present (python3.X, the runner tool cache) or installs it with uv
# (itself installed into a small venv when missing), and installs what the
# test suite needs (pytest, pyyaml) into a virtualenv ci/test.sh finds on
# disk. No Python version is written in the workflow or the config: this
# script is the only place that decides it.
set -euo pipefail

FLOOR="$(sed -n 's/^requires-python *= *">= *\([0-9][0-9.]*\)".*/\1/p' pyproject.toml | head -n1)"
if [ -z "$FLOOR" ]; then
    echo "ci/setup.sh: cannot read requires-python (\">=X.Y\") from pyproject.toml" >&2
    exit 1
fi
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/git-vendored-ci"
VENV="$CACHE/venv-$FLOOR"
TOOLS="$CACHE/tools"   # holds uv when it has to be installed

find_floor() {
    local candidate
    for candidate in "python$FLOOR" /opt/hostedtoolcache/Python/"$FLOOR".*/x64/bin/python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done
    local uv
    uv="$(command -v uv 2>/dev/null || true)"
    if [ -z "$uv" ] && python3 -m venv "$TOOLS" >&2 \
            && "$TOOLS/bin/python" -m pip install --quiet uv >&2; then
        uv="$TOOLS/bin/uv"
    fi
    if [ -n "$uv" ]; then
        "$uv" python install "$FLOOR" >&2 && "$uv" python find "$FLOOR" && return 0
    fi
    return 1
}

if PYTHON="$(find_floor)"; then
    echo "ci/setup.sh: using Python $FLOOR at $PYTHON"
elif [ -z "${CI:-}" ] && python3 -c "import sys; sys.exit(sys.version_info < tuple(map(int, '$FLOOR'.split('.'))))"; then
    PYTHON="$(command -v python3)"
    echo "ci/setup.sh: Python $FLOOR not found; using $("$PYTHON" --version) locally (CI runs the floor)"
else
    echo "ci/setup.sh: Python $FLOOR not found (looked for python$FLOOR and the runner tool cache; uv could not install it)" >&2
    exit 1
fi

"$PYTHON" -m venv --clear "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet pytest pyyaml
"$VENV/bin/python" --version
