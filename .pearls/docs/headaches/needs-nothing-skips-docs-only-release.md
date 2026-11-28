# git-cicd needs_nothing skips the release job on docs-only merges

> Captured: 2026-11-28

## What was happening

Implementing gv-05c2.5: moving git-vendored's own release from the hand-written `version-bump.yml` to a git-cicd `release` job (`"on": ["merge"]`, `"branches": ["main"]`, step `.vendored/pkg/git-semver/release`) in `.vendored/configs/git-cicd.json`. That config's `needs_nothing` lists `*.md`, `docs/**` and others so that docs-only pull requests skip the `test` and `vendor-check` jobs. git-cicd applies `needs_nothing` to every trigger, merge included.

## Headache

git-cicd applies `needs_nothing` to every trigger. So when a merge to `main` changes only `*.md` or `docs/**` files, the `release` job does not run. git-semver counts those files as shipped, and the old `version-bump.yml` did bump on them. Merges that touch `VERSION` or code still trigger a release.

There are two ways out, and both need the owner:

- a per-job `paths` or `needs_nothing` override in git-cicd;
- taking `*.md` out of `needs_nothing`, which would make docs-only pull requests run every check.
