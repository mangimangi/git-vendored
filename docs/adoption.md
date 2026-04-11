# Adoption Guide: gv-7a53 Framework Features

This guide covers how vendor repos can adopt the framework features from the
gv-7a53 epic (Codex Support & Vendor DX Improvements).

---

## 1. `$VENDOR_LIB` -- Shell Helper Library

Vendor `install.sh` scripts can source the framework's helper library to get
`fetch_file` and `fetch_dir` without reimplementing download/auth/manifest
logic.

**Pattern with inline fallback** (for compatibility when the framework is older
or absent):

```bash
source "$VENDOR_LIB" 2>/dev/null || {
    fetch_file() {
        local src="$1" dst="$2"
        curl -fsSL "https://raw.githubusercontent.com/$VENDOR_REPO/$VENDOR_REF/$src" -o "$dst"
        [ "${3:-}" = "+x" ] && chmod +x "$dst"
        echo "$dst" >> "${VENDOR_MANIFEST:-/dev/null}"
    }
}
```

### `fetch_file`

```
fetch_file <repo_path> <local_path> [+x]
```

- `repo_path` -- path within the vendor repo (e.g. `scripts/prl.py`)
- `local_path` -- destination path relative to repo root
- `+x` -- optional; makes the file executable after download

Side effects: creates parent directories, appends `local_path` to
`$VENDOR_MANIFEST`.

### `fetch_dir`

```
fetch_dir <repo_path> <local_path>
```

- `repo_path` -- directory path within the vendor repo
- `local_path` -- destination directory relative to repo root

Recursively downloads the directory tree. **Requires the `gh` CLI** (uses the
GitHub API to list directory contents).

### Auth

Both functions respect `$VENDOR_PAT` (checked first) and `$GH_TOKEN` for
private repo access. No additional auth setup is needed in vendor scripts.

### Environment variables

These are set by the framework before the vendor `install.sh` runs:

| Variable             | Description                            |
|----------------------|----------------------------------------|
| `VENDOR_REPO`        | `owner/repo` for API calls             |
| `VENDOR_REF`         | Git ref to fetch files at              |
| `VENDOR_MANIFEST`    | Path to the file manifest              |
| `VENDOR_INSTALL_DIR` | Target directory for vendor files      |
| `GH_TOKEN`           | Auth token (optional)                  |
| `VENDOR_PAT`         | Auth token override for private repos  |

---

## 2. Vendor Support Config

Vendors can add an optional `support` key to their config for richer feedback
and bug-reporting info.

### Schema

```json
{
  "repo": "owner/repo",
  "support": {
    "issues": "https://github.com/owner/repo/issues",
    "instructions": "Include your .vendored/manifests/<vendor>.version in bug reports.",
    "labels": ["vendored", "bug"]
  }
}
```

All fields inside `support` are optional:

- `issues` -- URL for filing issues. If absent, derived automatically from the
  `repo` field as `https://github.com/{repo}/issues`.
- `instructions` -- Free-text guidance shown to users when they run feedback.
- `labels` -- Suggested labels for issue filing.

### Usage

The `.vendored/feedback` command surfaces this info:

```
python3 .vendored/feedback            # all installed vendors
python3 .vendored/feedback <vendor>   # specific vendor
```

---

## 3. Session-Hook Orchestration (Removed)

Session-hook orchestration (`vendored-session.sh`, `--setup-hooks`, agent
session hooks in `.claude/settings.json` and `.codex/config.toml`) was removed
in phase 4.5. Target repos now use the image-baked model where health checks
run via `session.sh` in the medici image.

git-vendored's scope is now limited to:
- Host-side tool installs (git-semver, git-dogfood)
- File-protection checks (`.vendored/check`)
- Vendor feedback (``.vendored/feedback``)
