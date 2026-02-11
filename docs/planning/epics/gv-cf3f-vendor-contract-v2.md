# gv-cf3f: Vendor Contract v2 — Manifest-Driven install/check/remove

**Status:** Planning
**Priority:** P1
**Epic:** gv-cf3f

## Summary

Redesign the git-vendored contract around three principles:

1. **Manifest-driven** — `install.sh` emits what it wrote; the framework derives protection rules from the manifest
2. **Framework owns metadata** — version tracking, config registration, and protection rules are the framework's job, not the vendor's
3. **Three commands** — `install` (idempotent add+update), `check` (PR validation), `remove` (clean uninstall)

---

## Motivation

The current design has several friction points:

- **`protected` is hand-maintained** in config.json by each vendor's `install.sh`. If an install.sh writes a new file but forgets to add it to `protected`, it's unprotected. If it removes a file but doesn't update `protected`, stale entries accumulate.
- **No uninstall path** — once a vendor is added, there's no way to cleanly remove it without manually hunting down files.
- **`add` and `update` are separate commands** with heavily duplicated code (both download install.sh, run it, validate).
- **`install.sh` is passed its own version** as an argument, which is redundant — the framework already resolved the version and fetched install.sh at that exact ref.
- **Repo structure splits source files** between `vendored/` (scripts) and `templates/` (config + workflows) for no clear reason. Both are "things that get installed in consumer repos."

## Design

### The Vendor Contract (what vendor repos implement)

A vendor repo provides:

```
install.sh     # puts files on disk, writes a manifest
VERSION        # (or GitHub releases) for version discovery
```

**`install.sh` contract:**

- Receives context via environment variables (no positional args):

| Env var | Set by | Purpose |
|---|---|---|
| `VENDOR_REPO` | framework | `owner/repo` for API calls |
| `VENDOR_REF` | framework | git ref to fetch files at |
| `VENDOR_MANIFEST` | framework | path to write file manifest to |
| `GH_TOKEN` | framework | auth token |

- Fetches its files from `$VENDOR_REPO` at `$VENDOR_REF` and writes them to disk
- **Must** write a manifest to `$VENDOR_MANIFEST` listing every file it created/modified, one path per line:

```
.some-tool/script.sh
.some-tool/config-template.json
.github/workflows/some-tool-check.yml
```

- **Must not** write version files (framework does this)
- **Must not** modify `.vendored/config.json` (framework does this)
- **May** use a `fetch_file` helper provided by the framework (future enhancement)

### The Framework (what git-vendored provides)

Three commands installed at `.vendored/{install,check,remove}`:

#### `.vendored/install <owner/repo> [--version <version>]`

Idempotent. Handles both first-time add and update.

```
Flow:
1. Resolve version (releases API → VERSION file fallback)
2. If already installed at this version, skip (unless --force)
3. Download install.sh from vendor repo at resolved ref
4. Set env vars: VENDOR_REPO, VENDOR_REF, VENDOR_MANIFEST (temp file)
5. Run install.sh
6. Read manifest from VENDOR_MANIFEST
7. Validate: manifest is non-empty, all listed files exist on disk
8. Write version file: .vendored/manifests/<vendor>.version
9. Write manifest:    .vendored/manifests/<vendor>.files
10. Update .vendored/config.json:
    - Set/update vendor entry with repo, install_branch
    - Derive `protected` from manifest (all files in manifest)
    - Preserve user-specified `allowed` entries
11. Report summary
```

#### `.vendored/check [--base <ref>] [--staged]`

Same as today but reads protection rules from manifests.

```
Flow:
1. Load config.json for vendor registry
2. For each vendor:
   a. Read .vendored/manifests/<vendor>.files
   b. Compute protected = manifest files + manifest file itself
   c. Apply allowed exceptions from config
   d. Skip if branch matches vendor's install_branch
3. Diff changed files against base
4. Report violations, exit non-zero if any
```

#### `.vendored/remove <vendor>`

Clean uninstall using the manifest.

```
Flow:
1. Look up vendor in config.json
2. Read .vendored/manifests/<vendor>.files
3. Delete every file listed in manifest
4. Delete .vendored/manifests/<vendor>.{files,version}
5. Remove vendor entry from config.json
6. Report what was removed
```

### Repo Structure (flattened)

Current:
```
vendored/           # scripts that get installed
  add
  update
  check
  hooks/pre-commit
templates/          # other things that get installed
  vendored/config.json
  github/workflows/...
```

Proposed:
```
templates/          # everything that gets installed into consumer repos
  install           # merged add+update
  check             # protection checker
  remove            # new: clean uninstall
  hooks/pre-commit
  config.json       # initial config template
  github/
    workflows/
      check-vendor.yml
      install-vendored.yml
```

`install.sh` (the bootstrap) maps `templates/*` → consumer repo:
- `templates/{install,check,remove,hooks/*}` → `.vendored/{install,check,remove,hooks/*}`
- `templates/config.json` → `.vendored/config.json` (create only)
- `templates/github/workflows/*` → `.github/workflows/*`

### Config Schema (v2)

```json
{
  "vendors": {
    "some-tool": {
      "repo": "owner/some-tool",
      "install_branch": "chore/install-some-tool",
      "private": false,
      "automerge": false,
      "allowed": [".some-tool/config.json"]
    }
  }
}
```

Changes from v1:
- **`protected` removed** — derived from `.vendored/manifests/<vendor>.files`
- **`allowed` stays** — user-specified exceptions are config, not manifest

### Manifest Storage

```
.vendored/
  manifests/
    git-vendored.files      # one filepath per line
    git-vendored.version    # single line: version string
    some-tool.files
    some-tool.version
  config.json               # vendor registry (no more `protected` field)
  install                   # the install command
  check                     # the check command
  remove                    # the remove command
```

Plain text, one-path-per-line for `.files`. No JSON overhead — easy to `cat`, `diff`, `grep`.

---

## Task Breakdown

### Phase 1: Repo restructure
1. **gv-cf3f.1** — Flatten `vendored/` + `templates/vendored/` into `templates/`
   - Move `vendored/{add,check,update}` → `templates/{install,check,update}` (keep update temporarily)
   - Move `vendored/hooks/` → `templates/hooks/`
   - Move `templates/vendored/config.json` → `templates/config.json`
   - Delete `vendored/` directory
   - Update `install.sh` bootstrap to use new paths

### Phase 2: Merge add+update into install
2. **gv-cf3f.2** — Create `templates/install` (merged add+update)
   - Idempotent: detects whether vendor exists, handles both cases
   - Version skip logic (already at target version → skip unless --force)
   - Remove `templates/update` after merge
   - Update workflow template to call `.vendored/install` instead of `.vendored/update`

### Phase 3: Manifest contract
3. **gv-cf3f.3** — Add manifest emission to the install.sh contract
   - Framework sets `VENDOR_MANIFEST` env var (temp file path)
   - Framework sets `VENDOR_REPO`, `VENDOR_REF` env vars
   - Post-install: read manifest, validate files exist on disk
   - Store manifest at `.vendored/manifests/<vendor>.files`
   - Store version at `.vendored/manifests/<vendor>.version`
   - Remove version arg from install.sh (use env vars)

4. **gv-cf3f.4** — Derive `protected` from manifests in check
   - `check` reads `.vendored/manifests/<vendor>.files` instead of config `protected`
   - Fallback: if no manifest exists (v1 vendor), use config `protected` for backwards compat
   - Remove `protected` from config on next install (migration)

### Phase 4: Remove command
5. **gv-cf3f.5** — Create `templates/remove`
   - Read manifest to know what to delete
   - Delete manifest files, then manifest itself
   - Remove vendor entry from config.json
   - Error if vendor not registered or no manifest

### Phase 5: Update git-vendored's own install.sh
6. **gv-cf3f.6** — Rewrite `install.sh` (the bootstrap) for v2
   - Source files from `templates/` (new paths)
   - Emit manifest to `$VENDOR_MANIFEST` instead of self-registering
   - Remove version positional arg, read `$VENDOR_REF` / `$VENDOR_VERSION`
   - Create `.vendored/manifests/` directory

### Phase 6: Tests + docs
7. **gv-cf3f.7** — Update tests for new structure
   - Port test_add.py + test_update.py → test_install.py
   - Update test_check.py for manifest-based protection
   - Add test_remove.py
   - Add tests for manifest read/write/validation

8. **gv-cf3f.8** — Update README and docs
   - Document new vendor contract (env vars, manifest)
   - Document install/check/remove commands
   - Document config schema v2 (no protected field)
   - Migration notes for v1 → v2

---

## Migration / Backwards Compatibility

- **Consumer repos on v1:** Their config has `protected` fields. The v2 `check` command falls back to config `protected` when no manifest file exists. On next `install`, the manifest is created and `protected` is removed from config.
- **Vendor repos on v1 install.sh contract:** Their install.sh takes a version arg and self-registers. The v2 framework still runs install.sh but with env vars set. If install.sh ignores env vars and writes config directly, the framework detects the config change and extracts the info. On vendor repo upgrade to v2 contract, they switch to manifest emission.
- **Self-referential (dogfood):** git-vendored's own `install.sh` will be updated in gv-cf3f.6 to use the v2 contract. Until then, the v1 compat path handles it.

## Open Questions

1. **Should `fetch_file` be a framework-provided helper?** Vendors currently each implement their own download logic. The framework could provide `.vendored/lib/fetch` that install.sh sources. Deferred — not blocking for v2.
2. **Should `allowed` also move to the manifest?** The vendor knows which of its files are user-editable. Could be a second section in the manifest. Keeping in config for now since it's a consumer-side policy decision.
3. **Manifest format: one-per-line vs JSON?** Going with one-per-line for simplicity. JSON adds no value for a flat list of paths.
