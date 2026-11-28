#!/bin/bash
# ci/update-vendored.sh - the step of git-vendored's own `update-vendored`
# job: install or update vendors with the installed .vendored/install and
# open a pull request.
#
# git-cicd hands the job's declared inputs to the step as CICD_INPUT_
# variables: CICD_INPUT_VENDOR (default all), CICD_INPUT_VERSION (default
# latest) and CICD_INPUT_PRIVATE ("true" adds --private). A cron run gets the
# defaults. Each input is one element of an argv array, never part of a shell
# string, so a value is passed verbatim and never executed.
#
# .vendored/install reads its token from GH_TOKEN/GITHUB_TOKEN (and its write
# token from CICD_WRITE_TOKEN, else the deprecated VENDOR_PAT). The first of
# the CICD_WRITE_TOKEN and VENDOR_PAT secrets that is non-empty becomes
# GH_TOKEN; otherwise GH_TOKEN and GITHUB_TOKEN are left as they are. No
# token is printed.
set -euo pipefail

ARGS=(.vendored/install "${CICD_INPUT_VENDOR:-all}"
      --version "${CICD_INPUT_VERSION:-latest}" --pr --deps=install)
if [ "${CICD_INPUT_PRIVATE:-}" = "true" ]; then
    ARGS+=(--private)
fi
WRITE_TOKEN="${CICD_WRITE_TOKEN:-${VENDOR_PAT:-}}"
if [ -n "$WRITE_TOKEN" ]; then
    export GH_TOKEN="$WRITE_TOKEN"
fi
unset WRITE_TOKEN
exec python3 "${ARGS[@]}"
