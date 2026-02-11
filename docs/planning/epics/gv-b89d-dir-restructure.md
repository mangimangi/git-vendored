# gv-b89d: Directory Restructure — Consolidate Vendor Files Under .vendored/

**Status:** Refinement
**Priority:** P1
**Epic:** gv-b89d
**Depends on:** gv-cf3f (v2 contract — manifests, env vars)

## Summary

Consolidate per-vendor dotdirs (`.pearls/`, `.dogfood/`, `.semver/`) and the shared `config.json` into a structured layout under `.vendored/`:

- **`pkg/<vendor>/`** — vendor-installed files (replaces per-vendor dotdirs at repo root)
- **`configs/<vendor>.json`** — per-vendor config (replaces monolithic `config.json`)

This eliminates dotdir sprawl and merge conflicts from concurrent vendor update PRs.

---

## Motivation

Each vendor claims its own dotdir at the repo root. A repo with 5 vendors has 6 dotdirs (5 vendors + `.vendored/`). This doesn't scale.

Additionally, the single `config.json` with all vendors causes merge conflicts when multiple vendor update PRs are open simultaneously.

## Design

### Target layout

```
.vendored/
  install                    # framework script (git-vendored's own files)
  check                      # framework script
  remove                     # framework script
  hooks/                     # framework hooks
  manifests/                 # per-vendor (existing)
    <vendor>.files
    <vendor>.version
  configs/                   # per-vendor config (replaces config.json)
    <vendor>.json
  pkg/                       # per-vendor installed files
    <vendor>/
      ...
```

Files that **must** live at framework-dictated paths (`.github/workflows/`, `.claude/hooks/`) stay where they are. The manifest still tracks them.

### Per-vendor configs: `configs/<vendor>.json`

Current `config.json`:
```json
{
  "vendors": {
    "pearls": { "repo": "mangimangi/pearls", "install_branch": "chore/install-pearls", ... },
    "git-semver": { "repo": "mangimangi/git-semver", ... }
  }
}
```

Proposed `configs/pearls.json`:
```json
{
  "repo": "mangimangi/pearls",
  "install_branch": "chore/install-pearls",
  "private": true,
  "automerge": true,
  "allowed": [".vendored/pkg/pearls/config.json", ".vendored/pkg/pearls/issues.jsonl"]
}
```

**Benefits:**
- Adding/removing a vendor is file-level (add/delete a file), not a JSON edit to a shared file
- No merge conflicts between concurrent vendor update PRs
- Follows the `manifests/` pattern — one artifact per vendor
- `config.json` becomes available for framework-level settings if needed later

**Config loading:** `load_config()` scans `configs/` directory. Vendor name is derived from filename (e.g., `pearls.json` → vendor name `pearls`).

### Vendor install dir: `pkg/<vendor>/`

Vendor `install.sh` receives a new env var:

| Env var | Purpose |
|---------|---------|
| `VENDOR_INSTALL_DIR` | Directory for vendor's files (e.g., `.vendored/pkg/pearls`) |

The contract becomes: put your files under `$VENDOR_INSTALL_DIR`. Files that need specific system paths (workflows, hooks) go to those paths and must be listed in the manifest.

**What changes for vendors:**

| Before | After |
|--------|-------|
| `.pearls/prl.py` | `.vendored/pkg/pearls/prl.py` |
| `.pearls/config.json` | `.vendored/pkg/pearls/config.json` |
| `.dogfood/check` | `.vendored/pkg/git-dogfood/check` |
| `.semver/bump` | `.vendored/pkg/git-semver/bump` |
| `.github/workflows/dogfood.yml` | `.github/workflows/dogfood.yml` (unchanged) |

**Protection story simplifies partially:** Everything under `.vendored/pkg/<vendor>/` is protected by location. Workflow files outside `.vendored/` still need manifest-based protection.

### The dogfood question

git-vendored vendors itself. Its installed files ARE the framework scripts (`.vendored/install`, `.vendored/check`, etc.). These don't move to `.vendored/pkg/git-vendored/` — they stay at `.vendored/` root because they ARE the framework. This is the existing dogfood exception; this restructure doesn't change it.

## Contract Changes Summary

New env vars passed to `install.sh`:

| Env var | Value | Notes |
|---------|-------|-------|
| `VENDOR_INSTALL_DIR` | `.vendored/pkg/<vendor>` | New — primary install location |
| `VENDOR_REPO` | `owner/repo` | Existing v2 |
| `VENDOR_REF` | git ref | Existing v2 |
| `VENDOR_MANIFEST` | temp file path | Existing v2 |
| `GH_TOKEN` | auth token | Existing |

Vendors **should** install files under `$VENDOR_INSTALL_DIR` but **may** install to other paths (workflows, hooks) when the target system requires it. All installed files must appear in the manifest regardless of location.

**Backwards compat:** If `$VENDOR_INSTALL_DIR` is not set, vendor falls back to its original layout. This lets v1/v2 vendors work while being migrated.

---

## Task Breakdown

### Phase 1: Per-vendor configs
1. **gv-b89d.1** — Split `config.json` into `configs/<vendor>.json`
   - Update `load_config()` to scan `configs/` directory
   - Vendor name derived from filename
   - Migration helper: split existing `config.json` → `configs/<vendor>.json`
   - Update `install` to write per-vendor config files
   - Update `check` to read per-vendor configs
   - Update `remove` to delete `configs/<vendor>.json`

### Phase 2: Vendor install directory
2. **gv-b89d.2** — Add `VENDOR_INSTALL_DIR` env var and `pkg/` directory
   - Add `VENDOR_INSTALL_DIR` to env vars set by `download_and_run_install()`
   - Framework auto-creates `pkg/<vendor>/` before running `install.sh`
   - Update `remove` to delete `pkg/<vendor>/`

3. **gv-b89d.3** — Update `check` for `pkg/` paths
   - Resolve protection from `pkg/` paths
   - Maintain manifest-based protection for files outside `.vendored/`

### Phase 3: Bootstrap and migration
4. **gv-b89d.4** — Update `install.sh` (bootstrap) for new directory structure
   - Create `configs/` and `pkg/` directories during bootstrap
   - Run config migration on framework update

5. **gv-b89d.5** — Config migration path
   - On framework update: split `config.json` → `configs/<vendor>.json`
   - On vendor update: vendor's new `install.sh` installs to `pkg/<vendor>/`
   - Clean up old dotdir files (manifest-driven removal of old paths)

### Phase 4: Vendor repo updates
6. **gv-b89d.6** — Update vendor install.sh scripts
   - Each vendor's `install.sh` reads `$VENDOR_INSTALL_DIR` and installs there
   - Fallback to original layout when `$VENDOR_INSTALL_DIR` is not set
   - Update manifest paths to reflect new locations

### Phase 5: Docs and testing
7. **gv-b89d.7** — Update tests for new structure
   - Test config split/load from `configs/`
   - Test install to `pkg/<vendor>/`
   - Test migration from monolithic config
   - Test remove cleans up `configs/` and `pkg/`

8. **gv-b89d.8** — Write implementation guide
   - Detailed guide for implementers covering each phase
   - Code pointers, edge cases, and migration sequences

9. **gv-b89d.9** — Update README and docs
   - Document new directory layout
   - Document `VENDOR_INSTALL_DIR` env var
   - Document per-vendor config format
   - Migration notes for existing consumers

---

## Migration

### For consumer repos

Migration is **gradual**: framework updates first, then each vendor updates on its own schedule.

1. Framework update splits `config.json` → `configs/<vendor>.json`
2. On next per-vendor update, vendor's new `install.sh` installs to `pkg/<vendor>/`
3. Old dotdir files are cleaned up (manifest-driven removal of old paths + install to new paths)

### For vendor repos

Each vendor's `install.sh` needs updating to:
1. Read `$VENDOR_INSTALL_DIR` and install files there (with fallback)
2. Update manifest paths to reflect new locations

---

## Open Questions

1. **Should `config.json` remain for framework-level settings?** Currently no framework-level settings exist. Could reserve `config.json` for them and use `configs/` only for per-vendor. Or just scan `configs/` and add a `_framework.json` later if needed.

2. **Should the framework auto-create `$VENDOR_INSTALL_DIR`?** Probably yes — the framework creates the dir before running `install.sh`, so vendors don't need `mkdir -p`.
