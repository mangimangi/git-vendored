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
```

## Tests

```bash
pip install pytest pyyaml
python3 -m pytest tests/ -v
```

## Contributing

- Commits: `<type>: <description>` (e.g., `feat:`, `fix:`, `chore:`)
- PRs run `tests/` via CI and `.vendored/check` for file protection
- Vendor configs live in `.vendored/configs/<vendor>.json`, not the legacy `config.json`
- All vendor-installed files go under `.vendored/pkg/<vendor>/`
- Manifests at `.vendored/manifests/<vendor>.files` drive protection rules

## Key files

- `VERSION` — current release version
- `madreperla.yaml` — repo metadata for madreperla orchestration
- `pearls.yaml` — issue tracker config for pearls/prl
- See `docs/` for adoption guide and vendor install dir guide
