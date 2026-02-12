# gv-9d4e: Vendor Contract Validation GHA

**Status:** Planning
**Priority:** P2
**Epic:** gv-9d4e

## Summary

Expose the vendor contract checks (currently embedded in add/install) as a standalone validation tool and GitHub Action workflow. Allows anyone to answer "does repo XYZ validly implement the git-vendored vendor contract?" without actually installing the vendor.

---

## Motivation

Today, the only way to discover whether a repo properly implements the vendor contract is to run `.vendored/install <owner/repo>` — which actually installs the vendor. The pre-validation checks (`check_repo_exists`, `check_install_sh`) live inline in `templates/install` (lines 167-190) and are not reusable outside that flow.

This creates friction in several scenarios:

- **Vendor authors** want to verify their `install.sh` is correct before publishing a release, but there's no way to check without a consumer repo to test against.
- **Consumer operators** want to vet a vendor before adding it — "does this repo even implement the contract?" Currently requires reading the source or just trying `install` and hoping for the best.
- **CI for vendor repos** — a vendor repo could run this as part of its own CI to prevent shipping a broken contract (e.g., install.sh that doesn't write a manifest).

The validation logic already exists in pieces across `templates/install`. This epic extracts it into a standalone tool and wraps it in a GHA for easy access.

---

## Design

### Scope

The validation lives in the **git-vendored repo only** — it is not vendored to consumers. Consumers don't need it; they use `.vendored/install` which already runs the pre-checks inline. This is a development/evaluation tool for the git-vendored project itself.

### Script: `validate` (repo root)

A standalone Python script at the repo root. Repo root (not `templates/`) because it's not installed into consumer repos.

```
Usage:
    python3 validate <owner/repo> [--version <version>]

Environment:
    GH_TOKEN - Auth token for GitHub API access
```

### Checks

Eight checks covering the full v2 vendor contract:

| # | Check | Method | Fail behavior |
|---|-------|--------|---------------|
| 1 | Repo exists and is accessible | `gh api repos/{repo}` | Fail fast |
| 2 | `install.sh` exists at repo root | `gh api repos/{repo}/contents/install.sh` | Fail fast |
| 3 | Version resolvable | Releases API, then VERSION file fallback | Fail fast (dry-run needs a version) |
| 4 | Valid shebang | Download install.sh, check first line for `#!/bin/bash` or `#!/usr/bin/env bash` | Continue |
| 5 | Syntax valid | `bash -n` on downloaded script | Continue |
| 6 | Dry-run succeeds | Run install.sh in temp dir with v2 contract env vars, check exit code 0 | Continue |
| 7 | Manifest written | Check install.sh wrote to `$VENDOR_MANIFEST` | Continue |
| 8 | Manifest files exist | Verify every path in manifest exists on disk in the sandbox | Continue |

Checks 1-3 are **fail-fast** — if the repo doesn't exist or has no install.sh, there's nothing else to check. Checks 4-8 are **collect-and-report** — run all of them and report the full picture.

### Dry-run sandbox

The dry-run (checks 6-8) runs install.sh in a temporary directory with the v2 contract env vars set:

| Env var | Value |
|---------|-------|
| `VENDOR_REPO` | The target `owner/repo` |
| `VENDOR_REF` | `v{resolved_version}` |
| `VENDOR_MANIFEST` | Temp file path for manifest output |
| `VENDOR_INSTALL_DIR` | `.vendored/pkg/{vendor_name}/` (relative to sandbox) |
| `GH_TOKEN` | Inherited from caller |

The sandbox is cleaned up after validation regardless of outcome.

### Output format

```
Validating vendor contract: owner/some-tool

  [PASS] Repo exists
  [PASS] install.sh exists
  [PASS] Version resolvable (1.2.3)
  [PASS] Valid shebang (#!/bin/bash)
  [PASS] Syntax valid (bash -n passed)
  [PASS] Dry-run install (exit code 0)
  [PASS] Manifest written (8 files)
  [PASS] Manifest files exist (all files found on disk)

Result: PASS (8/8 checks passed)
```

On failure:

```
  [FAIL] Manifest written -- install.sh did not write to $VENDOR_MANIFEST

Result: FAIL (1/8 checks failed)
```

Exit code 0 on all-pass, 1 on any failure.

### GHA workflow: `.github/workflows/validate-vendor.yml`

A `workflow_dispatch` workflow with two inputs:

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `repo` | yes | — | `owner/repo` to validate |
| `version` | no | `latest` | Version to validate against |

Permissions: `contents: read` only.

Inputs are passed through env vars (not shell interpolation) to prevent injection:

```yaml
- name: Validate vendor contract
  env:
    GH_TOKEN: ${{ github.token }}
    VALIDATE_REPO: ${{ inputs.repo }}
    VALIDATE_VERSION: ${{ inputs.version }}
  run: python3 validate "$VALIDATE_REPO" --version "$VALIDATE_VERSION"
```

---

## Code reuse vs. standalone

Two options considered:

1. **Import from `templates/install`** — The check functions exist there already, but `templates/install` has no `.py` extension and is designed as a standalone script with its own `main()`. Importing from it would require either renaming it or adding sys.path hacks.

2. **Standalone with extracted logic** — Replicate the check functions in `validate`. The functions are small (5-15 lines each) and unlikely to drift since the contract itself is stable.

**Decision:** Standalone. The duplication is minimal and keeps `validate` self-contained with zero coupling to the vendored templates. If the contract checks grow complex enough to warrant sharing, a future refactor can extract them into a shared lib.

---

## Task Breakdown

### gv-9d4e.1 — Create `validate` script

- Standalone Python script at repo root
- Implement all 8 checks listed above
- `ValidationResult` class for collecting pass/fail with summary
- `--version` flag (default `latest`)
- Auth via `GH_TOKEN` / `GITHUB_TOKEN` env vars
- Exit code 0/1

### gv-9d4e.2 — Create `validate-vendor.yml` workflow

- `workflow_dispatch` trigger with `repo` and `version` inputs
- Checkout git-vendored, run `python3 validate`
- Env-var-based input passing (no shell interpolation of inputs)
- `contents: read` permissions only

---

## Open Questions

1. **Should validation also check for v1 contract compliance?** The v1 contract has install.sh self-register in config.json instead of writing a manifest. We could add a check that detects v1-style config writes and report it as a warning ("v1 contract detected — consider upgrading to v2"). Deferred for now.

2. **Should vendor repos be able to run this in their own CI?** Today you'd have to `git clone git-vendored` to get the `validate` script into a vendor repo's CI. A future option would be publishing it as a reusable GHA (`uses: mangimangi/git-vendored/validate@v1`). Out of scope for this epic but worth considering.

3. **Private repo support** — The GHA uses `github.token` which only has access to public repos. Validating a private vendor repo would require passing a PAT. Should we add a `token` secret input? Probably yes, matching the pattern in `install-vendored.yml`.
