#!/bin/bash
# git-vendored/install.sh - Install or update git-vendored in a project
#
# Usage:
#   install.sh <version> [<repo>]
#
# Environment:
#   GH_TOKEN         - Used for gh api downloads (required for private repos).
#                      Falls back to curl for public repos when not set.
#   VENDOR_MANIFEST  - Path to write manifest of installed files (v2 contract).
#
# Behavior:
#   - Always updates: .vendored/install, .vendored/check, .vendored/remove,
#     .vendored/hooks/pre-commit, .vendored/.version
#   - Always updates: workflow templates in .github/workflows/
#   - Preserves .vendored/config.json (only creates if missing)
#   - Self-registers git-vendored as a vendor in .vendored/config.json
#   - Writes manifest to $VENDOR_MANIFEST and .vendored/manifests/ (v2 contract)
#   - Cleans up old .vendored/add and .vendored/update (merged into install)
#
set -euo pipefail

VERSION="${1:?Usage: install.sh <version> [<repo>]}"
VENDORED_REPO="${2:-mangimangi/git-vendored}"

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

# Create directories
mkdir -p .vendored .vendored/hooks .vendored/manifests .github/workflows

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

# Clean up old add/update scripts (merged into install)
rm -f .vendored/add .vendored/update

echo "Downloading .vendored/hooks/pre-commit..."
fetch_file "templates/hooks/pre-commit" ".vendored/hooks/pre-commit"
chmod +x .vendored/hooks/pre-commit
INSTALLED_FILES+=(".vendored/hooks/pre-commit")

# Write version
echo "$VERSION" > .vendored/.version
echo "Installed git-vendored v$VERSION"
INSTALLED_FILES+=(".vendored/.version")

# config.json - only create if missing (preserves user settings)
if [ ! -f .vendored/config.json ]; then
    fetch_file "templates/config.json" ".vendored/config.json"
    echo "Created .vendored/config.json"
fi

# Install/update workflow templates (always updated to propagate changes)
install_workflow() {
    local workflow="$1"
    if fetch_file "templates/github/workflows/$workflow" ".github/workflows/$workflow" 2>/dev/null; then
        echo "Installed .github/workflows/$workflow"
        INSTALLED_FILES+=(".github/workflows/$workflow")
    fi
}

install_workflow "install-vendored.yml"
install_workflow "check-vendor.yml"

# Self-register git-vendored as a vendor in config.json
python3 -c "
import json
with open('.vendored/config.json') as f:
    config = json.load(f)
config.setdefault('vendors', {})
config['vendors']['git-vendored'] = {
    'repo': '$VENDORED_REPO',
    'install_branch': 'chore/install-git-vendored',
    'protected': [
        '.vendored/**',
        '.github/workflows/install-vendored.yml',
        '.github/workflows/check-vendor.yml'
    ],
    'allowed': ['.vendored/config.json', '.vendored/.version']
}
with open('.vendored/config.json', 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
"

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
