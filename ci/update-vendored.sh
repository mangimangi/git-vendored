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
# .vendored/install reads its token from GH_TOKEN/GITHUB_TOKEN. When the
# VENDOR_PAT secret is non-empty it becomes GH_TOKEN; otherwise GH_TOKEN and
# GITHUB_TOKEN are left as they are. No token is printed.
set -euo pipefail

ARGS=(.vendored/install "${CICD_INPUT_VENDOR:-all}"
      --version "${CICD_INPUT_VERSION:-latest}" --pr --deps=install)
if [ "${CICD_INPUT_PRIVATE:-}" = "true" ]; then
    ARGS+=(--private)
fi
if [ -n "${VENDOR_PAT:-}" ]; then
    export GH_TOKEN="$VENDOR_PAT"
fi
exec python3 "${ARGS[@]}"
