# Plan: Refactor `install` into `add` + `update`

## Motivation

The current `vendored/install` command does two conceptually different things:
- **Adding** a new vendor (first-time registration + initial install)
- **Updating** an existing vendor (version resolution + re-run install.sh)

Splitting these makes the interface clearer and enables better validation,
better workflow UX (dropdown of known vendors), and a cleaner contract for
what it means to "implement git-vendored."

---

## Current Architecture

```
install.sh                     # Bootstrap: sets up .vendored/ system + self-registers
vendored/install               # Runtime: install/update any vendor from config
vendored/check                 # Runtime: PR protection check
templates/vendored/config.json # Empty config template
templates/github/workflows/    # Workflow templates (install + check)
```

**Config shape** (`.vendored/config.json`):
```json
{
  "vendors": {
    "<name>": {
      "repo": "owner/repo",
      "install_branch": "chore/install-<name>",
      "private": false,
      "automerge": true,
      "dogfood": false,
      "protected": [".<dir>/**"],
      "allowed": [".<dir>/config.json"]
    }
  }
}
```

**Vendor contract** (what a vendor repo must provide):
- `install.sh` at repo root, invoked as `bash install.sh <version>`
- Version discoverable via GitHub Releases (tag) OR a `VERSION` file at root

---

## Proposed Changes

### 1. New command: `vendored/add`

**Usage:** `python3 .vendored/add <owner/repo> [--name <name>]`

**Responsibilities:**
- Validate the target repo implements git-vendored:
  - Confirm `install.sh` exists at repo root (via GitHub API)
  - Confirm version is resolvable (releases or VERSION file)
- Register the vendor in `.vendored/config.json`
  - Auto-generate `install_branch` from vendor name
  - If vendor repo provides a manifest (future: `vendor.json`), use it to
    populate `protected`, `allowed`, etc.
  - Otherwise, use sensible defaults (e.g., `protected: [".<name>/**"]`)
- Run the initial install (download + execute `install.sh`)
- Output what was added and installed

**Validation ("implements git-vendored"):**
For now, the minimum contract is:
1. Repo has `install.sh` at root
2. Repo has either GitHub Releases or a `VERSION` file

Future: a `vendor.json` manifest at repo root could declare:
```json
{
  "protected": [".<dir>/**", ".github/workflows/<workflow>.yml"],
  "allowed": [".<dir>/config.json"],
  "install_branch_prefix": "chore/install-<name>"
}
```
This would let `add` fully auto-populate the config entry.

**Error cases:**
- Repo doesn't exist or is inaccessible -> error with auth hint
- No `install.sh` found -> error: "repo does not implement git-vendored"
- Vendor already registered -> error or prompt to update instead

### 2. Rename/refocus: `vendored/install` -> `vendored/update`

**Usage:** `python3 .vendored/update <vendor|all> [--version <version>]`

This is the existing `vendored/install` with minimal changes:
- Rename file from `vendored/install` to `vendored/update`
- Only operates on vendors already in config (no registration)
- Same version resolution, same download-and-run logic
- Same output format (key=value for single, JSON for all)

### 3. Workflow improvements

#### `install-vendored.yml` -> split or simplify

**Option A (recommended):** Keep one workflow, rename to `vendored.yml`
- `workflow_dispatch` inputs:
  - `action`: `add` or `update` (default: `update`)
  - `vendor`: vendor name or `all` — for `update`, could use `type: choice`
    but GitHub doesn't support dynamic choices from files, so keep as string
    input with "all" default
  - `version`: version string (default: `latest`)
  - `repo`: only used when action=`add`
- Schedule trigger always runs `update all`

**Option B:** Two workflows (`add-vendor.yml`, `update-vendor.yml`)
- Simpler per-workflow but more files to maintain

#### Clean up output parsing

Current workflow parses `vendored/install` output via grep/cut/python
one-liners (fragile). Instead:
- Have `update` write structured output to a file (e.g., `/tmp/vendor-result.json`)
- Workflow reads the file — single `python3 -c` to extract what's needed
- Or use `>> $GITHUB_OUTPUT` directly from the Python script

#### Fix `automerge` default

Currently `automerge` defaults to `true` in a buried shell one-liner
(`install-vendored.yml:153`). Should:
- Default to `false` in the workflow
- Only automerge when explicitly set in config
- Document the default

### 4. `install.sh` (bootstrap) — minimal changes

`install.sh` remains as the bootstrap entrypoint for git-vendored itself.
It's fine that it does double duty (bootstrap system + install-as-vendor)
since git-vendored IS the system. Changes:
- Download `vendored/add` in addition to `vendored/update` and `vendored/check`
- The self-registration logic stays here (it's part of bootstrap)

### 5. PR creation bug: `VENDOR_PAT` token leaking into PR creation

The "Create Pull Request" step uses this token chain:
```yaml
GH_TOKEN: ${{ secrets.token || secrets.VENDOR_PAT || github.token }}
```

**The problem:** If `VENDOR_PAT` is set as a repo secret (needed for private
vendors like `pearls`), it gets used for PR creation on **all** vendor
updates — even public ones. That PAT is likely scoped for reading private
repo contents, not for creating PRs on the current repo. So PR creation
fails silently (error swallowed into `PR_URL` via `2>&1`).

**The fix:** Use different tokens for different steps:
- **Install step**: needs `VENDOR_PAT` to download from private repos
- **PR creation step**: should always use `github.token`, which has
  `contents: write` + `pull-requests: write` from the workflow `permissions`
  block

```yaml
# Install step — needs VENDOR_PAT for private repo downloads
env:
  GITHUB_TOKEN: ${{ github.token }}
  VENDOR_PAT: ${{ secrets.token || secrets.VENDOR_PAT || '' }}
  GH_TOKEN: ${{ secrets.token || secrets.VENDOR_PAT || github.token }}

# PR creation step — always use github.token for repo operations
env:
  GH_TOKEN: ${{ github.token }}
```

Additionally:
- Add `--head "$BRANCH"` to `gh pr create` for robustness
- Handle "PR already exists" case gracefully

---

## File Changes Summary

| Action | File | Description |
|--------|------|-------------|
| **New** | `vendored/add` | New add command (Python) |
| **Rename** | `vendored/install` -> `vendored/update` | Refocus as update-only |
| **Edit** | `install.sh` | Download `add` + `update` instead of `install` |
| **Edit** | `templates/github/workflows/install-vendored.yml` | Add/update dispatch, clean output parsing, fix automerge default |
| **New** | `tests/test_add.py` | Tests for add command |
| **Edit** | `tests/test_install.py` -> `tests/test_update.py` | Rename + adjust |
| **Edit** | `vendored/check` | No changes needed (already independent) |

---

## Migration / Backwards Compatibility

- Existing repos have `.vendored/install` — the bootstrap `install.sh` will
  replace it with `.vendored/update` on next update. The old `install` path
  stops existing; workflows reference the new name.
- The workflow template gets updated by `install.sh` only on first install
  (existing repos keep their workflow). May need a flag or docs for manual
  workflow update.

---

## Open Questions

1. **Vendor manifest (`vendor.json`)**: Do we want this now or later? It makes
   `add` much more powerful but adds a requirement to vendor repos.
2. **Dynamic workflow dropdown**: GitHub doesn't natively support populating
   `choice` options from a file. Worth a two-job approach (job 1 reads config,
   job 2 uses matrix/choice) or just keep as free-text input?
3. **Should `add` run the initial install automatically**, or just register
   and let the user run `update` separately?
