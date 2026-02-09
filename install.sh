#!/bin/bash
# git-vendored/install.sh - Install or update git-vendored in a project
#
# Usage:
#   install.sh <version> [<repo>]
#
# Environment:
#   GH_TOKEN - Used for gh api downloads (required for private repos).
#              Falls back to curl for public repos when not set.
#
# Behavior:
#   - Always updates: .vendored/install, .vendored/check, .vendored/.version
#   - First install only: workflow templates to .github/workflows/ (skipped if present)
#   - Preserves .vendored/config.json (only creates if missing)
#   - Self-registers git-vendored as a vendor in .vendored/config.json
#
set -euo pipefail

VERSION="${1:?Usage: install.sh <version> [<repo>]}"
VENDORED_REPO="${2:-mangimangi/git-vendored}"

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
mkdir -p .vendored .github/workflows

# Download vendored scripts
echo "Downloading .vendored/install..."
fetch_file "vendored/install" ".vendored/install"
chmod +x .vendored/install

echo "Downloading .vendored/check..."
fetch_file "vendored/check" ".vendored/check"
chmod +x .vendored/check

# Write version
echo "$VERSION" > .vendored/.version
echo "Installed git-vendored v$VERSION"

# config.json - only create if missing (preserves user settings)
if [ ! -f .vendored/config.json ]; then
    fetch_file "templates/vendored/config.json" ".vendored/config.json"
    echo "Created .vendored/config.json"
fi

# Helper to install a workflow file (first install only)
install_workflow() {
    local workflow="$1"
    if [ -f ".github/workflows/$workflow" ]; then
        echo "Workflow .github/workflows/$workflow already exists, skipping"
        return
    fi
    if fetch_file "templates/github/workflows/$workflow" ".github/workflows/$workflow" 2>/dev/null; then
        echo "Installed .github/workflows/$workflow"
    fi
}

# Install workflow templates (skipped if already present)
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

echo ""
echo "Done! git-vendored v$VERSION installed."
