#!/bin/bash
# ci/setup.sh - setup for git-vendored's own `test` job.
#
# Reads the Python floor from requires-python in pyproject.toml, uses that
# Python if present (python3.X, the runner tool cache) or installs it with uv
# (itself installed into a small venv when missing), and installs what the
# test suite needs (pytest, pyyaml, coverage) into a virtualenv ci/test.sh
# finds on disk, with a .pth startup hook so Python processes the tests start
# as subprocesses are measured too. When no `bats` is on PATH it also puts a
# pinned bats-core in the cache for the shell tests (tests/bats/). No Python version is written in the workflow or the config: this
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
# coverage 7.6 is the last line that supports Python 3.8 (the floor); [toml]
# pulls tomli there so the [tool.coverage] settings in pyproject.toml are read.
"$VENV/bin/python" -m pip install --quiet pytest pyyaml "coverage[toml]>=7.2,<7.7"
# Subprocess measurement: every interpreter started from this venv runs this
# hook, which starts coverage only when COVERAGE_PROCESS_START is set (as
# ci/test.sh does). coverage 7.10's patch = ["subprocess"] would replace it,
# but does not support Python 3.8.
SITE="$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
echo "import coverage; coverage.process_startup()" > "$SITE/git-vendored-coverage.pth"
"$VENV/bin/python" --version

# bats-core for the shell tests: the one on PATH if there is one, otherwise a
# pinned release (the npm registry tarball, checked against its sha256) in
# the cache, where ci/test.sh looks for it.
BATS_VERSION="1.11.1"
BATS_SHA256="1d8a88fc70bc5a518c7cf17e5201b80b24e9475be95abe6508b3197a64b73365"
BATS_DIR="$CACHE/bats-$BATS_VERSION"
if command -v bats >/dev/null 2>&1; then
    echo "ci/setup.sh: using $(bats --version) at $(command -v bats)"
elif [ -x "$BATS_DIR/bin/bats" ]; then
    echo "ci/setup.sh: using bats $BATS_VERSION at $BATS_DIR/bin/bats"
else
    TARBALL="$CACHE/bats-$BATS_VERSION.tgz"
    curl -fsSL "https://registry.npmjs.org/bats/-/bats-$BATS_VERSION.tgz" -o "$TARBALL"
    if ! echo "$BATS_SHA256  $TARBALL" | sha256sum -c --status; then
        echo "ci/setup.sh: bats $BATS_VERSION download does not match its sha256" >&2
        rm -f "$TARBALL"
        exit 1
    fi
    rm -rf "$BATS_DIR" && mkdir -p "$BATS_DIR"
    tar xzf "$TARBALL" -C "$BATS_DIR" --strip-components=1
    rm -f "$TARBALL"
    echo "ci/setup.sh: installed bats $BATS_VERSION at $BATS_DIR/bin/bats"
fi
