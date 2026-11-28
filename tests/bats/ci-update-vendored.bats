#!/usr/bin/env bats
# ci/update-vendored.sh: hands the update-vendored job's CICD_INPUT_ values
# to the installed .vendored/install as argv elements, with GH_TOKEN from
# CICD_WRITE_TOKEN, else the deprecated VENDOR_PAT, when one is set.

load ci-helpers

setup() {
    ci_setup
    unset CICD_INPUT_VENDOR CICD_INPUT_VERSION CICD_INPUT_PRIVATE
    # The python3 stub logs each argument in [brackets], one line per call,
    # then the token variables on a line of their own.
    cat > "$BIN/python3" <<'STUB'
#!/bin/bash
line="python3"
for a in "$@"; do line+=" [$a]"; done
printf '%s\n' "$line" >> "$STUB_LOG"
printf 'argc=%s\n' "$#" >> "$STUB_LOG"
printf 'gh_token=%s github_token=%s\n' "${GH_TOKEN-<unset>}" "${GITHUB_TOKEN-<unset>}" >> "$STUB_LOG"
exit "${STUB_INSTALL_STATUS:-0}"
STUB
    chmod +x "$BIN/python3"
}

run_update() { run env PATH="$BIN" "$@" bash "$ROOT/ci/update-vendored.sh"; }

first_line() { head -n 1 "$STUB_LOG"; }

@test "no inputs (a cron run): all vendors, latest, --pr --deps=install" {
    run_update
    [ "$status" -eq 0 ]
    [ "$(first_line)" = "python3 [.vendored/install] [all] [--version] [latest] [--pr] [--deps=install]" ]
}

@test "empty inputs get the defaults" {
    run_update CICD_INPUT_VENDOR= CICD_INPUT_VERSION= CICD_INPUT_PRIVATE=
    [ "$status" -eq 0 ]
    [ "$(first_line)" = "python3 [.vendored/install] [all] [--version] [latest] [--pr] [--deps=install]" ]
}

@test "vendor and version inputs are passed as arguments" {
    run_update CICD_INPUT_VENDOR=git-cicd CICD_INPUT_VERSION=v0.0.5 CICD_INPUT_PRIVATE=false
    [ "$status" -eq 0 ]
    [ "$(first_line)" = "python3 [.vendored/install] [git-cicd] [--version] [v0.0.5] [--pr] [--deps=install]" ]
}

@test "private true adds --private" {
    run_update CICD_INPUT_VENDOR=git-cicd CICD_INPUT_PRIVATE=true
    [ "$status" -eq 0 ]
    [ "$(first_line)" = "python3 [.vendored/install] [git-cicd] [--version] [latest] [--pr] [--deps=install] [--private]" ]
}

@test "private other than true does not add --private" {
    local value
    for value in false TRUE yes 1; do
        : > "$STUB_LOG"
        run_update CICD_INPUT_PRIVATE="$value"
        [ "$status" -eq 0 ]
        ! logged "[--private]" || false
    done
}

@test "a hostile input arrives verbatim as one argument and is not executed" {
    local evil='x y; touch pwned-semi $(touch pwned-subst) `touch pwned-tick` && echo hi'
    run_update CICD_INPUT_VENDOR="$evil" CICD_INPUT_VERSION="$evil"
    [ "$status" -eq 0 ]
    [ "$(first_line)" = "python3 [.vendored/install] [$evil] [--version] [$evil] [--pr] [--deps=install]" ]
    logged "argc=6"
    [ ! -e pwned-semi ]
    [ ! -e pwned-subst ]
    [ ! -e pwned-tick ]
    [ ! -e "$ROOT/pwned-semi" ]
    [ ! -e "$ROOT/pwned-subst" ]
    [ ! -e "$ROOT/pwned-tick" ]
}

@test "CICD_WRITE_TOKEN becomes GH_TOKEN, over VENDOR_PAT, and is never echoed" {
    run_update CICD_WRITE_TOKEN=secret-write-value VENDOR_PAT=secret-pat-value \
        GITHUB_TOKEN=workflow-token
    [ "$status" -eq 0 ]
    logged "gh_token=secret-write-value github_token=workflow-token"
    [[ "$output" != *secret-write-value* ]]
    [[ "$output" != *secret-pat-value* ]]
}

@test "an empty CICD_WRITE_TOKEN falls back to VENDOR_PAT" {
    run_update CICD_WRITE_TOKEN= VENDOR_PAT=secret-pat-value GITHUB_TOKEN=workflow-token
    [ "$status" -eq 0 ]
    logged "gh_token=secret-pat-value github_token=workflow-token"
}

@test "VENDOR_PAT alone becomes GH_TOKEN and is never echoed" {
    run_update VENDOR_PAT=secret-pat-value GITHUB_TOKEN=workflow-token
    [ "$status" -eq 0 ]
    logged "gh_token=secret-pat-value github_token=workflow-token"
    [[ "$output" != *secret-pat-value* ]]
}

@test "without a write token, GH_TOKEN and GITHUB_TOKEN are left as they are" {
    run_update GH_TOKEN=gh-token GITHUB_TOKEN=workflow-token
    [ "$status" -eq 0 ]
    logged "gh_token=gh-token github_token=workflow-token"
}

@test "an empty VENDOR_PAT leaves GH_TOKEN unset" {
    run_update VENDOR_PAT= GITHUB_TOKEN=workflow-token
    [ "$status" -eq 0 ]
    logged "gh_token=<unset> github_token=workflow-token"
}

@test "install's exit code is the step's exit code" {
    run_update STUB_INSTALL_STATUS=3
    [ "$status" -eq 3 ]
}

@test "ci_setup removes token variables the outer environment holds" {
    export CICD_WRITE_TOKEN=outer-fake-write CICD_READ_TOKEN=outer-fake-read
    export VENDOR_PAT=outer-fake-pat GH_TOKEN=outer-fake-gh GITHUB_TOKEN=outer-fake-gt
    BATS_TEST_TMPDIR="$BATS_TEST_TMPDIR/again" ci_setup
    [ -z "${CICD_WRITE_TOKEN+set}" ]
    [ -z "${CICD_READ_TOKEN+set}" ]
    [ -z "${VENDOR_PAT+set}" ]
    [ -z "${GH_TOKEN+set}" ]
    [ -z "${GITHUB_TOKEN+set}" ]
}
