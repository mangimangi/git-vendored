#!/bin/bash
# ci/validate.sh - the step of git-vendored's own `validate` job: check
# whether a repository implements the vendor contract, with this
# repository's own `validate` (nothing is installed).
#
# git-cicd hands the job's declared inputs to the step as CICD_INPUT_
# variables: CICD_INPUT_REPO (a git URL, or owner/repo for github.com;
# required) and CICD_INPUT_VERSION
# (default latest). Each is one argv element, never part of a shell string.
set -euo pipefail

if [ -z "${CICD_INPUT_REPO:-}" ]; then
    echo "ci/validate.sh: no repository to validate; start the validate job with" \
         'inputs like {"repo": "owner/repo"}' >&2
    exit 2
fi
exec python3 validate "$CICD_INPUT_REPO" --version "${CICD_INPUT_VERSION:-latest}"
