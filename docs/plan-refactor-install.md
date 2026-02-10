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

### 1. New command: `vendored/add` (local-only CLI tool)

**Usage:** `python3 .vendored/add <owner/repo> [--name <name>]`

Runs locally (not as a workflow). Adding a vendor is a rare, intentional
action — the user commits and pushes the result.

**Flow:**
1. **Pre-validate** the target repo:
   - Confirm `install.sh` exists at repo root (via GitHub API)
   - Confirm version is resolvable (GitHub Releases or VERSION file)
   - Fail with "repo does not implement git-vendored" if either is missing
2. **Snapshot** `.vendored/config.json` (before state)
3. **Run** the vendor's `install.sh` (downloads files, writes config entry)
4. **Post-validate** the config entry the vendor registered:
   - Diff config before/after to find the new entry
   - Required fields: `repo`, `protected`, `install_branch`
   - Fail with clear message if `install.sh` didn't register itself:
     "vendor's install.sh must add an entry to .vendored/config.json
     with at least: repo, protected, install_branch"
5. **Output** summary of what was added

The vendor's `install.sh` IS the manifest — it installs files AND declares
its own config (protected paths, allowed paths, install_branch, etc.).
No separate manifest file needed.

**Error cases:**
- Repo doesn't exist or is inaccessible -> error with auth hint
- No `install.sh` found -> "repo does not implement git-vendored"
- `install.sh` didn't write a config entry -> "install.sh must self-register"
- Vendor already registered -> error or prompt to update instead

### 2. Rename/refocus: `vendored/install` -> `vendored/update`

**Usage:** `python3 .vendored/update <vendor|all> [--version <version>]`

This is the existing `vendored/install` with minimal changes:
- Rename file from `vendored/install` to `vendored/update`
- Only operates on vendors already in config (no registration)
- Same version resolution, same download-and-run logic
- Same output format (key=value for single, JSON for all)
- Improve unknown vendor error to list registered vendors:
  ```
  ::error::Unknown vendor: typo-name
  Registered vendors: git-vendored, git-semver, git-dogfood, pearls
  ```
  (Current code already does this partially — just needs the phrasing tightened)

### 3. Workflow improvements

#### `add` is local-only, `update` stays as the workflow

`add` is a rare, intentional operation — no workflow needed. User runs it
locally: `python3 .vendored/add owner/repo`. This also avoids the GitHub
restriction where `GITHUB_TOKEN` can't push changes to `.github/workflows/`
files (would need a PAT with `workflows` scope).

`update` keeps the existing workflow with these changes:

#### Vendor input validation against config

The `vendor` input stays as `type: string` (free-text). GitHub Actions
doesn't support dynamic `choice` options populated from a file.

Instead, `vendored/update` validates the input against `.vendored/config.json`
and fails fast with a helpful message if unrecognized:

```
::error::Unknown vendor: typo-name
Registered vendors: git-vendored, git-semver, git-dogfood, pearls
```

This runs before any version resolution or downloads, so the feedback
is immediate.

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

## Resolved Decisions

1. **No separate vendor manifest** — The vendor's `install.sh` is the
   manifest. It installs files AND writes its own config entry. `add`
   validates the result after running it.
2. **No dynamic workflow dropdown** — GitHub doesn't support dynamic
   `choice` options from files, and updating workflow YAML programmatically
   requires a PAT with `workflows` scope. Instead: free-text `vendor` input,
   validated against `config.json` with a helpful error listing registered
   vendors.
3. **`add` runs initial install** — Register + install in one shot.
4. **`add` is local-only** — Not a workflow. User runs locally, commits,
   pushes.
