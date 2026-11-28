#!/bin/bash
# ci/vendor-check.sh - the step of git-vendored's own `vendor-check` job:
# run .vendored/check against the change's base.
#
# git-cicd hands the change's facts to the step as CICD_ variables. The base
# commit is passed as --base, and the source branch reaches .vendored/check as
# GITHUB_HEAD_REF (which it reads to skip vendor install branches) when the
# platform has not set it already. templates/check reads CICD_SOURCE_BRANCH
# itself; this copy becomes unnecessary once the installed .vendored/check is
# a release that does (git-vendored installed into itself).
set -euo pipefail

if [ -n "${CICD_SOURCE_BRANCH:-}" ] && [ -z "${GITHUB_HEAD_REF:-}" ]; then
    export GITHUB_HEAD_REF="$CICD_SOURCE_BRANCH"
fi
ARGS=()
if [ -n "${CICD_BASE:-}" ]; then
    ARGS=(--base "$CICD_BASE")
fi
exec python3 .vendored/check "${ARGS[@]}"
