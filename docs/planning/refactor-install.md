# Epic: Refactor `install` into `add` + `update`

## Motivation

The current `vendored/install` command does two conceptually different things:
- **Adding** a new vendor (first-time registration + initial install)
- **Updating** an existing vendor (version resolution + re-run install.sh)

Splitting these makes the interface clearer and enables better validation,
a cleaner contract for what it means to "implement git-vendored," and
better error messages in the update workflow.

---

## Vendor Contract

What a vendor repo must provide:
- `install.sh` at repo root, invoked as `bash install.sh <version>`
- `install.sh` must self-register in `.vendored/config.json` with at least:
  `repo`, `protected`, `install_branch`
- Version discoverable via GitHub Releases (tag) OR a `VERSION` file at root

The vendor's `install.sh` IS the manifest — it installs files AND declares
its own config. No separate manifest file needed.

---

## Tasks

### 1. Create `vendored/add` (local-only CLI tool)

**New file:** `vendored/add`

**Usage:** `python3 .vendored/add <owner/repo> [--name <name>]`

Runs locally (not as a workflow). Adding a vendor is a rare, intentional
action — the user commits and pushes the result. This also avoids the
GitHub restriction where `GITHUB_TOKEN` can't push changes to
`.github/workflows/` files.

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

**Error cases:**
- Repo doesn't exist or is inaccessible -> error with auth hint
- No `install.sh` found -> "repo does not implement git-vendored"
- `install.sh` didn't write a config entry -> "install.sh must self-register"
- Vendor already registered -> error or prompt to update instead

**Tests:** `tests/test_add.py`

---

### 2. Rename `vendored/install` -> `vendored/update`

**Rename:** `vendored/install` -> `vendored/update`
**Rename:** `tests/test_install.py` -> `tests/test_update.py`

Minimal changes to the existing code:
- Only operates on vendors already in config (no registration)
- Same version resolution, same download-and-run logic
- Improve unknown vendor error to list registered vendors:
  ```
  ::error::Unknown vendor: typo-name
  Registered vendors: git-vendored, git-semver, git-dogfood, pearls
  ```

---

### 3. Write `$GITHUB_OUTPUT` directly from Python

**Edit:** `vendored/update`

Current workflow parses `vendored/install` stdout via grep/cut/python
one-liners in shell (fragile). Instead, have the Python script write
directly to `$GITHUB_OUTPUT`:

```python
output_file = os.environ.get("GITHUB_OUTPUT")
if output_file:
    with open(output_file, "a") as f:
        f.write(f"vendor={result['vendor']}\n")
        f.write(f"changed={str(result['changed']).lower()}\n")
        # ...
```

This eliminates all the grep/cut/python parsing in the workflow shell
step. The workflow simplifies to just:

```yaml
- name: Run vendored update
  id: update
  run: python3 .vendored/update "$VENDOR" --version "$VERSION"

- name: Create Pull Request
  if: steps.update.outputs.changed == 'true'
```

---

### 4. Fix `VENDOR_PAT` token leaking into PR creation

**Edit:** `templates/github/workflows/install-vendored.yml`

The "Create Pull Request" step currently uses:
```yaml
GH_TOKEN: ${{ secrets.token || secrets.VENDOR_PAT || github.token }}
```

If `VENDOR_PAT` is set (for private vendors like `pearls`), it gets used
for PR creation on **all** vendor updates — even public ones. That PAT is
scoped for reading private repo contents, not for creating PRs.

**Fix:** Split token usage between steps:
```yaml
# Update step — needs VENDOR_PAT for private repo downloads
env:
  GITHUB_TOKEN: ${{ github.token }}
  VENDOR_PAT: ${{ secrets.token || secrets.VENDOR_PAT || '' }}
  GH_TOKEN: ${{ secrets.token || secrets.VENDOR_PAT || github.token }}

# PR creation step — always use github.token
env:
  GH_TOKEN: ${{ github.token }}
```

Also:
- Add `--head "$BRANCH"` to `gh pr create`
- Handle "PR already exists" case gracefully

---

### 5. Fix `automerge` default

**Edit:** `templates/github/workflows/install-vendored.yml`

Currently `automerge` defaults to `true` in a buried shell one-liner.

**Fix:**
- Default to `false` in the workflow
- Only automerge when explicitly `"automerge": true` in config
- Document the default in config shape

---

### 6. Update `install.sh` (bootstrap)

**Edit:** `install.sh`

`install.sh` remains as the bootstrap entrypoint. Changes:
- Download `vendored/add` in addition to `vendored/update` and `vendored/check`
- Rename references from `vendored/install` to `vendored/update`
- Self-registration logic stays (it's part of bootstrap)

---

## File Changes Summary

| Action | File | Description |
|--------|------|-------------|
| **New** | `vendored/add` | New add command (Python) |
| **Rename** | `vendored/install` -> `vendored/update` | Refocus as update-only |
| **Edit** | `vendored/update` | Write `$GITHUB_OUTPUT` directly, improve error msg |
| **Edit** | `install.sh` | Download `add` + `update` instead of `install` |
| **Edit** | `templates/github/workflows/install-vendored.yml` | Token fix, automerge default, simplified parsing |
| **New** | `tests/test_add.py` | Tests for add command |
| **Rename** | `tests/test_install.py` -> `tests/test_update.py` | Match rename |
| **No change** | `vendored/check` | Already independent |

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
5. **`$GITHUB_OUTPUT` directly from Python** — Eliminates fragile
   grep/cut shell parsing in the workflow.
