# git-vendored

Automated vendor install control for repo-embedded tools via GitHub workflows. Register external tools (like linters, CI helpers, or workflow utilities) in your repo, and git-vendored keeps them updated automatically — with PR-based updates, file protection, and private repo support.

## How It Works

git-vendored implements a **vendor contract**:

1. A vendor repo provides an `install.sh` at its root
2. `install.sh` downloads its files into the consumer repo and self-registers in `.vendored/config.json`
3. Versions are discovered via GitHub Releases (tag) or a `VERSION` file fallback
4. A GitHub workflow runs on a schedule (or manually), checks for updates, and opens PRs

## Quick Start

Bootstrap git-vendored in a new repo:

```bash
# Download and run the bootstrap installer
curl -fsSL https://raw.githubusercontent.com/mangimangi/git-vendored/v0.1.0/install.sh | bash -s 0.1.0
```

This creates:
- `.vendored/add` — add new vendors
- `.vendored/update` — update registered vendors
- `.vendored/check` — enforce file protection rules
- `.vendored/config.json` — vendor registry
- `.github/workflows/install-vendored.yml` — automated update workflow
- `.github/workflows/check-vendor.yml` — PR protection checks

## Adding a Vendor

```bash
python3 .vendored/add owner/repo-name
```

This will:
1. Verify the repo has `install.sh` and a resolvable version
2. Run the vendor's `install.sh`
3. Validate that it self-registered in config with required fields

Use `--name` to override the vendor key:

```bash
python3 .vendored/add owner/repo-name --name my-custom-name
```

## How Updates Work

The `install-vendored.yml` workflow runs weekly (Mondays 9am UTC) or on manual dispatch:

```
schedule/manual trigger → vendored/update → detect changes → create PR
```

Update a specific vendor manually:

```bash
# From GitHub Actions (workflow_dispatch)
# Or locally:
python3 .vendored/update my-vendor --version 2.0.0
python3 .vendored/update all  # update all vendors
```

## Configuration

`.vendored/config.json` holds the vendor registry:

```json
{
  "vendors": {
    "my-tool": {
      "repo": "owner/my-tool",
      "install_branch": "chore/install-my-tool",
      "protected": [".my-tool/**", ".github/workflows/my-tool.yml"],
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
| `protected` | yes | Glob patterns of vendor-managed files (cannot be edited in PRs) |
| `allowed` | no | Glob patterns of protected files that users *can* edit |
| `private` | no | If `true`, requires `VENDOR_PAT` secret for access |
| `automerge` | no | If `true`, auto-merge vendor update PRs (default: `false`) |
| `dogfood` | no | If `true`, included in dogfood workflow |

## Vendor Contract

A vendor repo must provide:

1. **`install.sh` at repo root** — accepts a version argument, downloads its files, and self-registers in `.vendored/config.json`
2. **Version discovery** — either GitHub Releases (tags like `v1.0.0`) or a `VERSION` file at repo root
3. **Self-registration** — `install.sh` must add/update its entry in `.vendored/config.json` with at minimum: `repo`, `protected`, `install_branch`

## Protection Rules

`vendored/check` runs on every PR via `check-vendor.yml`:

- Files matching `protected` patterns cannot be modified
- Exception: files also matching `allowed` patterns can be edited
- Exception: PRs from branches matching `install_branch` prefix bypass checks for that vendor

This prevents accidental edits to vendor-managed files while allowing the automated update workflow to function.
