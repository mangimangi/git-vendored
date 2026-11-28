#!/usr/bin/env bats
# ci/validate.sh: hands the validate job's CICD_INPUT_ values to this
# repository's own validate as argv elements.

load ci-helpers

setup() {
    ci_setup
    unset CICD_INPUT_REPO CICD_INPUT_VERSION
    cat > "$BIN/python3" <<'STUB'
#!/bin/bash
line="python3"
for a in "$@"; do line+=" [$a]"; done
printf '%s\n' "$line" >> "$STUB_LOG"
printf 'argc=%s\n' "$#" >> "$STUB_LOG"
exit "${STUB_VALIDATE_STATUS:-0}"
STUB
    chmod +x "$BIN/python3"
}

run_validate() { run env PATH="$BIN" "$@" bash "$ROOT/ci/validate.sh"; }

@test "no repo: fails with a message and runs nothing" {
    run_validate
    [ "$status" -ne 0 ]
    [[ "$output" == *"no repository to validate"* ]]
    [[ "$output" == *'{"repo": "owner/repo"}'* ]]
    [ ! -s "$STUB_LOG" ]
}

@test "an empty repo fails the same way" {
    run_validate CICD_INPUT_REPO= CICD_INPUT_VERSION=v1.0.0
    [ "$status" -ne 0 ]
    [[ "$output" == *"no repository to validate"* ]]
    [ ! -s "$STUB_LOG" ]
}

@test "repo and version are passed as arguments" {
    run_validate CICD_INPUT_REPO=owner/tool CICD_INPUT_VERSION=v0.2.0
    [ "$status" -eq 0 ]
    [ "$(head -n 1 "$STUB_LOG")" = "python3 [validate] [owner/tool] [--version] [v0.2.0]" ]
}

@test "the version defaults to latest" {
    run_validate CICD_INPUT_REPO=owner/tool
    [ "$status" -eq 0 ]
    [ "$(head -n 1 "$STUB_LOG")" = "python3 [validate] [owner/tool] [--version] [latest]" ]
    : > "$STUB_LOG"
    run_validate CICD_INPUT_REPO=owner/tool CICD_INPUT_VERSION=
    [ "$(head -n 1 "$STUB_LOG")" = "python3 [validate] [owner/tool] [--version] [latest]" ]
}

@test "a hostile repo arrives verbatim as one argument and is not executed" {
    local evil='a b; touch pwned-semi $(touch pwned-subst)'
    run_validate CICD_INPUT_REPO="$evil"
    [ "$status" -eq 0 ]
    [ "$(head -n 1 "$STUB_LOG")" = "python3 [validate] [$evil] [--version] [latest]" ]
    logged "argc=4"
    [ ! -e pwned-semi ]
    [ ! -e pwned-subst ]
}

@test "validate's exit code is the step's exit code" {
    run_validate CICD_INPUT_REPO=owner/tool STUB_VALIDATE_STATUS=1
    [ "$status" -eq 1 ]
}
