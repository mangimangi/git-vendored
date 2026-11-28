# git-vendored

Automated vendor install control for repo-embedded tools via GitHub workflows. Register external tools (like linters, CI helpers, or workflow utilities) in your repo, and git-vendored keeps them updated automatically — with PR-based updates, file protection, and private repo support.

## How It Works

git-vendored implements a **manifest-driven vendor contract**:

1. A vendor is a git repository with version tags and an `install.sh` at its root
2. The framework fetches it with git at the version's tag and runs `install.sh` from that checkout, with context via environment variables
3. `install.sh` copies its files (from the checkout, or by downloading them) and writes a manifest listing every file it installed
4. The framework stores the manifest, tracks versions, and derives file protection rules
5. A GitHub workflow runs on a schedule (or manually), checks for updates, and opens PRs

## Quick Start

Bootstrap git-vendored in a new repo, from its root, with git (works with git-vendored on any git host):

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.0.32 https://github.com/mangimangi/git-vendored.git "$tmp"
VENDOR_CHECKOUT="$tmp" bash "$tmp/install.sh" 0.0.32
rm -rf "$tmp"
```

With `VENDOR_CHECKOUT` set, `install.sh` copies every file from that checkout: no `gh`, no `curl`, no token.

GitHub-specific shortcut (downloads each file from `raw.githubusercontent.com`, or through `gh api` when `GH_TOKEN` is set):

```bash
curl -fsSL https://raw.githubusercontent.com/mangimangi/git-vendored/v0.0.32/install.sh | bash -s 0.0.32
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

The two workflows are installed only on this bootstrap install, into a repository with no earlier git-vendored install (no `.vendored/manifests/git-vendored.version`, `.vendored/manifests/git-vendored.files`, `.vendored/.version` or `.vendored/install`), and each is left out when the repository's git-cicd config (`.vendored/configs/git-cicd.json`) already has a job whose step runs `.vendored/check` (for `check-vendor.yml`) or `.vendored/install` (for `install-vendored.yml`), directly or from a script the step names; the installer prints one line saying why. An upgrade never adds either workflow: one that is present is kept and listed in the manifest, one that is absent was removed on purpose and stays absent. The manifest lists only files that are there.

## Adding a Vendor

```bash
python3 .vendored/install owner/repo-name                          # github.com shorthand
python3 .vendored/install https://git.example.com/team/repo-name.git  # any URL git can fetch
```

A vendor is named by a URL git can fetch (`https://`, `ssh://`, `git@host:path`, `file://`) or by the `owner/repo` shorthand, which means that repository on github.com. Its default vendor name is the URL's last path component without `.git`.

This will:
1. Resolve the version from the repo's version tags (`git ls-remote --tags`), then fetch the vendor once with git at that tag (a shallow clone into a temporary directory outside the repository, removed afterwards) and verify it has `install.sh` at its root
2. Run the vendor's `install.sh` from that checkout with `VENDOR_REPO`, `VENDOR_REF`, `VENDOR_MANIFEST`, `VENDOR_INSTALL_DIR` and `VENDOR_CHECKOUT` set; `deps.json` and `templates/config.schema` are read from the same checkout
3. Read the manifest output and store it at `.vendored/manifests/<vendor>.files`
4. Store the version at `.vendored/manifests/<vendor>.version` and the commit its tag points at at `.vendored/manifests/<vendor>.commit`

A later install of the same version checks the tag: when it now points at another commit than the recorded one, the install prints `::warning::<vendor>: tag <tag> now points at <new sha>, recorded <old sha>` and still skips, unless `--force` is given, which reinstalls and records the new commit. An install made before commits were recorded has no `.commit` file; it gets one on its next install.

Use `--name` to override the vendor key:

```bash
python3 .vendored/install owner/repo-name --name my-custom-name
```

If `owner/repo-name` is already registered (a vendor's registry `repo` is that repository), the same command updates it instead of failing, and says which vendor it updates. If the name it would use is registered for a different repository, it fails naming both. Surrounding whitespace is trimmed from the arguments; an empty target, one with whitespace inside, or a malformed `owner/repo` is rejected with a message naming what is wrong, before any network call.

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

The vendor, the version and the private flag can also be given through the environment, so a job can pass its declared inputs without building a command line. Command-line arguments win over the environment:

| Env var | Stands for | Used when |
|---------|------------|-----------|
| `VENDORED_VENDOR` | the target (`<vendor>`, a git URL, `owner/repo` or `all`) | no positional target is given |
| `VENDORED_VERSION` | `--version` (empty means `latest`) | `--version` is not given |
| `VENDORED_PRIVATE` | `--private` for `true`/`1`/`yes`; nothing for `false`/`0`/`no`/empty | `--private` is not given |

```bash
VENDORED_VENDOR=git-cicd VENDORED_VERSION=latest python3 .vendored/install --pr
```

### Which token does what

The install uses two secrets, split by what a token may do. A git-cicd job is given a secret only when it declares it, so the job that runs `.vendored/install --pr` must declare `CICD_WRITE_TOKEN` (and `CICD_READ_TOKEN` when it installs a private vendor).

| Token | What the install does with it | Read in this order | Fine-grained token permissions (on the repositories named) | Classic token scopes |
|-------|-------------------------------|--------------------|-------------------------------------------------------------|----------------------|
| `CICD_WRITE_TOKEN` | proposes changes: pushes the install branch (with its workflow files), opens the PR and requests auto-merge, so the PR's checks run | `CICD_WRITE_TOKEN`, then `VENDOR_PAT` | consuming repository: **Contents** read/write, **Pull requests** read/write, **Workflows** read/write | `repo`, `workflow` |
| `CICD_READ_TOKEN` | reads a private vendor repository (`private: true`, `--private`); cannot write | `CICD_READ_TOKEN`, then `CICD_WRITE_TOKEN`, then `VENDOR_PAT` | each private vendor repository: **Contents** read-only (and **Metadata** read-only, which GitHub adds) | `repo` |
| `GITHUB_TOKEN` (the workflow's own) | reads public vendors; pushes the branch without workflow files; opens the PR only with `--allow-workflow-token` or outside CI | | | |

`VENDOR_PAT`, the old name for both, is still read where the new names are unset, as shown; it is deprecated, so set `CICD_WRITE_TOKEN` and `CICD_READ_TOKEN` instead. No token value is printed. A vendor is read with git (`git ls-remote`, `git clone`): the read token is handed to that one git command as an HTTP header scoped to the vendor's URL, through `GIT_CONFIG_*` environment variables, never in a URL or on the command line and never written to a git config file. With no token, git reads the vendor anonymously.

### `--pr` in CI needs `CICD_WRITE_TOKEN`

GitHub starts no workflows for a pull request opened with a workflow's own `GITHUB_TOKEN`, so such an install PR gets no checks (and cannot merge where a status such as `Verdict / git-cicd:verdict` is required); where GitHub Actions may not create pull requests, the run fails after pushing its branch. So in `--pr` mode under CI (`GITHUB_ACTIONS` set) with no write token (`CICD_WRITE_TOKEN`, or the deprecated `VENDOR_PAT`), the install fails before changing any file or pushing any branch. Its message names `CICD_WRITE_TOKEN`, says the git-cicd job must declare it, and names `--allow-workflow-token`.

- **`--allow-workflow-token`** opens the PR with the workflow's own token on purpose, as before: its description then says in one line that no checks will run.
- **Outside CI** (`GITHUB_ACTIONS` unset) nothing is checked, and the PR is opened with whatever token `gh` has.

If the PR cannot be opened after the branch was pushed, the install names the branch, says how to open the PR by hand and exits non-zero; a PR that already exists for the branch is reused.

### Workflow files and `CICD_WRITE_TOKEN`

An install can change files under `.github/workflows/` (a vendor's workflows). The workflow's own `GITHUB_TOKEN` may not push those, so in `--pr` mode:

- **With `CICD_WRITE_TOKEN` set**, the workflow files the install wrote or removed stay in the commit, and the branch is pushed with it (sent as an HTTP header on the `git push` command line, never printed or written to `.git/config`). If the push is refused because the token may not write workflows, the install leaves the workflow files out, pushes the rest and still opens the PR.
- **Without a write token** (only with `--allow-workflow-token`, or outside CI), workflow files are left out.

Whenever workflow files are left out, the PR description lists them and says what to run and commit on the branch: for git-cicd, `.vendored/pkg/git-cicd/git-cicd generate`; for other vendors, `python3 .vendored/install <vendor> --force` with a token that may write workflows.

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
| `repo` | yes | A git URL of the vendor, or the `owner/name` shorthand for github.com; stored as given |
| `install_branch` | yes | Branch prefix for vendor update PRs |
| `allowed` | no | Glob patterns of vendor-managed files that users *can* edit |
| `private` | no | If `true`, the vendor is read with `CICD_READ_TOKEN` (else `CICD_WRITE_TOKEN`) |
| `automerge` | no | If `true`, auto-merge vendor update PRs (default: `false`) |
| `dogfood` | no | If `true`, skips `VENDOR_INSTALL_DIR` (installs into framework paths) |

**Backwards compatibility:** If `.vendored/configs/` has no `.json` files, the framework falls back to reading from a monolithic `.vendored/config.json` with a `vendors` key. The first time `install` runs after upgrading, it automatically migrates the monolithic config into per-vendor files.

**Note:** The `protected` field is preserved in per-vendor config for v1 fallback compatibility. Protection rules are derived automatically from manifests at `.vendored/manifests/<vendor>.files`. For v1 vendors without manifests, `check` falls back to config `protected` patterns.

## Vendor Contract

A vendor is a git repository, on any host git can fetch from, that has:

1. **`install.sh` at repo root** — receives context via environment variables, copies its files from the checkout (`VENDOR_CHECKOUT`, e.g. with the `$VENDOR_LIB` helpers) or downloads them, and writes a manifest
2. **Version tags** — the vendor's versions are its version tags (`vX.Y.Z` or `X.Y.Z`, numeric parts), as `git ls-remote --tags` lists them; `latest` is the highest of them by version order (so `0.0.10` is above `0.0.9`). Tags that are not versions (such as `latest`) and a component's tags (`<subdir>/vX.Y.Z`, a separate series) are ignored. An explicit `--version X` installs tag `vX`, else `X`; a version with no tag is an error

### Environment Variables

`install.sh` receives these environment variables from the framework:

| Env var | Purpose |
|---------|---------|
| `VENDOR_REPO` | The vendor's repository as configured (a git URL or `owner/repo`) |
| `VENDOR_REF` | The version's tag, which `VENDOR_CHECKOUT` is checked out at |
| `VENDOR_MANIFEST` | Path to write the file manifest to |
| `VENDOR_INSTALL_DIR` | Target directory for vendor files (e.g., `.vendored/pkg/<vendor>`) |
| `VENDOR_CHECKOUT` | Absolute path of the vendor fetched with git at `VENDOR_REF` (removed after the install) |
| `VENDOR_LIB` | Path of the helper library (`fetch_file`, `fetch_dir`), when installed |
| `GH_TOKEN` | Auth token (when available), for an installer that downloads by itself |

`VENDOR_INSTALL_DIR` is set for non-dogfood vendors. Vendors SHOULD install their primary files under this directory but MAY install to other paths (workflows) when the target system requires specific locations. If not set, the vendor falls back to its original file layout.

### Manifest

`install.sh` **must** write a manifest to `$VENDOR_MANIFEST` listing every file it created or modified, one path per line:

```
.my-tool/script.sh
.my-tool/config-template.json
.github/workflows/my-tool-check.yml
```

`install.sh` **must not**:
- Write version files (the framework handles this via `.vendored/manifests/<vendor>.version` and `.vendored/manifests/<vendor>.commit`)
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
| `repo` | yes | A git URL of the dependency, or the `owner/name` shorthand for github.com |
| `private` | no | If `true`, the dependency is read with `CICD_READ_TOKEN` (else `CICD_WRITE_TOKEN`). When omitted, inherits the parent vendor's `--private` flag |

Usage:

```bash
# Auto-install dependencies
python3 .vendored/install owner/my-tool --deps=install

# Private vendor with private dependencies
CICD_READ_TOKEN=<token> python3 .vendored/install owner/my-tool --private --deps=install
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
    my-tool.commit               # single line: commit of the installed version's tag
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

git-vendored's own pull request checks, releases, vendor updates and vendor validations run through [git-cicd](https://github.com/mangimangi/git-cicd), installed at `.vendored/pkg/git-cicd/`. The jobs are declared in `.vendored/configs/git-cicd.json`:

- `test` (Unit Tests): `ci/setup.sh` installs the Python floor that `requires-python` in `pyproject.toml` names, plus `pytest` and `pyyaml`, plus `coverage` (with a startup hook so subprocess runs are measured), into a virtualenv; `ci/test.sh` runs `pytest tests/ -v` under coverage with it and prints the line coverage of the six shipped Python scripts (`templates/install`, `templates/check`, `templates/remove`, `templates/audit`, `templates/feedback`, `validate`): `Stmts` executable lines, `Miss` lines no test ran, `Cover` the percentage, `Missing` their line numbers. Scripts a test starts as a subprocess are counted too. For one file: `python -m coverage report --include=templates/check` after a run. The job fails when the total or any one of those files is below 99% (`fail_under` in `pyproject.toml`, and a per-file check in `ci/test.sh`): a change that lowers coverage below 99% fails the verdict, so it adds its tests in the same pull request. A line is excluded (`# pragma: no cover`) only when no test can reach it, with the reason on the line. After pytest, `ci/test.sh` runs the bats tests in `tests/bats/` for `install.sh`, `templates/lib/vendor-helpers.sh` and the `ci/` scripts (`ci/setup.sh` provides a pinned bats-core when none is on `PATH`); a failing bats test fails the job. Run them alone with `bats tests/bats/`.
- `vendor-check` (Vendor Check): `ci/vendor-check.sh` runs `.vendored/check` against the change's base.
- `version-check` (Version Check): runs on every pull request into `main`. Its step is `.vendored/pkg/git-semver/git-semver check-bump`, which fails the pull request when it changes a file listed in `files` in `.vendored/configs/git-semver.json` (`install.sh`, `validate`, `templates/**`, `docs/**`, `AGENTS.md`, `README.md`) without raising `VERSION` above `main`'s.
- `release` (Release): runs on every merge to `main`, and by hand. Its step is `.vendored/pkg/git-semver/release` with no subcommand; with `"bump_on": "pull_request"` in `.vendored/configs/git-semver.json` it tags the landed commit with the version it carries (`v<VERSION>`) and creates the GitHub release, or does nothing when that version is already tagged. It pushes nothing to `main`, makes no commit and moves no `latest` tag. It takes no inputs; a manual run releases the current commit of the branch it runs on.
- `update-vendored` (Update Vendored): runs Mondays at 09:00 UTC (cron `0 9 * * 1`) on `main`, and by hand. `ci/update-vendored.sh` runs `.vendored/install <vendor> --version <version> --pr --deps=install` (plus `--private` when `private` is `true`), passing each input as one argument, never through a shell, with `GH_TOKEN` set from the `CICD_WRITE_TOKEN` secret (else the deprecated `VENDOR_PAT`) when one is set. Inputs: `vendor` (default `all`), `version` (default `latest`), `private` (`false` or `true`; default `false`).
- `validate` (Validate Vendor): by hand only. `ci/validate.sh` runs this repository's `validate <repo> --version <version>` to check whether a repository implements the vendor contract (nothing is installed). Inputs: `repo` (`owner/repo`, required) and `version` (default `latest`).

### How a release happens

The version is raised in the pull request, not after the merge. A change to a file git-semver watches runs, on its branch, `.vendored/pkg/git-semver/git-semver bump patch --no-commit` (or `minor` / `major` when it breaks an adopter), commits the new `VERSION` with the change, and the `version-check` job confirms it against `main`. Merging the pull request into `main` runs `release`, which tags that commit `v<VERSION>` and publishes the GitHub release. Nothing is pushed to `main`: there is no bump commit and no bump pull request.

To start a release (it only tags what is already on the branch), an update or a validation by hand: Actions tab → **Manual** workflow → **Run workflow**, pick the branch (`main` for `release` and `update-vendored`), set `job` to the job name (`release`, `update-vendored` or `validate`) and `inputs` to the job's inputs as a JSON object of strings, for example:

| `job` | `inputs` |
|---|---|
| `release` | `{}` (it takes none) |
| `update-vendored` | `{"vendor": "git-cicd", "version": "latest"}` (empty: every vendor, latest) |
| `validate` | `{"repo": "owner/repo"}` |

An input left out gets its default; an undeclared input, a value outside the choices or a missing `repo` refuses the run, with the reason in the report.

Tracker records (`LICENSE`, `.pearls/issues.jsonl`, `.pearls/docs/**`, `.madreperla/sessions.jsonl`, ...) are in `needs_nothing`, so a change to them alone needs no job. `*.md` and `docs/**` are not: `README.md`, `AGENTS.md` and `docs/**` are files git-semver watches, so a pull request into `main` that changes only them still runs `version-check` (and `vendor-check`). No Python version is written in any workflow: `pyproject.toml` is the one place it is declared.

Run the checks locally the way CI runs them:

```bash
.vendored/pkg/git-cicd/git-cicd check --setup   # first run: setup, then the jobs
.vendored/pkg/git-cicd/git-cicd check           # later runs reuse the virtualenv
```

The workflows `.github/workflows/git-cicd-open.yml`, `git-cicd-merge.yml`, `git-cicd-cron.yml` and `git-cicd-manual.yml` are generated: after changing the config or upgrading git-cicd, run `.vendored/pkg/git-cicd/git-cicd generate` and commit what it writes (`git-cicd verify` checks it matches).
