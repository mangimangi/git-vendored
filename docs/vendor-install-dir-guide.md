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

Each vendor gets its own config file at `.vendored/configs/<vendor>.json`. The file contains two kinds of data:

- **`_vendor` key** — framework-owned registry fields. Written by `install`/`remove`, read by `check`. The underscore prefix signals "managed by the framework — don't edit."
- **Top-level keys** — project-owned config, opaque to the framework, read by the vendor tool itself.

```json
{
  "_vendor": {
    "repo": "owner/my-tool",
    "install_branch": "chore/install-my-tool",
    "automerge": true,
    "protected": [".vendored/pkg/my-tool/**"],
    "allowed": [".vendored/configs/my-tool.json"]
  },
  "setting": "value",
  "feature_flags": { "new_ui": true }
}
```

### `_vendor` Registry Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `repo` | string | yes | GitHub repository (`owner/name`) |
| `install_branch` | string | yes | Branch prefix for vendor update PRs |
| `private` | bool | no | Requires `VENDOR_PAT` secret for access |
| `dogfood` | bool | no | Excluded from `VENDOR_INSTALL_DIR` |
| `automerge` | bool | no | Auto-merge vendor update PRs |
| `protected` | list | yes | Glob patterns of protected files |
| `allowed` | list | no | Files users can edit (exceptions to protection) |

### Project Config (Top-Level Keys)

Top-level keys (everything except `_vendor`) belong to the vendor tool. The framework never reads, writes, or validates them. Examples:

```json
{
  "_vendor": { "repo": "owner/pearls", "install_branch": "chore/install-pearls" },
  "prefix": "gv",
  "docs": ["AGENTS.md", "README.md"],
  "models": { "implementer": "claude-opus-4-6" }
}
```

## Reading Project Config from Vendor Tools

Vendor tools should read their project config from `.vendored/configs/<vendor>.json`, filtering out the `_vendor` key. Fall back to the legacy dot-directory config if the vendored config doesn't exist.

### Python Example

```python
import json
from pathlib import Path

VENDORED_CONFIG = ".vendored/configs/my-tool.json"
LEGACY_CONFIG = ".my-tool/config.json"

def load_config():
    """Load project config, ignoring _vendor key."""
    # Try vendored config first
    path = Path(VENDORED_CONFIG)
    if not path.exists():
        path = Path(LEGACY_CONFIG)  # fallback
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    raw = json.loads(path.read_text())
    return {k: v for k, v in raw.items() if k != "_vendor"}
```

### Bash Example

```bash
# Read project config, filter out _vendor with jq
CONFIG_FILE=".vendored/configs/my-tool.json"
if [ ! -f "$CONFIG_FILE" ]; then
    CONFIG_FILE=".my-tool/config.json"  # fallback
fi
MY_SETTING=$(jq -r '.my_setting // empty' "$CONFIG_FILE")
```

### Backwards Compatibility

| Scenario | Behavior |
|----------|----------|
| `.vendored/configs/<vendor>.json` exists | Read from vendored config, ignore `_vendor` |
| `.vendored/configs/<vendor>.json` missing | Fall back to legacy `.<vendor>/config.json` |
| Pre-`_vendor` flat config (no `_vendor` key) | All keys treated as registry fields by framework |

## What Vendor Repos Need to Change

1. **Read `VENDOR_INSTALL_DIR`** — use it as the base directory for installed files, with fallback to the original location
2. **Update manifest paths** — ensure manifest entries reflect the actual install location (which changes when `VENDOR_INSTALL_DIR` is set)
3. **Update config loading** — read project config from `.vendored/configs/<vendor>.json` (ignoring `_vendor`), with fallback to the legacy dot-directory config
4. **No other changes required** — the framework handles config migration, directory creation, and cleanup

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

The framework handles config migration automatically:

1. **Registry migration**: When it detects a monolithic `config.json` with a `vendors` key and no per-vendor configs, it splits the config into individual files with `_vendor` namespace.
2. **Project config migration**: When legacy project configs exist at `.<vendor>/config.json` and a per-vendor config exists at `.vendored/configs/<vendor>.json`, it merges the project config into the top level of the vendored config and removes the legacy file.
