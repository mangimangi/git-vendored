# Shared setup for the ci/*.sh bats tests.
#
# Each test runs a copy-free invocation of the real ci script from a temporary
# "checkout" (its own pyproject.toml, ci/setup.sh) with HOME and
# XDG_CACHE_HOME in the temp dir and PATH limited to a bin dir holding only
# the coreutils the scripts need plus stubs. RUNNER_TOOL_CACHE (the runner
# tool cache ci/setup.sh looks in) is an empty directory in the temp dir, so
# no Python the machine has, on PATH or in its tool cache, is found. Stubs log
# every call to $STUB_LOG; nothing touches the network or the real cache.

ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"

ci_setup() {
    WORK="$BATS_TEST_TMPDIR/work"
    BIN="$BATS_TEST_TMPDIR/bin"
    STUB_LOG="$BATS_TEST_TMPDIR/stub.log"
    REAL_PYTHON3="$(command -v python3)"
    mkdir -p "$WORK/ci" "$BIN" "$BATS_TEST_TMPDIR/home" "$BATS_TEST_TMPDIR/cache"
    : > "$STUB_LOG"
    export HOME="$BATS_TEST_TMPDIR/home"
    export XDG_CACHE_HOME="$BATS_TEST_TMPDIR/cache"
    export RUNNER_TOOL_CACHE="$BATS_TEST_TMPDIR/toolcache"
    mkdir -p "$RUNNER_TOOL_CACHE"
    export STUB_LOG REAL_PYTHON3
    unset CI GITHUB_HEAD_REF CICD_SOURCE_BRANCH CICD_BASE COVERAGE_PROCESS_START GIT_VENDORED_ROOT
    # No test reads a token from the ambient environment (CI holds real
    # secrets); a test that needs one passes a fake value.
    unset CICD_WRITE_TOKEN CICD_READ_TOKEN VENDOR_PAT GH_TOKEN GITHUB_TOKEN
    local tool dir
    for tool in bash sh sed head mktemp rm mkdir cp chmod cat sha256sum tar gzip \
                dirname basename env grep ln ls touch sort tr; do
        for dir in /usr/bin /bin /usr/local/bin; do
            if [ -x "$dir/$tool" ]; then
                ln -s "$dir/$tool" "$BIN/$tool"
                break
            fi
        done
    done
    cp "$ROOT/ci/setup.sh" "$WORK/ci/setup.sh"
    write_pyproject ">=3.11" 99
    cd "$WORK"
}

# write_pyproject <requires-python> [fail_under]
write_pyproject() {
    {
        echo '[project]'
        echo "requires-python = \"$1\""
        if [ -n "${2:-}" ]; then
            echo '[tool.coverage.report]'
            echo "fail_under = $2"
        fi
    } > "$WORK/pyproject.toml"
}

# A fake Python interpreter. It answers the calls ci/setup.sh and ci/test.sh
# make, logs them, and runs "-" (an inline script) with the real python3 so
# the per-file coverage check in ci/test.sh is exercised for real. It reports
# itself as Python $STUB_PY_VERSION (default 3.11.99), also to the version
# check ci/setup.sh makes, whatever version the real python3 is.
fake_python() {
    local dest="$1"
    mkdir -p "$(dirname "$dest")"
    cat > "$dest" <<'PYSTUB'
#!/bin/bash
echo "$(basename "$0") $*" >> "$STUB_LOG"
case "${1:-}" in
    --version) echo "Python ${STUB_PY_VERSION:-3.11.99}"; exit 0 ;;
    -)  exec "$REAL_PYTHON3" "$@" ;;
    -c)
        case "$2" in
            *git-vendored-coverage.pth*) exit "${STUB_HOOK_STATUS:-0}" ;;
            *sysconfig*) mkdir -p "$STUB_SITE"; echo "$STUB_SITE"; exit 0 ;;
            *"import pytest, yaml, coverage"*) exit "${STUB_IMPORT_STATUS:-0}" ;;
            *"import coverage"*) exit "${STUB_COVERAGE_STATUS:-0}" ;;
            *sys.version_info*)
                exec "$REAL_PYTHON3" - "${STUB_PY_VERSION:-3.11.99}" "$2" <<'PY'
import re, sys
have = tuple(map(int, sys.argv[1].split(".")))
want = tuple(map(int, re.search(r"'([0-9.]+)'", sys.argv[2]).group(1).split(".")))
sys.exit(have < want)
PY
                ;;
            *) exec "$REAL_PYTHON3" "$@" ;;
        esac ;;
    -m)
        case "$2" in
            venv)
                dir="${!#}"
                [ "${STUB_VENV_STATUS:-0}" = 0 ] || exit "$STUB_VENV_STATUS"
                mkdir -p "$dir/bin"; cp "$0" "$dir/bin/python"; exit 0 ;;
            pip)
                if [ "${!#}" = "uv" ]; then
                    [ "${STUB_PIP_UV_STATUS:-0}" = 0 ] || exit "$STUB_PIP_UV_STATUS"
                    cp "$STUB_UV" "$(dirname "$0")/uv"
                    exit 0
                fi
                exit "${STUB_PIP_STATUS:-0}" ;;
            coverage)
                case "$3" in
                    run)
                        echo "env COVERAGE_PROCESS_START=${COVERAGE_PROCESS_START:-} GIT_VENDORED_ROOT=${GIT_VENDORED_ROOT:-}" >> "$STUB_LOG"
                        echo "PYTEST-OUTPUT"
                        exit "${STUB_PYTEST_STATUS:-0}" ;;
                    report) echo "REPORT-OUTPUT"; exit "${STUB_REPORT_STATUS:-0}" ;;
                    json)
                        out=""; prev=""
                        for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
                        cp "$STUB_COVERAGE_JSON" "$out"; exit 0 ;;
                    *) exit 0 ;;
                esac ;;
        esac ;;
esac
exit 0
PYSTUB
    chmod +x "$dest"
}

# stub <path> [exit status] [stdout]: a command that logs its name and args.
stub() {
    local dest="$1" status="${2:-0}" out="${3:-}"
    mkdir -p "$(dirname "$dest")"
    cat > "$dest" <<STUB
#!/bin/bash
echo "\$(basename "\$0") \$*" >> "\$STUB_LOG"
${out:+echo "$out"}
exit $status
STUB
    chmod +x "$dest"
}

# coverage_json <file> <name=percent:missing,lines>...
coverage_json() {
    local dest="$1"; shift
    "$REAL_PYTHON3" - "$dest" "$@" <<'PY'
import json, sys
files = {}
for spec in sys.argv[2:]:
    name, rest = spec.split("=", 1)
    pct, _, missing = rest.partition(":")
    files[name] = {"summary": {"percent_covered": float(pct)},
                   "missing_lines": [int(n) for n in missing.split(",") if n]}
json.dump({"meta": {}, "files": files}, open(sys.argv[1], "w"))
PY
}

logged() { grep -qF -- "$1" "$STUB_LOG"; }
