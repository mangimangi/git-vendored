#!/usr/bin/env bats
# ci/test.sh: pytest under coverage, the per-file 99% check, then bats.

load ci-helpers

setup() {
    ci_setup
    VENV="$XDG_CACHE_HOME/git-vendored-ci/venv-3.8"
    export STUB_SITE="$BATS_TEST_TMPDIR/site"
    export STUB_COVERAGE_JSON="$BATS_TEST_TMPDIR/coverage.json"
    coverage_json "$STUB_COVERAGE_JSON" "templates/check=100:" "validate=99.5:12"
    fake_python "$VENV/bin/python"
    stub "$BIN/bats" 0 "Bats 0.0-stub"
}

run_test_sh() { run env PATH="$BIN" "$@" bash "$ROOT/ci/test.sh"; }

@test "with the setup venv: runs coverage, pytest, report, the per-file check and bats" {
    run_test_sh
    [ "$status" -eq 0 ]
    [[ "$output" == *"Python 3.8.99"* ]]
    [[ "$output" == *"PYTEST-OUTPUT"* ]]
    [[ "$output" == *"REPORT-OUTPUT"* ]]
    [[ "$output" != *"below"* ]]
    run grep -o "^python -m coverage [a-z]*\|^bats .*" "$STUB_LOG"
    [ "${lines[0]}" = "python -m coverage erase" ]
    [ "${lines[1]}" = "python -m coverage run" ]
    [ "${lines[2]}" = "python -m coverage combine" ]
    [ "${lines[3]}" = "python -m coverage report" ]
    [ "${lines[4]}" = "python -m coverage json" ]
    [ "${lines[5]}" = "bats --version" ]
    [ "${lines[6]}" = "bats tests/bats/" ]
    logged "python -m coverage run -m pytest tests/ -v"
}

@test "exports COVERAGE_PROCESS_START and GIT_VENDORED_ROOT for subprocess runs" {
    run_test_sh
    [ "$status" -eq 0 ]
    logged "env COVERAGE_PROCESS_START=$WORK/pyproject.toml GIT_VENDORED_ROOT=$WORK"
}

@test "without the venv: falls back to a python3 that has pytest, pyyaml and coverage" {
    rm -rf "$VENV"
    fake_python "$BIN/python3"
    run_test_sh
    [ "$status" -eq 0 ]
    logged "python3 -m coverage run -m pytest tests/ -v"
}

@test "without the venv or the modules: error pointing to --setup, exit 1" {
    rm -rf "$VENV"
    fake_python "$BIN/python3"
    run_test_sh STUB_IMPORT_STATUS=1
    [ "$status" -eq 1 ]
    [[ "$output" == *"ci/test.sh: pytest, pyyaml or coverage is not installed; run: .vendored/pkg/git-cicd/git-cicd check --setup"* ]]
    ! logged "coverage run"
}

@test "a venv without coverage: error, exit 1" {
    run_test_sh STUB_COVERAGE_STATUS=1
    [ "$status" -eq 1 ]
    [[ "$output" == *"ci/test.sh: coverage is not installed in $VENV/bin/python; run: .vendored/pkg/git-cicd/git-cicd check --setup"* ]]
    ! logged "coverage run"
}

@test "no subprocess hook: warns that subprocess runs are not counted, then runs" {
    run_test_sh STUB_HOOK_STATUS=1
    [ "$status" -eq 0 ]
    [[ "$output" == *"ci/test.sh: warning: the coverage subprocess hook is not installed for $VENV/bin/python,"* ]]
    [[ "$output" == *"so subprocess runs are not counted and the figures will differ from CI"* ]]
    logged "coverage run"
}

@test "failing tests fail the step, after the report and bats still run" {
    run_test_sh STUB_PYTEST_STATUS=1
    [ "$status" -eq 1 ]
    [[ "$output" == *"REPORT-OUTPUT"* ]]
    logged "bats tests/bats/"
}

@test "total below fail_under (report exits non-zero) fails the step" {
    run_test_sh STUB_REPORT_STATUS=2
    [ "$status" -eq 2 ]
    logged "bats tests/bats/"
}

@test "one file below the threshold fails, naming it, its figure and missing line ranges" {
    coverage_json "$STUB_COVERAGE_JSON" "templates/check=98.69:3,4,5,9,165" "validate=100:"
    run_test_sh
    [ "$status" -eq 1 ]
    [[ "$output" == *"ci/test.sh: templates/check is at 98.69% line coverage, below 99%; missing lines: 3-5, 9, 165"* ]]
    [[ "$output" != *"validate is at"* ]]
    [[ "$output" == *"ci/test.sh: add tests for those lines in this pull request (see Coverage in AGENTS.md)"* ]]
    [[ "$output" == *"REPORT-OUTPUT"* ]]
}

@test "the per-file threshold is fail_under from pyproject.toml" {
    write_pyproject ">=3.8" 95
    coverage_json "$STUB_COVERAGE_JSON" "templates/check=96:1" "validate=94:2"
    run_test_sh
    [ "$status" -eq 1 ]
    [[ "$output" == *"validate is at 94.00% line coverage, below 95%"* ]]
    [[ "$output" != *"templates/check is at"* ]]
}

@test "without fail_under the per-file threshold is 99" {
    write_pyproject ">=3.8"
    coverage_json "$STUB_COVERAGE_JSON" "validate=98.9:2"
    run_test_sh
    [ "$status" -eq 1 ]
    [[ "$output" == *"below 99%"* ]]
}

@test "the venv is found from requires-python" {
    write_pyproject ">=3.11" 99
    rm -rf "$VENV"
    fake_python "$XDG_CACHE_HOME/git-vendored-ci/venv-3.11/bin/python"
    run_test_sh
    [ "$status" -eq 0 ]
    logged "python -m coverage run"
}

@test "failing bats tests fail the step" {
    cat > "$BIN/bats" <<'STUB'
#!/bin/bash
echo "bats $*" >> "$STUB_LOG"
[ "$1" = "--version" ] && exit 0
exit 1
STUB
    run_test_sh
    [ "$status" -eq 1 ]
    logged "bats tests/bats/"
}

@test "bats from the setup cache when none is on PATH" {
    rm "$BIN/bats"
    stub "$XDG_CACHE_HOME/git-vendored-ci/bats-1.11.1/bin/bats"
    run_test_sh
    [ "$status" -eq 0 ]
    logged "bats tests/bats/"
}

@test "no bats at all: error pointing to --setup, exit 1" {
    rm "$BIN/bats"
    run_test_sh
    [ "$status" -eq 1 ]
    [[ "$output" == *"ci/test.sh: bats is not installed; run: .vendored/pkg/git-cicd/git-cicd check --setup"* ]]
    ! logged "coverage run"
}
