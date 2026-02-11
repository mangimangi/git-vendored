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
- `.vendored/config.json` — vendor registry
- `.vendored/manifests/` — manifest storage (file lists + versions)
- `.github/workflows/install-vendored.yml` — automated update workflow
- `.github/workflows/check-vendor.yml` — PR protection checks

## Adding a Vendor

```bash
python3 .vendored/install owner/repo-name
```

This will:
1. Verify the repo has `install.sh` and a resolvable version
2. Run the vendor's `install.sh` with `VENDOR_REPO`, `VENDOR_REF`, and `VENDOR_MANIFEST` set
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

`.vendored/config.json` holds the vendor registry:

```json
{
  "vendors": {
    "my-tool": {
      "repo": "owner/my-tool",
      "install_branch": "chore/install-my-tool",
      "allowed": [".my-tool/config.json"],
      "private": false,
      "automerge": false,
      "dogfood": false
    }
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `repo` | yes | GitHub repository (`owner/name`) |
| `install_branch` | yes | Branch prefix for vendor update PRs |
| `allowed` | no | Glob patterns of vendor-managed files that users *can* edit |
| `private` | no | If `true`, requires `VENDOR_PAT` secret for access |
| `automerge` | no | If `true`, auto-merge vendor update PRs (default: `false`) |
| `dogfood` | no | If `true`, included in dogfood workflow |

**Note:** The `protected` field is no longer used in the config. Protection rules are derived automatically from manifests at `.vendored/manifests/<vendor>.files`. For v1 vendors without manifests, `check` falls back to config `protected` patterns for backwards compatibility.

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
| `GH_TOKEN` | Auth token (when available) |

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

## Manifest Storage

```
.vendored/manifests/
  git-vendored.files      # one filepath per line
  git-vendored.version    # single line: version string
  my-tool.files
  my-tool.version
```

Plain text, one-path-per-line for `.files`. Easy to `cat`, `diff`, `grep`.

## Migrating from v1 to v2

If you're upgrading from a v1 git-vendored installation:

1. **Re-bootstrap**: Run the latest `install.sh` — it will clean up deprecated files (`.vendored/add`, `.vendored/update`, `.vendored/.version`)
2. **Manifests generated on update**: The next time each vendor is updated via `.vendored/install`, a manifest will be generated and stored. Until then, `check` falls back to config `protected` patterns.
3. **Config `protected` field**: No longer needed once manifests exist. It will be ignored when a manifest is present but serves as backwards-compatible fallback for vendors not yet updated.
4. **Vendor `install.sh` updates**: Vendor repos should update their `install.sh` to read `VENDOR_REF`/`VENDOR_REPO` env vars and write a manifest to `$VENDOR_MANIFEST`. The framework still runs v1 install.sh scripts — they just won't benefit from manifest-driven protection until updated.
