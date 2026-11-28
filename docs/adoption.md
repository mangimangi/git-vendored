# Adoption Guide: gv-7a53 Framework Features

This guide covers how vendor repos can adopt the framework features from the
gv-7a53 epic (Codex Support & Vendor DX Improvements).

---

## 1. `$VENDOR_LIB` -- Shell Helper Library

Vendor `install.sh` scripts can source the framework's helper library to get
`fetch_file` and `fetch_dir` without reimplementing download/auth/manifest
logic.

The helpers work in two modes:

- **Checkout mode** -- the framework fetched the vendor with git at
  `$VENDOR_REF` and set `$VENDOR_CHECKOUT` to that checkout's absolute path.
  `fetch_file` and `fetch_dir` copy from it: no `gh`, no `curl`, no token,
  and any git host works.
- **Fallback mode** -- `$VENDOR_CHECKOUT` is unset or empty (an installer run
  by hand, or an older framework). The helpers download as before: the GitHub
  API through `gh` when a token is set, else `curl` on
  `raw.githubusercontent.com`.

In both modes a file gets its content only: its mode is the umask default, and
it is executable only through `fetch_file ... +x` (an exec bit in the vendor's
git tree is not copied). A vendor `install.sh` that uses the helpers needs no
change to work in either mode.

**Pattern with inline fallback** (for compatibility when the framework is older
or absent):

```bash
source "$VENDOR_LIB" 2>/dev/null || {
    fetch_file() {
        local src="$1" dst="$2"
        mkdir -p "$(dirname "$dst")"
        if [ -n "${VENDOR_CHECKOUT:-}" ] && [ -d "$VENDOR_CHECKOUT" ]; then
            cat "$VENDOR_CHECKOUT/$src" > "$dst"
        else
            curl -fsSL "https://raw.githubusercontent.com/$VENDOR_REPO/$VENDOR_REF/$src" -o "$dst"
        fi
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
`$VENDOR_MANIFEST`. In checkout mode a `repo_path` missing from the checkout
(or a symlink) returns nonzero with an error naming the path.

### `fetch_dir`

```
fetch_dir <repo_path> <local_path>
```

- `repo_path` -- directory path within the vendor repo
- `local_path` -- destination directory relative to repo root

Recursively copies or downloads the directory tree, calling `fetch_file` for
each file, so each lands in `$VENDOR_MANIFEST`. In checkout mode it walks
`$VENDOR_CHECKOUT/<repo_path>` and skips `.git`, symlinks and submodules (the
API mode handles only files and directories). In fallback mode it **requires
the `gh` CLI** (uses the GitHub API to list directory contents). A missing
directory prints `Error: failed to list directory <repo_path> from <repo>` and
returns 1.

### Auth

In checkout mode no token is used: the framework already fetched the vendor
(with `CICD_READ_TOKEN` for a private one). In fallback mode both functions
authenticate with the first of `$CICD_READ_TOKEN`, `$CICD_WRITE_TOKEN`,
`$VENDOR_PAT` (deprecated) and `$GH_TOKEN` that is set, for private repo
access. No additional auth setup is needed in vendor scripts.

### Environment variables

These are set by the framework before the vendor `install.sh` runs:

| Variable             | Description                            |
|----------------------|----------------------------------------|
| `VENDOR_CHECKOUT`    | Absolute path of the vendor checkout at `VENDOR_REF` (checkout mode) |
| `VENDOR_REPO`        | The vendor's repo as configured (a git URL or `owner/repo`) |
| `VENDOR_REF`         | Git ref (the version's tag) to fetch files at |
| `VENDOR_MANIFEST`    | Path to the file manifest              |
| `VENDOR_INSTALL_DIR` | Target directory for vendor files      |
| `GH_TOKEN`           | Auth token (optional)                  |
| `CICD_READ_TOKEN`    | Token that reads private repos         |
| `CICD_WRITE_TOKEN`   | Read when `CICD_READ_TOKEN` is unset   |
| `VENDOR_PAT`         | Deprecated old name, read last         |

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
