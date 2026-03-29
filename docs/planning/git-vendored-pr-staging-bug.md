# git-vendored: PR staging misses pkg/ files

> **Status:** Open. Discovered during medici workspace setup.

## Problem

The `--pr` codepath in `.vendored/install` creates a PR that is missing the actual vendor package files (`.vendored/pkg/<vendor>/`). Manifests, configs, and hooks are committed, but the code that runs (`prl.py`, `AGENTS.md`, hook scripts, etc.) is not.

This was discovered in [medici PR #5](https://github.com/mangimangi/medici/pull/5) — the GHA install of madreperla (with pearls as a dependency) produced a PR with 12 files, none from `.vendored/pkg/`.

## Evidence

**GHA run:** [actions/runs/23695125547](https://github.com/mangimangi/medici/actions/runs/23695125547/job/69029072914)

The install logs show the files were written:
```
Downloading prl.py...
Installed prl.py v0.2.36
Updated .vendored/pkg/pearls/AGENTS.md
Updated .vendored/pkg/pearls/hooks/
```

The manifest (`pearls.files`) correctly lists 9 files including `pkg/` paths. But the PR diff only contains manifests, configs, `.pearls/`, and `.claude/` files.

**Staging code** (`.vendored/install` line 980):
```python
subprocess.run(["git", "add", "-A"], check=True, capture_output=True)
```

`git add -A` should pick up everything. The files were either not on disk when staging ran, or were written to a different location.

## Likely cause

The vendor's `install.sh` runs in a subprocess. If `fetch_file` (the helper that downloads from GitHub) writes files relative to a different working directory, or if there's a timing issue with the dependency chain (pearls installs, then madreperla installs and the coordinator re-execs), the files could be written but not present in the working tree at commit time.

Worth checking:
1. Does `install.sh` use `$PROJECT_DIR` or rely on `pwd`?
2. Does the `--deps=install` flow for pearls run before or after the main vendor's `create_pull_request`?
3. Is there a self-bootstrap re-exec (`--post-install-only`) that loses the working tree state?

## Impact

Any consumer repo installing a vendor via GHA gets a broken install — manifests say the vendor is installed but the actual code is missing. The post-install stamp matches the version, so subsequent session hooks won't detect the gap.

## Target repo

git-vendored (framework bug in the install coordinator)
