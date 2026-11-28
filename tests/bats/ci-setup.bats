#!/usr/bin/env bats
# ci/setup.sh: finds or installs the Python floor, builds the venv with the
# coverage hook, and provides bats. All interpreters, uv, curl and bats are
# stubs; nothing is downloaded or installed for real.

load ci-helpers

setup() {
    ci_setup
    CACHE="$XDG_CACHE_HOME/git-vendored-ci"
    export STUB_SITE="$BATS_TEST_TMPDIR/site-packages"
    # A uv that "installs" a Python and reports a fake interpreter's path.
    export STUB_FOUND_PYTHON="$BATS_TEST_TMPDIR/uv-python/bin/python3.11"
    fake_python "$STUB_FOUND_PYTHON"
    export STUB_UV="$BATS_TEST_TMPDIR/uv-template"
    cat > "$STUB_UV" <<'STUB'
#!/bin/bash
echo "uv $*" >> "$STUB_LOG"
if [ "$2" = "install" ]; then exit "${STUB_UV_INSTALL_STATUS:-0}"; fi
if [ "$2" = "find" ]; then echo "$STUB_FOUND_PYTHON"; fi
exit 0
STUB
    chmod +x "$STUB_UV"
    stub "$BIN/bats" 0 "Bats 9.9.9"
}

run_setup() { run env PATH="$BIN" "$@" bash "$ROOT/ci/setup.sh"; }

@test "no requires-python in pyproject.toml: error, exit 1" {
    echo '[project]' > pyproject.toml
    run_setup
    [ "$status" -eq 1 ]
    [[ "$output" == *'ci/setup.sh: cannot read requires-python (">=X.Y") from pyproject.toml'* ]]
}

@test "python<floor> on PATH is used; venv built in XDG_CACHE_HOME with pytest, pyyaml, coverage" {
    fake_python "$BIN/python3.11"
    run_setup
    [ "$status" -eq 0 ]
    [[ "$output" == *"ci/setup.sh: using Python 3.11 at $BIN/python3.11"* ]]
    logged "python3.11 -m venv --clear $CACHE/venv-3.11"
    logged "python -m pip install --quiet --upgrade pip"
    logged 'python -m pip install --quiet pytest pyyaml coverage>=7.2'
    [ -x "$CACHE/venv-3.11/bin/python" ]
    [[ "$output" == *"Python 3.11.99"* ]]
    ! logged "uv "
}

@test "writes the coverage startup hook into the venv's site-packages" {
    fake_python "$BIN/python3.11"
    run_setup
    [ "$status" -eq 0 ]
    [ "$(cat "$STUB_SITE/git-vendored-coverage.pth")" = "import coverage; coverage.process_startup()" ]
}

@test "the venv goes under HOME/.cache when XDG_CACHE_HOME is unset" {
    fake_python "$BIN/python3.11"
    run env -u XDG_CACHE_HOME PATH="$BIN" bash "$ROOT/ci/setup.sh"
    [ "$status" -eq 0 ]
    [ -x "$HOME/.cache/git-vendored-ci/venv-3.11/bin/python" ]
}

@test "the floor comes from requires-python" {
    write_pyproject ">= 3.13"
    fake_python "$BIN/python3.13"
    run_setup
    [ "$status" -eq 0 ]
    [[ "$output" == *"using Python 3.13 at $BIN/python3.13"* ]]
    [ -x "$CACHE/venv-3.13/bin/python" ]
}

@test "the runner tool cache is used when python<floor> is not on PATH" {
    fake_python "$RUNNER_TOOL_CACHE/Python/3.11.7/x64/bin/python3"
    run_setup
    [ "$status" -eq 0 ]
    [[ "$output" == *"using Python 3.11 at $RUNNER_TOOL_CACHE/Python/3.11.7/x64/bin/python3"* ]]
    logged "python3 -m venv --clear $CACHE/venv-3.11"
}

@test "the tool cache of another Python version is not used" {
    fake_python "$RUNNER_TOOL_CACHE/Python/3.12.1/x64/bin/python3"
    run_setup CI=true STUB_PIP_UV_STATUS=1
    [ "$status" -eq 1 ]
    [[ "$output" == *"Python 3.11 not found"* ]]
}

@test "RUNNER_TOOL_CACHE unset: the tool cache is /opt/hostedtoolcache" {
    grep -qF 'TOOLCACHE="${RUNNER_TOOL_CACHE:-/opt/hostedtoolcache}"' "$ROOT/ci/setup.sh"
}

@test "uv on PATH installs the floor when no interpreter is found" {
    cp "$STUB_UV" "$BIN/uv"
    run_setup
    [ "$status" -eq 0 ]
    logged "uv python install 3.11"
    logged "uv python find 3.11"
    [[ "$output" == *"using Python 3.11 at $STUB_FOUND_PYTHON"* ]]
    logged "python3.11 -m venv --clear $CACHE/venv-3.11"
}

@test "without uv, uv is installed into a tools venv in the cache and used" {
    fake_python "$BIN/python3"
    run_setup
    [ "$status" -eq 0 ]
    logged "python3 -m venv $CACHE/tools"
    logged "python -m pip install --quiet uv"
    [ -x "$CACHE/tools/bin/uv" ]
    logged "uv python install 3.11"
    [[ "$output" == *"using Python 3.11 at $STUB_FOUND_PYTHON"* ]]
}

@test "uv that cannot install the floor: falls back to local python3 outside CI" {
    fake_python "$BIN/python3"
    cp "$STUB_UV" "$BIN/uv"
    run_setup STUB_UV_INSTALL_STATUS=1
    [ "$status" -eq 0 ]
    [[ "$output" == *"ci/setup.sh: Python 3.11 not found; using Python 3.11.99 locally (CI runs the floor)"* ]]
    logged "python3 -m venv --clear $CACHE/venv-3.11"
}

@test "uv cannot be installed: falls back to local python3 outside CI" {
    fake_python "$BIN/python3"
    run_setup STUB_PIP_UV_STATUS=1
    [ "$status" -eq 0 ]
    [[ "$output" == *"Python 3.11 not found; using Python 3.11.99 locally"* ]]
    ! logged "uv python"
}

@test "floor not found in CI: error, exit 1" {
    fake_python "$BIN/python3"
    run_setup CI=true STUB_PIP_UV_STATUS=1
    [ "$status" -eq 1 ]
    [[ "$output" == *"ci/setup.sh: Python 3.11 not found (looked for python3.11 and the runner tool cache; uv could not install it)"* ]]
    [ ! -e "$CACHE/venv-3.11" ]
}

@test "floor not found and local python3 older than the floor: error, exit 1" {
    fake_python "$BIN/python3"
    run_setup STUB_PIP_UV_STATUS=1 STUB_PY_VERSION=3.10.14
    [ "$status" -eq 1 ]
    [[ "$output" == *"ci/setup.sh: Python 3.11 not found"* ]]
    [ ! -e "$CACHE/venv-3.11" ]
}

@test "a failing pip install fails setup" {
    fake_python "$BIN/python3.11"
    run_setup STUB_PIP_STATUS=1
    [ "$status" -ne 0 ]
    [ ! -e "$STUB_SITE/git-vendored-coverage.pth" ]
}

@test "bats on PATH is used as is" {
    fake_python "$BIN/python3.11"
    run_setup
    [ "$status" -eq 0 ]
    [[ "$output" == *"ci/setup.sh: using Bats 9.9.9 at $BIN/bats"* ]]
    ! logged "curl"
}

@test "a cached bats is reused without downloading" {
    fake_python "$BIN/python3.11"
    rm "$BIN/bats"
    stub "$CACHE/bats-1.11.1/bin/bats"
    run_setup
    [ "$status" -eq 0 ]
    [[ "$output" == *"ci/setup.sh: using bats 1.11.1 at $CACHE/bats-1.11.1/bin/bats"* ]]
    ! logged "curl"
}

# A copy of setup.sh whose pinned sha256 is that of a local fake tarball, and a
# curl that "downloads" that tarball.
fake_bats_download() {
    mkdir -p "$BATS_TEST_TMPDIR/pkg/package/bin"
    printf '#!/bin/bash\necho fake bats\n' > "$BATS_TEST_TMPDIR/pkg/package/bin/bats"
    chmod +x "$BATS_TEST_TMPDIR/pkg/package/bin/bats"
    tar czf "$BATS_TEST_TMPDIR/bats.tgz" -C "$BATS_TEST_TMPDIR/pkg" package
    local sha
    sha="$(sha256sum "$BATS_TEST_TMPDIR/bats.tgz" | cut -c1-64)"
    sed "s/^BATS_SHA256=.*/BATS_SHA256=\"${1:-$sha}\"/" "$ROOT/ci/setup.sh" > "$WORK/ci/setup.sh"
    cat > "$BIN/curl" <<STUB
#!/bin/bash
echo "curl \$*" >> "\$STUB_LOG"
[ "\${STUB_CURL_STATUS:-0}" = 0 ] || exit "\$STUB_CURL_STATUS"
out=""; prev=""
for a in "\$@"; do [ "\$prev" = "-o" ] && out="\$a"; prev="\$a"; done
cp "$BATS_TEST_TMPDIR/bats.tgz" "\$out"
STUB
    chmod +x "$BIN/curl"
    rm "$BIN/bats"
    fake_python "$BIN/python3.11"
}

@test "no bats: downloads the pinned release, checks its sha256, unpacks it into the cache" {
    ln -s "$(command -v cut)" "$BIN/cut"
    fake_bats_download
    run env PATH="$BIN" bash "$WORK/ci/setup.sh"
    [ "$status" -eq 0 ]
    logged "curl -fsSL https://registry.npmjs.org/bats/-/bats-1.11.1.tgz -o $CACHE/bats-1.11.1.tgz"
    [[ "$output" == *"ci/setup.sh: installed bats 1.11.1 at $CACHE/bats-1.11.1/bin/bats"* ]]
    [ "$("$CACHE/bats-1.11.1/bin/bats")" = "fake bats" ]
    [ ! -e "$CACHE/bats-1.11.1.tgz" ]
}

@test "a bats download that does not match the pinned sha256: error, exit 1, nothing kept" {
    ln -s "$(command -v cut)" "$BIN/cut"
    fake_bats_download "0000000000000000000000000000000000000000000000000000000000000000"
    run env PATH="$BIN" bash "$WORK/ci/setup.sh"
    [ "$status" -eq 1 ]
    [[ "$output" == *"ci/setup.sh: bats 1.11.1 download does not match its sha256"* ]]
    [ ! -e "$CACHE/bats-1.11.1.tgz" ]
    [ ! -e "$CACHE/bats-1.11.1" ]
}

@test "a failed bats download fails setup" {
    ln -s "$(command -v cut)" "$BIN/cut"
    fake_bats_download
    run env PATH="$BIN" STUB_CURL_STATUS=22 bash "$WORK/ci/setup.sh"
    [ "$status" -eq 22 ]
    [ ! -e "$CACHE/bats-1.11.1/bin/bats" ]
}

@test "the pinned bats version and sha256 in setup.sh are well formed" {
    grep -qE '^BATS_VERSION="[0-9]+\.[0-9]+\.[0-9]+"$' "$ROOT/ci/setup.sh"
    grep -qE '^BATS_SHA256="[0-9a-f]{64}"$' "$ROOT/ci/setup.sh"
}
