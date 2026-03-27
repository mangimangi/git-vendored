#!/bin/bash
# vendor-helpers.sh — Shell helper library for vendor install.sh scripts.
#
# Provides fetch_file and fetch_dir functions that handle download, auth,
# and manifest emission so vendor install scripts don't duplicate this logic.
#
# Usage in vendor install.sh:
#   source "$VENDOR_LIB" 2>/dev/null || {
#       fetch_file() { curl -fsSL ...; }  # inline fallback
#   }
#
# Environment (set by the framework before sourcing):
#   VENDOR_REPO      - owner/repo for API calls
#   VENDOR_REF       - Git ref to fetch files at
#   VENDOR_MANIFEST  - Path to write the file manifest to
#   VENDOR_INSTALL_DIR - Target directory for vendor files (optional)
#   GH_TOKEN         - Auth token (optional, required for private repos)
#   VENDOR_PAT       - Auth token for private repos (optional, overrides GH_TOKEN)
set -euo pipefail

# ── Internal helpers ─────────────────────────────────────────────────────

_vendor_auth_header() {
    local token="${VENDOR_PAT:-${GH_TOKEN:-}}"
    if [ -n "$token" ]; then
        echo "Authorization: token $token"
    fi
}

_vendor_download() {
    # Download a single file from the vendor repo.
    # Args: <repo_path> <dest_path>
    local repo_path="$1"
    local dest="$2"
    local repo="${VENDOR_REPO:?VENDOR_REPO not set}"
    local ref="${VENDOR_REF:?VENDOR_REF not set}"
    local auth_header
    auth_header="$(_vendor_auth_header)"

    mkdir -p "$(dirname "$dest")"

    # Try gh API first (handles private repos well), fall back to curl.
    # gh can fail due to bad creds, rate limits, or missing config — curl
    # is the reliable fallback.
    if [ -n "$auth_header" ] && command -v gh &>/dev/null; then
        local gh_content
        if gh_content=$(gh api "repos/$repo/contents/$repo_path?ref=$ref" --jq '.content' 2>/dev/null); then
            echo "$gh_content" | base64 -d > "$dest"
            return 0
        fi
    fi

    if [ -n "$auth_header" ]; then
        curl -fsSL -H "$auth_header" \
            "https://raw.githubusercontent.com/$repo/$ref/$repo_path" \
            -o "$dest"
    else
        curl -fsSL \
            "https://raw.githubusercontent.com/$repo/$ref/$repo_path" \
            -o "$dest"
    fi
}

_vendor_manifest_append() {
    # Append a path to the manifest file.
    local path="$1"
    local manifest="${VENDOR_MANIFEST:-}"
    if [ -n "$manifest" ]; then
        echo "$path" >> "$manifest"
    fi
}

# ── Public API ───────────────────────────────────────────────────────────

fetch_file() {
    # Download a single file from the vendor repo.
    #
    # Usage: fetch_file <repo_path> <local_path> [+x]
    #
    # Args:
    #   repo_path  - Path within the vendor repo (e.g., "prl.py")
    #   local_path - Destination path relative to repo root (e.g., "$VENDOR_INSTALL_DIR/prl.py")
    #   +x         - Optional: make the file executable after download
    #
    # Side effects:
    #   - Creates parent directories as needed
    #   - Appends local_path to $VENDOR_MANIFEST
    local repo_path="$1"
    local local_path="$2"
    local make_exec="${3:-}"

    _vendor_download "$repo_path" "$local_path"

    if [ "$make_exec" = "+x" ]; then
        chmod +x "$local_path"
    fi

    _vendor_manifest_append "$local_path"
}

fetch_dir() {
    # Download a directory tree from the vendor repo.
    #
    # Usage: fetch_dir <repo_path> <local_path>
    #
    # Args:
    #   repo_path  - Directory path within the vendor repo (e.g., "templates/hooks")
    #   local_path - Destination directory relative to repo root
    #
    # Side effects:
    #   - Creates the local directory tree
    #   - Appends each downloaded file to $VENDOR_MANIFEST
    #
    # Requires: gh CLI (uses GitHub API to list directory contents)
    local repo_path="$1"
    local local_path="$2"
    local repo="${VENDOR_REPO:?VENDOR_REPO not set}"
    local ref="${VENDOR_REF:?VENDOR_REF not set}"

    mkdir -p "$local_path"

    # Use gh API to list directory contents
    local entries
    entries=$(gh api "repos/$repo/contents/$repo_path?ref=$ref" \
        --jq '.[] | "\(.type)\t\(.path)\t\(.name)"' 2>/dev/null) || {
        echo "Error: failed to list directory $repo_path from $repo" >&2
        return 1
    }

    while IFS=$'\t' read -r type path name; do
        [ -z "$type" ] && continue
        if [ "$type" = "file" ]; then
            fetch_file "$path" "$local_path/$name"
        elif [ "$type" = "dir" ]; then
            fetch_dir "$path" "$local_path/$name"
        fi
    done <<< "$entries"
}
