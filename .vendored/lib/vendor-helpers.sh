#!/bin/bash
# vendor-helpers.sh — Shell helper library for vendor install.sh scripts.
#
# Provides fetch_file and fetch_dir functions that handle download, auth,
# and manifest emission so vendor install scripts don't duplicate this logic.
#
# Two modes:
#   checkout mode - VENDOR_CHECKOUT is set to a directory (the framework
#                   fetched the vendor with git at VENDOR_REF): files are
#                   copied from it. No gh, no curl, no token.
#   fallback mode - VENDOR_CHECKOUT unset or empty (an installer run by hand,
#                   or an older framework): gh api, then curl on
#                   raw.githubusercontent.com, as before.
# Either way a file gets its content only: its mode is the umask default,
# and executable only through `fetch_file ... +x`.
#
# Usage in vendor install.sh:
#   source "$VENDOR_LIB" 2>/dev/null || {
#       fetch_file() { curl -fsSL ...; }  # inline fallback
#   }
#
# Environment (set by the framework before sourcing):
#   VENDOR_CHECKOUT  - Absolute path of the vendor checkout at VENDOR_REF
#                      (optional; selects checkout mode)
#   VENDOR_REPO      - The vendor's repo as configured (owner/repo in
#                      fallback mode)
#   VENDOR_REF       - Git ref to fetch files at
#   VENDOR_MANIFEST  - Path to write the file manifest to
#   VENDOR_INSTALL_DIR - Target directory for vendor files (optional)
#   CICD_READ_TOKEN  - Token that reads private repos (optional; first choice)
#   CICD_WRITE_TOKEN - Token that may also write (optional; second choice)
#   VENDOR_PAT       - Deprecated old name (optional; third choice)
#   GH_TOKEN         - Auth token (optional; used when none of the above is set)
set -euo pipefail

# ── Internal helpers ─────────────────────────────────────────────────────

_vendor_auth_header() {
    local token="${CICD_READ_TOKEN:-${CICD_WRITE_TOKEN:-${VENDOR_PAT:-${GH_TOKEN:-}}}}"
    if [ -n "$token" ]; then
        echo "Authorization: token $token"
    fi
}

_vendor_checkout_mode() {
    # True when the framework gave a vendor checkout to copy from.
    [ -n "${VENDOR_CHECKOUT:-}" ] && [ -d "$VENDOR_CHECKOUT" ]
}

_vendor_copy() {
    # Copy a single file from the vendor checkout: content only, so the
    # mode is what a download gives, not the checkout's.
    # Args: <repo_path> <dest_path>
    local src="$VENDOR_CHECKOUT/$1"
    local dest="$2"
    if [ -L "$src" ] || [ ! -f "$src" ]; then
        echo "Error: $1 not found in the vendor checkout" >&2
        return 1
    fi
    mkdir -p "$(dirname "$dest")"
    cat "$src" > "$dest"
}

_vendor_list_dir() {
    # Print a directory's entries (dotfiles too), NUL-separated, with bash
    # globbing only (no find or ls needed).
    local restore entry
    restore="$(shopt -p nullglob dotglob || true)"
    shopt -s nullglob dotglob
    for entry in "$1"/*; do
        printf '%s\0' "$entry"
    done
    eval "$restore"
}

_vendor_is_empty_dir() {
    local restore
    restore="$(shopt -p nullglob dotglob || true)"
    shopt -s nullglob dotglob
    local entries=("$1"/*)
    eval "$restore"
    [ "${#entries[@]}" -eq 0 ]
}

_vendor_download() {
    # Download a single file from the vendor repo.
    # Args: <repo_path> <dest_path>
    local repo_path="$1"
    local dest="$2"

    if _vendor_checkout_mode; then
        _vendor_copy "$repo_path" "$dest"
        return
    fi

    # Fallback mode (no checkout given): GitHub API, then raw.githubusercontent.com
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

    # Explicit: set -e does not apply when the caller tests the result.
    _vendor_download "$repo_path" "$local_path" || return

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
    # Checkout mode walks $VENDOR_CHECKOUT/<repo_path>: regular files are
    # fetched, directories recursed into; .git, symlinks and submodules are
    # skipped (the API mode handles only files and directories).
    # Fallback mode requires the gh CLI (GitHub API lists the directory).
    local repo_path="$1"
    local local_path="$2"

    if _vendor_checkout_mode; then
        local src="$VENDOR_CHECKOUT/$repo_path"
        if [ -L "$src" ] || [ ! -d "$src" ]; then
            echo "Error: failed to list directory $repo_path from ${VENDOR_REPO:-the vendor checkout}" >&2
            return 1
        fi
        mkdir -p "$local_path"
        local entry name
        while IFS= read -r -d '' entry; do
            name="${entry##*/}"
            [ "$name" = ".git" ] && continue
            [ -L "$entry" ] && continue
            if [ -d "$entry" ]; then
                # A submodule is a gitlink: initialized it holds .git,
                # uninitialized it is empty (git tracks no empty directory).
                [ -e "$entry/.git" ] && continue
                _vendor_is_empty_dir "$entry" && continue
                fetch_dir "${repo_path%/}/$name" "$local_path/$name" || return 1
            elif [ -f "$entry" ]; then
                fetch_file "${repo_path%/}/$name" "$local_path/$name" || return 1
            fi
        done < <(_vendor_list_dir "$src")
        return 0
    fi

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
