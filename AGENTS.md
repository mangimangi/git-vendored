# AGENTS.md

git-vendored: automated vendor install control for repo-embedded tools via GitHub workflows.

## Repo structure

```
.vendored/           # framework commands and vendor data
  install            # add/update vendors
  check              # file protection checks (runs on PRs)
  remove             # uninstall vendors
  audit              # validate configs against schemas
  feedback           # vendor feedback collection
  configs/           # per-vendor config (<vendor>.json)
  pkg/               # vendor-installed files (<vendor>/)
  manifests/         # file lists, versions, schemas, registries
  lib/               # shared Python modules
install.sh           # bootstrap installer (repo root)
tests/               # pytest suite
ci/                  # git-cicd job scripts (setup.sh, test.sh, vendor-check.sh,
                     #   update-vendored.sh, validate.sh)
docs/                # guides and planning
```

## Commands

```bash
python3 .vendored/install <owner/repo>       # install a vendor
python3 .vendored/install all                 # update all vendors
python3 .vendored/install all --pr            # update all + open PR
python3 .vendored/remove <vendor>             # uninstall a vendor
python3 .vendored/check                       # run file protection checks
python3 .vendored/audit                       # validate configs against schemas
python3 .vendored/feedback                    # vendor support/bug-report info
python3 .vendored/install --list              # list installed vendors
python3 validate <owner/repo> --version latest # check a repo implements the vendor contract
```

Release, vendor update and vendor validation are git-cicd jobs too
(`.vendored/configs/git-cicd.json`): `release` (runs on merge to `main`;
`.vendored/pkg/git-semver/release` tags the landed commit `v<VERSION>` and
creates the GitHub release, or does nothing if that version is tagged; it
pushes nothing to `main`),
`update-vendored` (cron Mondays 09:00 UTC on `main`; `ci/update-vendored.sh`
runs `.vendored/install <vendor> --version <version> --pr --deps=install`,
`GH_TOKEN` from `CICD_WRITE_TOKEN`, else the deprecated `VENDOR_PAT`,
when set) and `validate` (manual only;
`ci/validate.sh` runs `validate <repo> --version <version>`). Start one by
hand: Actions tab -> **Manual** workflow -> Run workflow, `job` = the job name,
`inputs` = its inputs as a JSON object of strings:

```
release          {}                              # no inputs: tags the branch's current commit
update-vendored  {"vendor": "git-cicd", "version": "latest"}   # defaults: all, latest; private: "true"|"false"
validate         {"repo": "owner/repo"}          # version defaults to latest
```

### Releasing

The version is raised in the pull request (`"bump_on": "pull_request"` in
`.vendored/configs/git-semver.json`). A change to a file listed in its `files`
(`install.sh`, `validate`, `templates/**`, `docs/**`, `AGENTS.md`,
`README.md`) runs `.vendored/pkg/git-semver/git-semver bump patch --no-commit`
(`minor`/`major` if it breaks an adopter) and commits `VERSION` with the
change; the `version-check` job (pull requests into `main`) runs
`.vendored/pkg/git-semver/git-semver check-bump` and fails if the version was
not raised above `main`'s. Merging into `main` tags and publishes it. There is
no bump commit or bump pull request.

## Tests

Pull request checks run through git-cicd (`.vendored/configs/git-cicd.json`):
the `test` job (`ci/setup.sh` installs the Python floor from `requires-python`
in `pyproject.toml` plus pytest, pyyaml, coverage and bats; `ci/test.sh` runs
the pytest suite under coverage, enforces 99%, then runs the bats tests) and
the `vendor-check` job (`ci/vendor-check.sh` runs `.vendored/check`). Run them
locally the same way:

```bash
.vendored/pkg/git-cicd/git-cicd check --setup   # setup, then every needed job
.vendored/pkg/git-cicd/git-cicd check           # reuse the setup
```

Or just the suite: `pip install pytest pyyaml && python3 -m pytest tests/ -v`.

### Shell tests (bats)

`install.sh`, `templates/lib/vendor-helpers.sh` and the `ci/` scripts have
bats tests under `tests/bats/` (`install.bats`, `vendor-helpers.bats`,
`ci-setup.bats`, `ci-test.bats`, `ci-vendor-check.bats`,
`ci-update-vendored.bats`, `ci-validate.bats`). `ci/test.sh` runs
them after pytest, and a failing bats test fails the `test` job. They stub
`curl`, `gh`, `uv`, the Python interpreters and `bats` on a temporary `PATH`
and run in temp dirs: no network, nothing installed. `ci/setup.sh` provides
bats (the one on `PATH`, or a pinned bats-core it downloads into the cache).
There is no coverage figure for shell. Run them alone:

```bash
bats tests/bats/        # or ~/.cache/git-vendored-ci/bats-<version>/bin/bats tests/bats/
```

### Coverage

The `test` job measures line coverage of the six Python scripts the repo
ships, and nothing else: `templates/install`, `templates/check`,
`templates/remove`, `templates/audit`, `templates/feedback` and `validate`
(named by path in `[tool.coverage.run]` in `pyproject.toml`, since they have
no `.py` extension; `tests/` and `.vendored/` are not measured). `ci/test.sh`
runs `coverage run -m pytest tests/ -v`, then `coverage combine` and
`coverage report`.

Subprocess runs count: `ci/setup.sh` puts a `.pth` startup hook
(`coverage.process_startup()`) in the floor venv, and `ci/test.sh` exports
`COVERAGE_PROCESS_START` and `GIT_VENDORED_ROOT`, so a script a test starts as
a program is measured too (`tests/test_entrypoints.py` does this for the
`__main__` lines). `tests/conftest.py` keeps those variables in any `env=` a
test passes to subprocess. Use the venv (`git-cicd check --setup` once) for
the same figures as CI; without the hook `ci/test.sh` warns that subprocess
runs are not counted.

Reading the report: `Stmts` is the executable lines in the file, `Miss` how
many of them no test ran, `Cover` the percentage run, and `Missing` the line
numbers (ranges like `100-113`) still untested. To see one file after a run:
`<venv>/bin/python -m coverage report --include=templates/check`.

The rule: each of the six scripts, and their total, must stay at 99% line
coverage or more. `ci/test.sh` fails the `test` job (and so
`Verdict / git-cicd:verdict`) when the total is below `fail_under = 99`
(`pyproject.toml`) or when any one file is, naming the file, its figure and
its missing lines. The `Cover` column rounds, so trust the `ci/test.sh:` line.
A change that lowers coverage below 99% adds its tests in the same pull
request. A line is excluded with `# pragma: no cover` only when no test can
reach it, with the reason in a comment on that line.
After changing the git-cicd config, run `.vendored/pkg/git-cicd/git-cicd generate`
and commit every `.github/workflows/git-cicd-*.yml` it writes (open, merge,
cron, manual); `git-cicd verify` checks they match.

## Contributing

- Commits: `<type>: <description>` (e.g., `feat:`, `fix:`, `chore:`)
- A change to a file git-semver watches raises `VERSION` in the same PR (`.vendored/pkg/git-semver/git-semver bump patch --no-commit`)
- Keep every shipped Python script at >= 99% line coverage: a change that lowers it fails the `test` job, so add its tests in the same PR (`# pragma: no cover` only for lines no test can reach, reason on the line)
- PRs run `tests/` and `.vendored/check` as git-cicd jobs (`Open / ... / git-vendored:<job>` rows, `Verdict / git-cicd:verdict` status), plus `version-check` on pull requests into `main`; `release`, `update-vendored` and `validate` are git-cicd jobs on merge, cron and manual runs
- Vendor configs live in `.vendored/configs/<vendor>.json`, not the legacy `config.json`
- All vendor-installed files go under `.vendored/pkg/<vendor>/`
- Manifests at `.vendored/manifests/<vendor>.files` drive protection rules

## Key files

- `VERSION` — current release version
- `pyproject.toml` — declares the Python floor (`requires-python = ">=3.11"`); CI tests on Python 3.11
- `madreperla.yaml` — repo metadata for madreperla orchestration
- `pearls.yaml` — issue tracker config for pearls/prl
- See `docs/` for adoption guide and vendor install dir guide
