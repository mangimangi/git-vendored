# Directory Restructure: Consolidate Vendor Files Under .vendored/

**Status:** Planning

## Problem

Each vendor claims its own dotdir at the repo root (`.pearls/`, `.dogfood/`, `.semver/`), creating bloat. A repo with 5 vendors has 6 dotdirs (5 vendors + `.vendored/`). This doesn't scale.

Additionally, the single `config.json` with all vendors causes merge conflicts when multiple vendor update PRs are open simultaneously.

## Proposal

Consolidate everything under `.vendored/`, following the pattern already established by `manifests/`:

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
  pkg/                       # per-vendor installed files (NEW)
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

## Migration

### For the framework (this repo)

1. Add `VENDOR_INSTALL_DIR` to the env vars set by `download_and_run_install()`
2. Create `pkg/` directory during install
3. Update `load_config()` to scan `configs/` directory
4. Update `check` to read per-vendor configs and resolve protection from `pkg/` paths
5. Update `remove` to delete `configs/<vendor>.json` and `src/<vendor>/`
6. Migration helper: split existing `config.json` into `configs/<vendor>.json` files
7. Update `install.sh` (bootstrap) to create the new directory structure

### For vendor repos

Each vendor's `install.sh` needs updating to:
1. Read `$VENDOR_INSTALL_DIR` and install files there (with fallback)
2. Update manifest paths to reflect new locations

### For consumer repos

On next framework update:
1. Framework migration splits `config.json` → `configs/<vendor>.json`
2. On next per-vendor update, vendor's new `install.sh` installs to `src/<vendor>/`
3. Old dotdir files are cleaned up (manifest-driven removal of old paths + install to new paths)

This means migration is **gradual**: framework updates first, then each vendor updates on its own schedule.

## Open Questions

1. ~~**Naming:** resolved — using `pkg/`.~~

2. **Should `config.json` remain for framework-level settings?** Currently no framework-level settings exist. Could reserve `config.json` for them and use `configs/` only for per-vendor. Or just scan `configs/` and add a `_framework.json` later if needed.

3. **Should the framework auto-create `$VENDOR_INSTALL_DIR`?** Probably yes — the framework creates the dir before running `install.sh`, so vendors don't need `mkdir -p`.

4. **Ordering vs v2 contract work.** The v2 epic (gv-cf3f) is mostly done. This restructure builds on v2 (manifests, env vars). Should this be a v3 or rolled into remaining v2 work?
