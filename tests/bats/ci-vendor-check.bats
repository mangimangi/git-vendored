#!/usr/bin/env bats
# ci/vendor-check.sh: hands git-cicd's CICD_ facts to .vendored/check.

load ci-helpers

setup() {
    ci_setup
    cat > "$BIN/python3" <<'STUB'
#!/bin/bash
echo "python3 $* head_ref=${GITHUB_HEAD_REF-<unset>}" >> "$STUB_LOG"
exit "${STUB_CHECK_STATUS:-0}"
STUB
    chmod +x "$BIN/python3"
}

run_vendor_check() { run env PATH="$BIN" "$@" bash "$ROOT/ci/vendor-check.sh"; }

@test "no CICD facts: runs .vendored/check with no arguments" {
    run_vendor_check
    [ "$status" -eq 0 ]
    [ "$(cat "$STUB_LOG")" = "python3 .vendored/check head_ref=<unset>" ]
}

@test "CICD_BASE is passed as --base" {
    run_vendor_check CICD_BASE=abc123
    [ "$status" -eq 0 ]
    [ "$(cat "$STUB_LOG")" = "python3 .vendored/check --base abc123 head_ref=<unset>" ]
}

@test "CICD_SOURCE_BRANCH becomes GITHUB_HEAD_REF when that is unset" {
    run_vendor_check CICD_SOURCE_BRANCH=chore/install-tool
    [ "$status" -eq 0 ]
    logged "head_ref=chore/install-tool"
}

@test "an existing GITHUB_HEAD_REF is kept" {
    run_vendor_check CICD_SOURCE_BRANCH=other GITHUB_HEAD_REF=chore/install-tool
    [ "$status" -eq 0 ]
    logged "head_ref=chore/install-tool"
}

@test "an empty GITHUB_HEAD_REF is replaced by the source branch" {
    run_vendor_check CICD_SOURCE_BRANCH=feature GITHUB_HEAD_REF=
    [ "$status" -eq 0 ]
    logged "head_ref=feature"
}

@test "an empty CICD_SOURCE_BRANCH leaves GITHUB_HEAD_REF unset" {
    run_vendor_check CICD_SOURCE_BRANCH=
    [ "$status" -eq 0 ]
    logged "head_ref=<unset>"
}

@test "check's exit code is the step's exit code" {
    run_vendor_check STUB_CHECK_STATUS=1 CICD_BASE=main
    [ "$status" -eq 1 ]
}
