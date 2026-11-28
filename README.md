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
curl -fsSL https://raw.githubusercontent.com/mangimangi/git-vendored/v0.0.28/install.sh | bash -s 0.0.28
```

This creates:
- `.vendored/install` — add new vendors or update existing ones
- `.vendored/check` — enforce file protection rules
- `.vendored/remove` — cleanly uninstall a vendor
- `.vendored/audit` — validate configs against vendor schemas
- `.vendored/feedback` — show support and bug-reporting info for installed vendors
- `.vendored/config.json` — framework-level config (legacy vendor registry)
- `.vendored/configs/` — per-vendor config files (`<vendor>.json`)
- `.vendored/pkg/` — vendor-installed files (`<vendor>/`)
- `.vendored/manifests/` — manifest storage (file lists + versions)
- `.vendored/lib/` — shared helper modules
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

### Workflow files and `VENDOR_PAT`

An install can change files under `.github/workflows/` (a vendor's workflows). The workflow's own `GITHUB_TOKEN` may not push those, so in `--pr` mode:

- **With `VENDOR_PAT` set**, the workflow files the install wrote or removed stay in the commit, and the branch is pushed with `VENDOR_PAT` (sent as an HTTP header on the `git push` command line, never printed or written to `.git/config`). The PR itself is still opened with `GITHUB_TOKEN`. If the push is refused because the token may not write workflows, the install leaves the workflow files out, pushes the rest and still opens the PR.
- **Without `VENDOR_PAT`**, workflow files are left out as before.

Whenever workflow files are left out, the PR description lists them and says what to run and commit on the branch: for git-cicd, `.vendored/pkg/git-cicd/git-cicd generate`; for other vendors, `python3 .vendored/install <vendor> --force` with a token that may write workflows.

To carry workflow files, `VENDOR_PAT` needs, on the consuming repository: **Contents** read/write, **Pull requests** read/write and **Workflows** write (fine-grained token), or the `repo` and `workflow` scopes (classic token). No token value is printed in any log.

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

`VENDOR_INSTALL_DIR` is set for non-dogfood vendors. Vendors SHOULD install their primary files under this directory but MAY install to other paths (workflows) when the target system requires specific locations. If not set, the vendor falls back to its original file layout.

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

On every install, add or update, `.vendored/manifests/<vendor>.files` is replaced by the manifest that install wrote, so it always lists the files of the installed version.

### Registry

A vendor's registry lives in `.vendored/manifests/<vendor>.registry`. `install.sh` ships it as a `_vendor` block in `.vendored/configs/<vendor>.json` (or as its entry under `vendors` in the legacy `.vendored/config.json`, or by writing the `.registry` file itself). The framework moves it into the `.registry` file and strips `_vendor` from the config.

On every install, add or update, the registry is that of the installed version:

| Owned by | Fields | On an update |
|----------|--------|--------------|
| the vendor | `repo`, `install_branch`, `protected`, `allowed`, `dogfood`, `support` | replaced by what the installed version ships; a field it no longer ships is removed (`repo` keeps its old value if missing) |
| the repository | `private`, `automerge`, `dependency_mode` | kept as they are |

The repository's own `.vendored/configs/<vendor>.json` is never overwritten: its keys keep their values (a key `install.sh` adds is kept). If the installed version ships no registry at all, the existing one is kept unchanged. So when a vendor changes which files it allows (git-cicd v0.0.4 allows `.github/workflows/git-cicd-*.yml` where v0.0.2 allowed `.github/workflows/git-cicd.yml`), `.vendored/check` uses the new rules as soon as the install is merged.

### Dependencies (`deps.json`)

A vendor repo may include a `deps.json` at its root to declare dependencies on other vendors. When a consumer installs the vendor with `--deps=install`, missing dependencies are automatically installed.

```json
{
  "pearls": {"repo": "mangimangi/pearls", "private": true},
  "some-tool": {"repo": "owner/some-tool"}
}
```

Each key is the dependency's vendor name, and the value is an object with:

| Field | Required | Description |
|-------|----------|-------------|
| `repo` | yes | GitHub repository (`owner/name`) |
| `private` | no | If `true`, the dependency requires `VENDOR_PAT` for access. When omitted, inherits the parent vendor's `--private` flag |

Usage:

```bash
# Auto-install dependencies
python3 .vendored/install owner/my-tool --deps=install

# Private vendor with private dependencies
VENDOR_PAT=<token> python3 .vendored/install owner/my-tool --private --deps=install
```

Dependency modes (`--deps`):
- `error` (default) — exit if any dependencies are missing
- `warn` — print a warning and continue
- `skip` — ignore dependencies entirely
- `install` — auto-install missing dependencies

## Protection Rules

`.vendored/check` runs on every PR via `check-vendor.yml`:

- Files listed in `.vendored/manifests/<vendor>.files` cannot be modified
- Exception: files matching `allowed` patterns in config can be edited
- Exception: PRs from branches matching `install_branch` prefix bypass checks for that vendor
- Fallback: for v1 vendors without manifests, config `protected` patterns are used

This prevents accidental edits to vendor-managed files while allowing the automated update workflow to function.

### Running the check as a git-cicd job

In a repository that uses [git-cicd](https://github.com/mangimangi/git-cicd), the check can run as a job instead of through `check-vendor.yml`. Declare it in `.vendored/configs/git-cicd.json` and run `.vendored/pkg/git-cicd/git-cicd generate`:

```json
"vendor-check": {"on": ["open"], "branches": ["**"], "paths": ["**"], "steps": [".vendored/check"]}
```

No wrapper script is needed. The source branch (which decides whether an `install_branch` is let through) is read in this order: `CICD_SOURCE_BRANCH` (git-cicd sets it for a step, in Actions and locally), then `GITHUB_HEAD_REF` (a GitHub pull request), then the current git branch; an empty variable counts as unset. Without `--base`, the base is `origin/$GITHUB_BASE_REF`, else `origin/main`.

`--base <ref>` reads only the commits in `<ref>..HEAD`. When the working tree or the index holds changes outside that range, the check prints one line saying so (`Note: N uncommitted or staged file(s) not checked ...; run with --staged to check staged files`); the note does not change the exit code. `--staged` checks the index instead (no note is printed in that mode).

## Directory Layout

```
.vendored/
  install                        # framework command: add/update vendors
  check                          # framework command: file protection checks
  remove                         # framework command: uninstall vendors
  audit                          # framework command: validate configs against schemas
  feedback                       # framework command: vendor support/bug-report info
  config.json                    # framework-level config (legacy)
  lib/                           # shared helper modules
    vendor-helpers.sh
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
    my-tool.schema               # config schema (if vendor provides one)
    my-tool.deps                 # dependency list (if vendor declares deps)
    pearls.files
    pearls.version
```

> **Note:** Session-hook orchestration (`.vendored/hooks/vendored-session.sh`,
> `--setup-hooks`, agent session hooks) was removed in phase 4.5. Target repos
> now use the image-baked model where health checks run via `session.sh` in the
> medici image. git-vendored's scope is now limited to host-side tool installs
> (git-semver, git-dogfood) and file-protection checks.

Vendor data files (e.g. `.pearls/issues.jsonl`, `.semver/.version`) remain in their original `.<vendor>/` directories — these are vendor-owned, not framework-managed. After migration, dot-directories become data-only zones. See `docs/vendor-install-dir-guide.md` for details.

Manifest `.files` are plain text, one-path-per-line. Easy to `cat`, `diff`, `grep`.

## Config Schemas

Vendor repos can ship a `templates/config.schema` file to declare the expected fields in their consumer config. During install, the framework copies it to `.vendored/manifests/<vendor>.schema`.

### Schema Format

```json
{
  "vendor": "<vendor-name>",
  "fields": {
    "field_name": {
      "required": true,
      "type": "string",
      "description": "Human-readable description"
    }
  }
}
```

Top-level fields only. Types: `string`, `number`, `boolean`, `array`, `object`.

### Audit Command

Run `.vendored/audit` to validate all consumer configs against installed schemas:

```bash
python3 .vendored/audit
```

Reports required-missing fields as errors (non-zero exit), unknown/misplaced fields as warnings (zero exit).

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

## Developing git-vendored

git-vendored's own pull request checks run through [git-cicd](https://github.com/mangimangi/git-cicd), installed at `.vendored/pkg/git-cicd/`. The jobs are declared in `.vendored/configs/git-cicd.json`:

- `test` (Unit Tests): `ci/setup.sh` installs the Python floor that `requires-python` in `pyproject.toml` names, plus `pytest` and `pyyaml`, plus `coverage` (with a startup hook so subprocess runs are measured), into a virtualenv; `ci/test.sh` runs `pytest tests/ -v` under coverage with it and prints the line coverage of the six shipped Python scripts (`templates/install`, `templates/check`, `templates/remove`, `templates/audit`, `templates/feedback`, `validate`): `Stmts` executable lines, `Miss` lines no test ran, `Cover` the percentage, `Missing` their line numbers. Scripts a test starts as a subprocess are counted too. For one file: `python -m coverage report --include=templates/check` after a run. The job fails when the total or any one of those files is below 99% (`fail_under` in `pyproject.toml`, and a per-file check in `ci/test.sh`): a change that lowers coverage below 99% fails the verdict, so it adds its tests in the same pull request. A line is excluded (`# pragma: no cover`) only when no test can reach it, with the reason on the line. After pytest, `ci/test.sh` runs the bats tests in `tests/bats/` for `install.sh`, `templates/lib/vendor-helpers.sh` and the `ci/` scripts (`ci/setup.sh` provides a pinned bats-core when none is on `PATH`); a failing bats test fails the job. Run them alone with `bats tests/bats/`.
- `vendor-check` (Vendor Check): `ci/vendor-check.sh` runs `.vendored/check` against the change's base.

Documents and tracker records (`*.md`, `docs/**`, `.pearls/issues.jsonl`, `.pearls/docs/**`, `.madreperla/sessions.jsonl`, ...) are in `needs_nothing`, so a change to them alone needs no job. No Python version is written in any workflow: `pyproject.toml` is the one place it is declared.

Run the checks locally the way CI runs them:

```bash
.vendored/pkg/git-cicd/git-cicd check --setup   # first run: setup, then the jobs
.vendored/pkg/git-cicd/git-cicd check           # later runs reuse the virtualenv
```

`.github/workflows/git-cicd-open.yml` is generated: after changing the config or upgrading git-cicd, run `.vendored/pkg/git-cicd/git-cicd generate` and commit what it writes (`git-cicd verify` checks it matches).
