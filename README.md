# git-vendored

Automated vendor install control for repo-embedded tools via GitHub workflows. Register external tools (like linters, CI helpers, or workflow utilities) in your repo, and git-vendored keeps them updated automatically — with PR-based updates, file protection, and private repo support.

## How It Works

git-vendored implements a **manifest-driven vendor contract**:

1. A vendor repo provides an `install.sh` at its root
2. The framework runs `install.sh` with context via environment variables
3. `install.sh` downloads its files and writes a manifest listing every file it installed
4. The framework stores the manifest, tracks versions, and derives file protection rules
5. A GitHub workflow runs on a schedule (or manually), checks for updates, and opens PRs

## Quick Start

Bootstrap git-vendored in a new repo:

```bash
# Download and run the bootstrap installer
curl -fsSL https://raw.githubusercontent.com/mangimangi/git-vendored/v0.1.0/install.sh | bash -s 0.1.0
```

This creates:
- `.vendored/install` — add new vendors or update existing ones
- `.vendored/check` — enforce file protection rules
- `.vendored/remove` — cleanly uninstall a vendor
- `.vendored/config.json` — framework-level config (legacy vendor registry)
- `.vendored/configs/` — per-vendor config files (`<vendor>.json`)
- `.vendored/pkg/` — vendor-installed files (`<vendor>/`)
- `.vendored/manifests/` — manifest storage (file lists + versions)
- `.github/workflows/install-vendored.yml` — automated update workflow
- `.github/workflows/check-vendor.yml` — PR protection checks

## Adding a Vendor

```bash
python3 .vendored/install owner/repo-name
```

This will:
1. Verify the repo has `install.sh` and a resolvable version
2. Run the vendor's `install.sh` with `VENDOR_REPO`, `VENDOR_REF`, `VENDOR_MANIFEST`, and `VENDOR_INSTALL_DIR` set
3. Read the manifest output and store it at `.vendored/manifests/<vendor>.files`
4. Store the version at `.vendored/manifests/<vendor>.version`

Use `--name` to override the vendor key:

```bash
python3 .vendored/install owner/repo-name --name my-custom-name
```

## How Updates Work

The `install-vendored.yml` workflow runs weekly (Mondays 9am UTC) or on manual dispatch:

```
schedule/manual trigger → .vendored/install all --pr → detect changes → create PR
```

Update a specific vendor manually:

```bash
# From GitHub Actions (workflow_dispatch)
# Or locally:
python3 .vendored/install my-vendor --version 2.0.0
python3 .vendored/install all  # update all vendors

# With automatic PR creation (used by CI):
python3 .vendored/install all --pr
```

## Removing a Vendor

```bash
python3 .vendored/remove my-vendor
```

This uses the manifest to cleanly remove all vendor files, delete the manifest, and remove the config entry. A manifest is required — the command will error if none exists (re-install the vendor first to generate one).

## Configuration

Each vendor has its own config file at `.vendored/configs/<vendor>.json`:

```json
{
  "repo": "owner/my-tool",
  "install_branch": "chore/install-my-tool",
  "allowed": [".vendored/pkg/my-tool/config.json"],
  "private": false,
  "automerge": false,
  "dogfood": false
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `repo` | yes | GitHub repository (`owner/name`) |
| `install_branch` | yes | Branch prefix for vendor update PRs |
| `allowed` | no | Glob patterns of vendor-managed files that users *can* edit |
| `private` | no | If `true`, requires `VENDOR_PAT` secret for access |
| `automerge` | no | If `true`, auto-merge vendor update PRs (default: `false`) |
| `dogfood` | no | If `true`, skips `VENDOR_INSTALL_DIR` (installs into framework paths) |

**Backwards compatibility:** If `.vendored/configs/` has no `.json` files, the framework falls back to reading from a monolithic `.vendored/config.json` with a `vendors` key. The first time `install` runs after upgrading, it automatically migrates the monolithic config into per-vendor files.

**Note:** The `protected` field is preserved in per-vendor config for v1 fallback compatibility. Protection rules are derived automatically from manifests at `.vendored/manifests/<vendor>.files`. For v1 vendors without manifests, `check` falls back to config `protected` patterns.

## Vendor Contract

A vendor repo must provide:

1. **`install.sh` at repo root** — receives context via environment variables, downloads its files, and writes a manifest
2. **Version discovery** — either GitHub Releases (tags like `v1.0.0`) or a `VERSION` file at repo root

### Environment Variables

`install.sh` receives these environment variables from the framework:

| Env var | Purpose |
|---------|---------|
| `VENDOR_REPO` | `owner/repo` for API calls |
| `VENDOR_REF` | Git ref to fetch files at |
| `VENDOR_MANIFEST` | Path to write the file manifest to |
| `VENDOR_INSTALL_DIR` | Target directory for vendor files (e.g., `.vendored/pkg/<vendor>`) |
| `GH_TOKEN` | Auth token (when available) |

`VENDOR_INSTALL_DIR` is set for non-dogfood vendors. Vendors SHOULD install their primary files under this directory but MAY install to other paths (workflows, hooks) when the target system requires specific locations. If not set, the vendor falls back to its original file layout.

### Manifest

`install.sh` **must** write a manifest to `$VENDOR_MANIFEST` listing every file it created or modified, one path per line:

```
.my-tool/script.sh
.my-tool/config-template.json
.github/workflows/my-tool-check.yml
```

`install.sh` **must not**:
- Write version files (the framework handles this via `.vendored/manifests/<vendor>.version`)
- Modify `.vendored/config.json` (the framework handles vendor registration)

## Protection Rules

`.vendored/check` runs on every PR via `check-vendor.yml`:

- Files listed in `.vendored/manifests/<vendor>.files` cannot be modified
- Exception: files matching `allowed` patterns in config can be edited
- Exception: PRs from branches matching `install_branch` prefix bypass checks for that vendor
- Fallback: for v1 vendors without manifests, config `protected` patterns are used

This prevents accidental edits to vendor-managed files while allowing the automated update workflow to function.

## Directory Layout

```
.vendored/
  install                        # framework command: add/update vendors
  check                          # framework command: file protection checks
  remove                         # framework command: uninstall vendors
  config.json                    # framework-level config (legacy)
  configs/
    my-tool.json                 # per-vendor config
    pearls.json
  pkg/
    my-tool/                     # vendor-installed files
      script.sh
      lib.py
    pearls/
      prl.py
  manifests/
    my-tool.files                # one filepath per line
    my-tool.version              # single line: version string
    pearls.files
    pearls.version
  hooks/
    pre-commit                   # shared pre-commit hook
```

Manifest `.files` are plain text, one-path-per-line. Easy to `cat`, `diff`, `grep`.

## Migration

### From v1 to v2

If you're upgrading from a v1 git-vendored installation:

1. **Re-bootstrap**: Run the latest `install.sh` — it will clean up deprecated files (`.vendored/add`, `.vendored/update`, `.vendored/.version`) and create `configs/` and `pkg/` directories
2. **Config migration**: The first time `.vendored/install` runs, it automatically splits the monolithic `config.json` vendors dict into individual `configs/<vendor>.json` files
3. **Manifests generated on update**: The next time each vendor is updated via `.vendored/install`, a manifest will be generated and stored. Until then, `check` falls back to config `protected` patterns
4. **Vendor `install.sh` updates**: Vendor repos should update their `install.sh` to use `VENDOR_INSTALL_DIR` for file placement and write a manifest to `$VENDOR_MANIFEST`. The framework still runs old install.sh scripts — they just won't benefit from the new directory layout until updated

### Migrating vendor file layout

To move a vendor's files from dotdirs (e.g., `.my-tool/`) into `.vendored/pkg/my-tool/`:

```bash
python3 .vendored/remove my-tool --force
python3 .vendored/install owner/my-tool
```

This requires the vendor repo to have updated its `install.sh` to use `$VENDOR_INSTALL_DIR`. See `docs/vendor-install-dir-guide.md` for details.
