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
After changing the git-cicd config, run `.vendored/pkg/git-cicd/git-cicd generate`
and commit `.github/workflows/git-cicd-open.yml`.

## Contributing

- Commits: `<type>: <description>` (e.g., `feat:`, `fix:`, `chore:`)
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
