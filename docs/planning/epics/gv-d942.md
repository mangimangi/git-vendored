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

### 1. Create `vendored/add`

**New file:** `vendored/add` (source) → installed to `.vendored/add` by `install.sh`

**Usage:** `python3 .vendored/add <owner/repo> [--name <name>]`

Run by the user locally (not by workflows). Adding a vendor is a rare,
intentional action — the user commits and pushes the result. This also
avoids the GitHub restriction where `GITHUB_TOKEN` can't push changes to
`.github/workflows/` files.

**Flow:**
1. **Pre-validate** the target repo:
   - Confirm `install.sh` exists at repo root (via GitHub contents API:
     `gh api repos/{owner/repo}/contents/install.sh`)
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
- Repo doesn't exist or is inaccessible → error with auth hint
- No `install.sh` found → "repo does not implement git-vendored"
- `install.sh` didn't write a config entry → "install.sh must self-register"
- Vendor already registered → error or prompt to update instead

**Tests:** `tests/test_add.py` (see [Test Plan](#test-plan-test_addpy) below)

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

**Download changes:**
- Download `vendored/add` → `.vendored/add` (new)
- Download `vendored/update` → `.vendored/update` (renamed from `install`)
- Download `vendored/check` → `.vendored/check` (unchanged)

**Migration cleanup:**
- `rm -f .vendored/install` — remove the old script so it stops existing
  (the source file is renamed to `vendored/update` in Task 2, so this
  only matters for repos that had the old file installed)

**Workflow patching:**
- After downloading files, patch existing workflow files that reference
  the old path. In `.github/workflows/install-vendored.yml`, replace
  `python3 .vendored/install` with `python3 .vendored/update`:
  ```bash
  if [ -f .github/workflows/install-vendored.yml ]; then
      sed -i 's|python3 \.vendored/install|python3 .vendored/update|g' \
          .github/workflows/install-vendored.yml
  fi
  ```
  This ensures existing repos pick up the rename without manual intervention.

**Unchanged:**
- Self-registration logic stays (it's part of bootstrap)
- First-install-only guard for workflow templates stays

---

## Task Order

Tasks have ordering constraints due to shared files:

```
2 (rename install→update)
├── 3 (GITHUB_OUTPUT from Python) — edits vendored/update
├── 6 (install.sh bootstrap) — references vendored/update
│   └── 1 (vendored/add) — downloaded by install.sh
4 (token fix) ─┐
5 (automerge)  ─┤── both edit the workflow template, do together or sequentially
```

**Recommended implementation order:** 2 → 3 → 4+5 → 1 → 6

- **2 first** — the rename creates `vendored/update`, which Tasks 3 and 6 depend on
- **3 next** — edits `vendored/update` (GITHUB_OUTPUT), simplifies the workflow
  for Tasks 4+5
- **4+5 together** — both edit the workflow template; doing them together
  avoids merge conflicts
- **1 next** — `vendored/add` is a new file, no dependencies on other tasks,
  but Task 6 needs to download it
- **6 last** — references all renamed/new files, handles migration

---

## File Changes Summary

| Action | File | Description |
|--------|------|-------------|
| **New** | `vendored/add` | New add command (Python), installed to `.vendored/add` |
| **Rename** | `vendored/install` → `vendored/update` | Refocus as update-only |
| **Edit** | `vendored/update` | Write `$GITHUB_OUTPUT` directly, improve error msg |
| **Edit** | `install.sh` | Download `add` + `update`, delete old `install`, patch workflow |
| **Edit** | `templates/github/workflows/install-vendored.yml` | Token fix, automerge default, simplified parsing |
| **New** | `tests/test_add.py` | Tests for add command |
| **Rename** | `tests/test_install.py` → `tests/test_update.py` | Match rename |
| **No change** | `vendored/check` | Already independent |

---

## Migration / Backwards Compatibility

- Existing repos have `.vendored/install` — the bootstrap `install.sh` will
  download `.vendored/update` and `rm -f .vendored/install` (Task 6).
- Existing repos have workflows referencing `python3 .vendored/install` —
  `install.sh` patches the workflow file in-place with `sed` to reference
  `.vendored/update` (Task 6). No manual intervention required.

---

## Test Plan: `test_add.py`

Tests follow existing patterns: dynamic module import, `tmp_repo` + `make_config`
fixtures, `monkeypatch` for env vars, `unittest.mock.patch` for subprocess calls.

### TestPreValidate

| Test | Description |
|------|-------------|
| `test_repo_with_install_sh_passes` | Mock GitHub API returns `install.sh` contents → no error |
| `test_repo_without_install_sh_fails` | Mock API returns 404 → exits with "does not implement git-vendored" |
| `test_repo_not_found_fails` | Mock API returns 404 for repo → exits with auth hint |
| `test_version_resolvable_from_releases` | Mock releases API returns tag → version resolved |
| `test_version_resolvable_from_version_file` | Mock releases fails, VERSION file fallback works |
| `test_version_not_resolvable_fails` | Both resolution methods fail → exits with error |

### TestSnapshotAndDiff

| Test | Description |
|------|-------------|
| `test_detects_new_config_entry` | Config before has 1 vendor, after has 2 → new entry found |
| `test_no_new_entry_fails` | Config unchanged after install.sh → exits with "must self-register" |

### TestPostValidate

| Test | Description |
|------|-------------|
| `test_valid_entry_passes` | New entry has `repo`, `protected`, `install_branch` → success |
| `test_missing_repo_fails` | New entry missing `repo` → exits with clear message |
| `test_missing_protected_fails` | New entry missing `protected` → exits with clear message |
| `test_missing_install_branch_fails` | New entry missing `install_branch` → exits with clear message |

### TestAddVendor (integration)

| Test | Description |
|------|-------------|
| `test_add_new_vendor` | Full flow: pre-validate → run install.sh → post-validate → success output |
| `test_add_already_registered_fails` | Vendor already in config → exits with "already registered" |
| `test_add_with_custom_name` | `--name` flag overrides vendor key in config lookup |

### TestAddOutput

| Test | Description |
|------|-------------|
| `test_summary_shows_vendor_name` | Output includes vendor name |
| `test_summary_shows_version` | Output includes installed version |
| `test_summary_shows_registered_files` | Output includes what `install.sh` added to config |

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
4. **`add` is vendored, not a workflow** — Distributed via `install.sh`
   to `.vendored/add` like other tools. User runs it locally (not used by
   workflows); user commits and pushes the result.
5. **`$GITHUB_OUTPUT` directly from Python** — Eliminates fragile
   grep/cut shell parsing in the workflow.
6. **Workflow patching over manual migration** — `install.sh` patches
   existing workflow files in-place (`sed`) to reference the renamed
   script. No flag needed, no manual step for existing repos.
