# Vendor Compliance Guide: Directory Restructure

This guide describes how vendor repos need to update their `install.sh` scripts for compatibility with the git-vendored directory restructure.

## Overview

git-vendored is consolidating per-vendor dotdirs (`.pearls/`, `.dogfood/`, `.semver/`) into a structured layout under `.vendored/`:

```
.vendored/
  configs/<vendor>.json    # per-vendor config (replaces monolithic config.json)
  pkg/<vendor>/            # vendor-installed files (replaces dotdirs at repo root)
  manifests/<vendor>.files # file manifest
  manifests/<vendor>.version
```

## VENDOR_INSTALL_DIR Contract

### Environment Variable

The framework now passes `VENDOR_INSTALL_DIR` to vendor `install.sh` scripts:

| Env var | Value | When set |
|---------|-------|----------|
| `VENDOR_INSTALL_DIR` | `.vendored/pkg/<vendor>` | Non-dogfood vendors |

Dogfood vendors (`"dogfood": true` in config) do NOT receive `VENDOR_INSTALL_DIR` — they install directly into framework paths.

### Expected Behavior

When `VENDOR_INSTALL_DIR` is set, vendor `install.sh` SHOULD:

1. Install its primary files under `$VENDOR_INSTALL_DIR`
2. List all installed files in the manifest (at `$VENDOR_MANIFEST`)

When `VENDOR_INSTALL_DIR` is NOT set, vendor `install.sh` SHOULD:

1. Fall back to its original file layout (backwards compat)

### Files That Can Live Outside VENDOR_INSTALL_DIR

Some files must live in specific locations regardless of `VENDOR_INSTALL_DIR`:

- **GitHub workflows** → `.github/workflows/`
- **Git hooks** → `.vendored/hooks/` or `.git/hooks/`
- **Config files** the user edits → wherever they currently live

All files MUST appear in the manifest regardless of location.

## Code Examples

### Before (old layout)

```bash
#!/bin/bash
set -euo pipefail
VERSION="${VENDOR_REF:-${1:?}}"
REPO="${VENDOR_REPO:-owner/my-tool}"
INSTALLED_FILES=()

mkdir -p .my-tool
fetch_file "src/script.sh" ".my-tool/script.sh"
INSTALLED_FILES+=(".my-tool/script.sh")

fetch_file "src/lib.py" ".my-tool/lib.py"
INSTALLED_FILES+=(".my-tool/lib.py")

# Write manifest
printf '%s\n' "${INSTALLED_FILES[@]}" > "$VENDOR_MANIFEST"
```

### After (new layout with VENDOR_INSTALL_DIR)

```bash
#!/bin/bash
set -euo pipefail
VERSION="${VENDOR_REF:-${1:?}}"
REPO="${VENDOR_REPO:-owner/my-tool}"
INSTALLED_FILES=()

# Use VENDOR_INSTALL_DIR if set, otherwise fall back to original layout
INSTALL_DIR="${VENDOR_INSTALL_DIR:-.my-tool}"

mkdir -p "$INSTALL_DIR"
fetch_file "src/script.sh" "$INSTALL_DIR/script.sh"
INSTALLED_FILES+=("$INSTALL_DIR/script.sh")

fetch_file "src/lib.py" "$INSTALL_DIR/lib.py"
INSTALLED_FILES+=("$INSTALL_DIR/lib.py")

# Write manifest
printf '%s\n' "${INSTALLED_FILES[@]}" > "$VENDOR_MANIFEST"
```

The key change is a single line:
```bash
INSTALL_DIR="${VENDOR_INSTALL_DIR:-.my-tool}"
```

## Per-Vendor Config Schema

Each vendor gets its own config file at `.vendored/configs/<vendor>.json`:

```json
{
  "repo": "owner/repo",
  "install_branch": "chore/install-<name>",
  "private": false,
  "dogfood": false,
  "automerge": false,
  "protected": [".my-tool/**"],
  "allowed": [".my-tool/config.json"]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `repo` | string | yes | GitHub repository (`owner/name`) |
| `install_branch` | string | yes | Branch prefix for vendor update PRs |
| `private` | bool | no | Requires `VENDOR_PAT` secret for access |
| `dogfood` | bool | no | Excluded from `VENDOR_INSTALL_DIR` |
| `automerge` | bool | no | Auto-merge vendor update PRs |
| `protected` | list | yes | Glob patterns of protected files |
| `allowed` | list | no | Files users can edit (exceptions to protection) |

## What Vendor Repos Need to Change

1. **Read `VENDOR_INSTALL_DIR`** — use it as the base directory for installed files, with fallback to the original location
2. **Update manifest paths** — ensure manifest entries reflect the actual install location (which changes when `VENDOR_INSTALL_DIR` is set)
3. **No other changes required** — the framework handles config migration, directory creation, and cleanup

## Fallback Behavior

| Scenario | Behavior |
|----------|----------|
| `VENDOR_INSTALL_DIR` is set | Install files under that directory |
| `VENDOR_INSTALL_DIR` is not set | Install files in original location (e.g., `.my-tool/`) |
| Old framework + new install.sh | `VENDOR_INSTALL_DIR` not set → original layout |
| New framework + old install.sh | Files install in original location, framework still tracks via manifest |

Both old and new install.sh scripts work with both old and new framework versions.

## Migration Path for Consumer Repos

Consumer repos (repos that have vendors installed) migrate by:

1. **Update git-vendored** — run the latest bootstrap `install.sh` or let the automated PR update it
2. **Re-install vendors** — `python3 .vendored/install all --force`
3. **Or remove + re-install** — for a clean migration:
   ```bash
   python3 .vendored/remove my-vendor --force
   python3 .vendored/install owner/my-vendor
   ```

The framework handles config migration automatically: when it detects a monolithic `config.json` with a `vendors` key and no per-vendor configs, it splits the config into individual files.
