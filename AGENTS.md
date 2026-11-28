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
ci/                  # git-cicd job scripts (setup.sh, test.sh, vendor-check.sh)
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
```

## Tests

Pull request checks run through git-cicd (`.vendored/configs/git-cicd.json`):
the `test` job (`ci/setup.sh` installs the Python floor from `requires-python`
in `pyproject.toml` plus pytest and pyyaml; `ci/test.sh` runs the suite) and
the `vendor-check` job (`ci/vendor-check.sh` runs `.vendored/check`). Run them
locally the same way:

```bash
.vendored/pkg/git-cicd/git-cicd check --setup   # setup, then every needed job
.vendored/pkg/git-cicd/git-cicd check           # reuse the setup
```

Or just the suite: `pip install pytest pyyaml && python3 -m pytest tests/ -v`.

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
and commit `.github/workflows/git-cicd-open.yml`.

## Contributing

- Commits: `<type>: <description>` (e.g., `feat:`, `fix:`, `chore:`)
- Keep every shipped Python script at >= 99% line coverage: a change that lowers it fails the `test` job, so add its tests in the same PR (`# pragma: no cover` only for lines no test can reach, reason on the line)
- PRs run `tests/` and `.vendored/check` as git-cicd jobs (`Open / ... / git-vendored:<job>` rows, `Verdict / git-cicd:verdict` status)
- Vendor configs live in `.vendored/configs/<vendor>.json`, not the legacy `config.json`
- All vendor-installed files go under `.vendored/pkg/<vendor>/`
- Manifests at `.vendored/manifests/<vendor>.files` drive protection rules

## Key files

- `VERSION` — current release version
- `pyproject.toml` — declares the Python floor (`requires-python`); CI tests on it
- `madreperla.yaml` — repo metadata for madreperla orchestration
- `pearls.yaml` — issue tracker config for pearls/prl
- See `docs/` for adoption guide and vendor install dir guide
