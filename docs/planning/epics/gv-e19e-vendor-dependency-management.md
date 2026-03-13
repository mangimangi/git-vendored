# gv-e19e: Vendor Dependency Management

**Status:** Planning
**Priority:** P2
**Epic:** gv-e19e

## Summary

Extend the vendor contract to support **vendor-to-vendor dependencies**. Vendors declare which other vendors they require via `deps.json`, and the framework checks (and optionally installs) those dependencies during the install flow.

---

## Motivation

Today, if vendor A requires vendor B to function (e.g., a tool that depends on `git-semver` for version management), there's no way to express or enforce this. The failure mode is silent: vendor A installs fine, then breaks at runtime because vendor B isn't present.

This creates friction in two places:

- **Consumer operators** add a vendor and it doesn't work because they don't know about its dependencies. There's no error message pointing them to the missing vendor — they have to debug it themselves.
- **Vendor authors** can't formally express what their tool needs. They resort to README notes like "make sure you also install X" which are easy to miss.

Dependency management closes this gap by making vendor dependencies explicit, checkable, and optionally auto-installable.

---

## Design

### Vendor Contract Extension

Vendors declare dependencies via an **optional `deps.json`** at repo root, alongside `install.sh` and `VERSION`:

```
vendor-repo/
  install.sh      # (required) installs files, writes manifest
  VERSION          # (or GitHub releases) version discovery
  deps.json        # (optional, NEW) declares vendor dependencies
```

#### `deps.json` Format

```json
{
  "git-semver": {
    "repo": "mangimangi/git-semver"
  },
  "pearls": {
    "repo": "mangimangi/pearls"
  }
}
```

Each key is the vendor name. **Vendor names must match the repo name** (the segment after `/` in `owner/repo`). The `repo` field is the `owner/repo` needed for auto-install.

**Why JSON, not plain text?** Auto-install needs the `repo` for each dependency. A plain text list of names wouldn't carry enough info. JSON is also consistent with per-vendor configs.

**Why `deps.json` and not part of the vendor config?** Dependencies must be checked *before* running `install.sh`. The consumer's per-vendor config (`configs/<vendor>.json`) is written by the framework *after* install succeeds. A separate file in the vendor repo allows the framework to download and inspect deps pre-install.

**Why not a broader `vendor.json` metadata file?** We considered bundling deps with other pre-install metadata (contract version, min framework version). Decision: start narrow with deps only. A broader metadata file can be introduced later if needed — renaming is cheaper than over-designing now.

### Vendor Naming Convention

**Vendor names must match repo names.** The vendor name is derived from the repo: `mangimangi/git-semver` → vendor name `git-semver`. This is enforced for dependency resolution — `deps.json` keys must match the repo-derived name of the dependency.

The `--name` CLI flag on install is not supported for vendors that are dependencies of other vendors. If a consumer installs a vendor under a custom name, dep resolution will not find it.

### Framework Behavior

#### Dependency Resolution Flow

During `.vendored/install`, after pre-validation but before running `install.sh`:

```
1. Download deps.json from vendor repo at target ref (if exists)
2. Parse dependency list
3. For each dependency:
   a. Check if vendor is installed:
      - .vendored/configs/<dep>.json exists, OR
      - .vendored/manifests/<dep>.version exists
   b. If installed → satisfied
   c. If missing → apply dependency_mode:
      - "error"   → collect missing deps, fail with clear message
      - "warn"    → log warning, continue with install
      - "install" → auto-install the missing dep (recursive)
      - "skip"    → don't check deps at all
4. If all deps satisfied (or mode allows continuing) → run install.sh
```

#### Integration Points

Dependency checking hooks into two places in `templates/install`:

1. **`install_new_vendor()`** — after `check_repo_exists()` + `check_install_sh()`, before `download_and_run_install()`
2. **`install_existing_vendor()`** — before `download_and_run_install()` (deps may change between versions)

New functions:

| Function | Purpose |
|----------|---------|
| `download_deps(repo, ref, token)` | Download and parse `deps.json` from vendor repo (returns dict or None) |
| `check_deps(deps)` | Check which deps are installed via per-vendor config or manifest existence |
| `resolve_deps(deps, token, mode, installing_set)` | Apply dependency_mode: error/warn/install/skip |

#### Auto-Install (dependency_mode: "install")

When a missing dep is detected and mode is `"install"`:

1. Framework calls `install_new_vendor(dep_repo, "latest", token)` for the missing dep
2. This is recursive — the dep's own `deps.json` is checked, and *its* deps are resolved first
3. **Cycle detection** via an `installing_set` parameter passed through the call chain:
   - Before installing dep X, check if X is already in the set
   - If yes → error: "Circular dependency detected: A → B → A"
   - If no → add X to set, install, remove X from set

### Dependency Mode Configuration

**Per-vendor setting** in `.vendored/configs/<vendor>.json` under the `_vendor` key:

```json
{
  "_vendor": {
    "repo": "mangimangi/my-tool",
    "install_branch": "chore/install-my-tool",
    "dependency_mode": "install"
  }
}
```

**CLI override** (highest priority):

```bash
python3 .vendored/install owner/repo --deps=error
python3 .vendored/install owner/repo --deps=warn
python3 .vendored/install owner/repo --deps=install
python3 .vendored/install owner/repo --deps=skip
```

| Mode | Behavior |
|------|----------|
| `error` | Fail with list of missing deps (default — safe) |
| `warn` | Log warnings for missing deps, continue install |
| `install` | Auto-install missing deps, then install the vendor |
| `skip` | Don't check deps at all |

**Resolution order:** CLI flag (`--deps`) > per-vendor `_vendor.dependency_mode` > default (`error`)

For `install all`, each vendor's own `dependency_mode` is used unless the CLI flag overrides globally.

### CI / Workflow Integration

The `install-vendored.yml` workflow runs `.vendored/install all` on schedule. During `all` mode:

- Each vendor's deps are checked before its install.sh runs
- Since `all` mode iterates all registered vendors, deps are likely already installed
- For new deps introduced by a vendor update: the workflow should use `--deps=install` so updates don't fail due to newly-required deps

The workflow template should pass `--deps=install` by default for automated runs.

### Reverse Dependency Check on Remove

When running `.vendored/remove <vendor>`, the framework should check if any other installed vendor depends on the one being removed:

```
$ python3 .vendored/remove git-semver
Warning: The following vendors depend on git-semver:
  - my-tool (declared in deps.json)
Proceed anyway? [y/N]
```

This uses cached `.vendored/manifests/<vendor>.deps` files (written during install) to perform reverse-dep lookups without re-downloading deps.json from vendor repos.

### Manifest Extension

When deps are resolved during install, store them:

```
.vendored/manifests/
  my-tool.files       # (existing) installed file list
  my-tool.version     # (existing) installed version
  my-tool.deps        # (NEW) resolved dependency list
```

Format of `.deps` file (plain text, one vendor name per line):

```
git-semver
pearls
```

This enables reverse-dep lookups without re-downloading deps.json from vendor repos. Updated on every install, so staleness is bounded.

---

## Examples

### Vendor declares dependencies

Vendor repo `mangimangi/my-tool` has:

```json
// deps.json
{
  "git-semver": {
    "repo": "mangimangi/git-semver"
  }
}
```

### Consumer installs with error mode (default)

```bash
$ python3 .vendored/install mangimangi/my-tool

Adding mangimangi/my-tool v1.0.0...
Checking dependencies...
::error::Missing required vendor dependencies for my-tool:
  - git-semver (mangimangi/git-semver)

Install missing deps first:
  python3 .vendored/install mangimangi/git-semver
Or use --deps=install to auto-install.
```

### Consumer installs with auto-install

```bash
$ python3 .vendored/install mangimangi/my-tool --deps=install

Adding mangimangi/my-tool v1.0.0...
Checking dependencies...
  git-semver: not installed, auto-installing...
  Adding mangimangi/git-semver v2.1.0...
  Added vendor: git-semver (3 files)
Dependencies satisfied.
Added vendor: my-tool (5 files)
```

### Per-vendor dependency mode

```json
// .vendored/configs/my-tool.json
{
  "_vendor": {
    "repo": "mangimangi/my-tool",
    "install_branch": "chore/install-my-tool",
    "dependency_mode": "install"
  }
}
```

With this config, `python3 .vendored/install my-tool` auto-installs deps without needing `--deps=install` on the CLI.

### CI workflow auto-installs new deps on update

```bash
$ python3 .vendored/install all --deps=install

my-tool: 1.0.0 -> 2.0.0
  Checking dependencies...
  pearls: not installed, auto-installing...
  Adding mangimangi/pearls v0.3.0...
  Dependencies satisfied.
git-semver: already at v2.1.0, skipping
```

---

## Decisions

1. **Version constraints** — **Deferred.** v1 is presence-only (is the dep installed?). Version constraints (e.g., `>=1.0.0`) add semver comparison complexity and can be added as a follow-up once the core flow is proven.

2. **Topological sort for `install all`** — **Yes.** The framework will topologically sort vendors by their dependency graph before iterating. This prevents ordering failures where a dep is listed after the vendor that needs it.

3. **Vendor naming** — **Enforced.** Vendor names must match repo names (`owner/repo` → vendor name is `repo`). `deps.json` keys reference vendors by this canonical name. The `--name` override is not supported for deps.

4. **Dependency mode** — **Per-vendor.** Stored in `_vendor.dependency_mode` in per-vendor config files. CLI `--deps=X` overrides. Default is `error` (fail-fast).

5. **Dep presence check** — Uses v2 per-vendor config structure: checks `.vendored/configs/<dep>.json` or `.vendored/manifests/<dep>.version` existence. Does not reference monolithic `config.json`.

6. **Dep caching** — Cache in `.vendored/manifests/<vendor>.deps` after install. Updated on every install so staleness is bounded. Used for reverse-dep checks on remove (no re-download needed).

7. **`deps.json` scope** — Deps only. No broader vendor metadata file. Can be extended or replaced later if pre-install metadata needs grow.

8. **All deps required** — No optional/soft dependencies in v1. All declared deps are required. Optional deps can be a future extension.

---

## Non-Goals

- **System-level dependencies** (jq, python3, curl) — out of scope. This is vendor-to-vendor only.
- **Version pinning** — consumers can't pin a dep to a specific version via this mechanism. They install deps at whatever version they want; this feature only checks presence.
- **Dependency resolution conflicts** — no diamond dependency resolution. If A needs semver and B needs semver, there's only one semver installed anyway. Version conflicts (when version constraints are added) would be a future concern.
- **Broader vendor metadata file** — `deps.json` is deps-only. Contract version, min framework version, etc. are out of scope for this epic.

---

## Backwards Compatibility

- **`deps.json` is optional** — vendors without it work exactly as before. Zero breaking changes.
- **Consumers without `dependency_mode` in vendor config** — default to `"error"`, which is safe (fail-fast on missing deps rather than silently proceeding).
- **Existing vendors adding deps** — on next update via `install all`, the framework downloads deps.json for the first time and applies the dependency_mode logic. If deps are already installed (common case), no action needed.

---

## Task Breakdown

### 1. Core dep resolution in `templates/install`

- Add `download_deps(repo, ref, token)` — download and parse `deps.json` from vendor repo (returns dict or None if no deps.json)
- Add `check_deps(deps)` — check which deps are installed via `.vendored/configs/<dep>.json` or `.vendored/manifests/<dep>.version` existence
- Add `resolve_deps(deps, token, mode, installing_set)` — apply dependency_mode logic (error/warn/install/skip)
- Wire into `install_new_vendor()` and `install_existing_vendor()` — call resolve_deps before `download_and_run_install()`
- Add `--deps` CLI flag with error/warn/install/skip values
- Read `dependency_mode` from per-vendor config `_vendor.dependency_mode` as default
- Cycle detection via `installing_set` parameter

### 2. Topological sort for `install all`

- Build dependency graph from all registered vendors' cached `.deps` files (and/or download deps.json for each)
- Topological sort with cycle detection
- Iterate vendors in sorted order instead of config order

### 3. Cache resolved deps in manifests

- After successful install, write `.vendored/manifests/<vendor>.deps` (one vendor name per line)
- Update `.vendored/remove` to also delete `.deps` file during uninstall

### 4. Reverse-dep check on remove

- In `.vendored/remove`, before deleting files, scan all `.vendored/manifests/*.deps` for references to the vendor being removed
- If found: warn with list of dependent vendors, require `--force` or confirmation to proceed

### 5. Update install-vendored.yml workflow

- Pass `--deps=install` in the workflow so automated runs auto-install new deps
- Ensure auto-installed deps are included in the PR's commit

### 6. Tests

- Unit tests for dep resolution logic (presence check, cycle detection, topological sort)
- Integration test: vendor with deps.json, dep missing → error mode fails, install mode succeeds
- Integration test: circular dependency → error with clear message
- Integration test: `install all` respects topological order
- Test per-vendor dependency_mode override
- Test CLI `--deps` flag overrides per-vendor config
