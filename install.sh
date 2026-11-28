#!/bin/bash
# git-vendored/install.sh - Install or update git-vendored in a project
#
# Usage:
#   install.sh <version> [<repo>]
#
# Environment (v2 contract — preferred):
#   VENDOR_REF       - Git ref (version) to install at. Falls back to $1.
#   VENDOR_REPO      - owner/repo for API calls. Falls back to $2 / default.
#   GH_TOKEN         - Used for gh api downloads (required for private repos).
#                      Falls back to curl for public repos when not set.
#   VENDOR_MANIFEST  - Path to write manifest of installed files (v2 contract).
#
# Behavior:
#   - Always updates: .vendored/install, .vendored/check, .vendored/remove
#   - Installs workflow templates in .github/workflows/ on the bootstrap
#     install only (no earlier git-vendored install), and not one whose job
#     the repository's git-cicd config already runs; an upgrade never adds one
#   - Preserves .vendored/config.json (only creates if missing)
#   - Writes manifest to $VENDOR_MANIFEST and .vendored/manifests/ (v2 contract)
#   - Cleans up old .vendored/add and .vendored/update (merged into install)
#   - Cleans up deprecated .vendored/.version (replaced by manifests)
#
set -euo pipefail

# v2 contract: read env vars, fall back to positional args for backwards compat
VERSION="${VENDOR_REF:-${1:?Usage: install.sh <version> [<repo>]}}"
VERSION="${VERSION#v}"  # strip v prefix if present (VENDOR_REF includes it)
VENDORED_REPO="${VENDOR_REPO:-${2:-mangimangi/git-vendored}}"

# Track installed files for manifest
INSTALLED_FILES=()

# File download helper - uses gh api when GH_TOKEN is set, curl otherwise
fetch_file() {
    local repo_path="$1"
    local dest="$2"
    local ref="${3:-v$VERSION}"

    if [ -n "${GH_TOKEN:-}" ] && command -v gh &>/dev/null; then
        gh api "repos/$VENDORED_REPO/contents/$repo_path?ref=$ref" --jq '.content' | base64 -d > "$dest"
    else
        local base="https://raw.githubusercontent.com/$VENDORED_REPO"
        curl -fsSL "$base/$ref/$repo_path" -o "$dest"
    fi
}

echo "Installing git-vendored v$VERSION from $VENDORED_REPO"

# Bootstrap or upgrade? Decided before anything is written: any of these is
# left by an earlier git-vendored install.
EARLIER_INSTALL=""
for marker in .vendored/manifests/git-vendored.version \
        .vendored/manifests/git-vendored.files .vendored/.version .vendored/install; do
    if [ -e "$marker" ]; then
        EARLIER_INSTALL="$marker"
        break
    fi
done

# Create directories
mkdir -p .vendored .vendored/manifests .vendored/configs .vendored/pkg .vendored/lib .github/workflows

# Download vendored scripts
echo "Downloading .vendored/install..."
fetch_file "templates/install" ".vendored/install"
chmod +x .vendored/install
INSTALLED_FILES+=(".vendored/install")

echo "Downloading .vendored/check..."
fetch_file "templates/check" ".vendored/check"
chmod +x .vendored/check
INSTALLED_FILES+=(".vendored/check")

echo "Downloading .vendored/remove..."
fetch_file "templates/remove" ".vendored/remove"
chmod +x .vendored/remove
INSTALLED_FILES+=(".vendored/remove")

# Download vendor helper library
echo "Downloading .vendored/feedback..."
fetch_file "templates/feedback" ".vendored/feedback"
chmod +x .vendored/feedback
INSTALLED_FILES+=(".vendored/feedback")

echo "Downloading .vendored/audit..."
fetch_file "templates/audit" ".vendored/audit"
chmod +x .vendored/audit
INSTALLED_FILES+=(".vendored/audit")

echo "Downloading .vendored/lib/vendor-helpers.sh..."
fetch_file "templates/lib/vendor-helpers.sh" ".vendored/lib/vendor-helpers.sh"
chmod +x .vendored/lib/vendor-helpers.sh
INSTALLED_FILES+=(".vendored/lib/vendor-helpers.sh")

# Clean up old add/update scripts (merged into install)
rm -f .vendored/add .vendored/update

# Clean up deprecated .vendored/.version (replaced by manifests/<vendor>.version)
rm -f .vendored/.version

# config.json - only create if missing (preserves user settings)
if [ ! -f .vendored/config.json ]; then
    fetch_file "templates/config.json" ".vendored/config.json"
    echo "Created .vendored/config.json"
fi

# Workflow templates. A workflow that is present stays (and is listed in the
# manifest). One that is absent is installed only on the bootstrap install:
# on an upgrade, absent means the repository removed it on purpose, and it
# is not installed either when a git-cicd job already runs the command it
# exists for (GITHUB_TOKEN cannot push workflow files anyway).
GIT_CICD_CONFIG=".vendored/configs/git-cicd.json"

# git_cicd_job_running <command>: print the name of a job in the git-cicd
# config with a step that names <command> or runs a script in the repository
# that does; print nothing (and succeed) when there is none.
git_cicd_job_running() {
    [ -f "$GIT_CICD_CONFIG" ] || return 0
    command -v python3 &>/dev/null || return 0
    python3 - "$GIT_CICD_CONFIG" "$1" <<'PY' 2>/dev/null || true
import json, os, re, shlex, sys
config_path, command = sys.argv[1], sys.argv[2]
pattern = re.compile(r"(?<![\w./-])(\./)?" + re.escape(command) + r"(?![\w./-])")
with open(config_path) as f:
    jobs = json.load(f).get("jobs", {})
for name, job in jobs.items():
    for step in job.get("steps", []):
        words = step if isinstance(step, list) else shlex.split(str(step))
        text = " ".join(str(w) for w in words)
        if pattern.search(text):
            print(name)
            sys.exit(0)
        script = str(words[0]) if words else ""
        if script and os.path.isfile(script):
            with open(script, errors="replace") as s:
                if pattern.search(s.read()):
                    print(name)
                    sys.exit(0)
PY
}

install_workflow() {
    local workflow="$1" command="$2" job
    if [ -f ".github/workflows/$workflow" ]; then
        echo "Workflow .github/workflows/$workflow already exists, skipping"
        INSTALLED_FILES+=(".github/workflows/$workflow")
        return
    fi
    if [ -n "$EARLIER_INSTALL" ]; then
        echo "Not installing .github/workflows/$workflow: this is an upgrade ($EARLIER_INSTALL exists) and the repository has no such workflow"
        return
    fi
    job="$(git_cicd_job_running "$command")"
    if [ -n "$job" ]; then
        echo "Not installing .github/workflows/$workflow: git-cicd job '$job' in $GIT_CICD_CONFIG already runs $command"
        return
    fi
    if fetch_file "templates/github/workflows/$workflow" ".github/workflows/$workflow" 2>/dev/null; then
        echo "Installed .github/workflows/$workflow"
        INSTALLED_FILES+=(".github/workflows/$workflow")
    else
        # gh path's redirect leaves an empty file behind on failure
        rm -f ".github/workflows/$workflow"
    fi
}

install_workflow "install-vendored.yml" ".vendored/install"
install_workflow "check-vendor.yml" ".vendored/check"

# v2 contract: install.sh does NOT self-register in config.json.
# The framework handles registration after reading the manifest.

# Write manifest (v2 contract)
write_manifest() {
    # Write to $VENDOR_MANIFEST if set (framework reads this)
    if [ -n "${VENDOR_MANIFEST:-}" ]; then
        printf '%s\n' "${INSTALLED_FILES[@]}" > "$VENDOR_MANIFEST"
    fi

    # Also write to .vendored/manifests/ for direct storage
    printf '%s\n' "${INSTALLED_FILES[@]}" | sort > .vendored/manifests/git-vendored.files
    echo "$VERSION" > .vendored/manifests/git-vendored.version
}

write_manifest

echo ""
echo "Done! git-vendored v$VERSION installed."
