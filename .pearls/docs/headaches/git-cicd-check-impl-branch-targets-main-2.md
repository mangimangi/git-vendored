# git-cicd check on an impl branch still targets main during eval

> Captured: 2026-11-28

## What was happening

Re-eval of epic gv-05c2 (`/eval gv-05c2`), step 3b, scoring defect gv-05c2.6 on `gv-05c2/impl`. `.vendored/pkg/git-cicd/git-cicd check --setup` decided target `main`, so `vendor-check` failed with `::error::Protected vendor files were modified!` (git-cicd, git-semver and git-vendored files already on `plan/git-dev-883c`). The test job passed. Rerunning with `--target plan/git-dev-883c` passed both jobs (`No vendor file violations detected.`).

## Headache

Eval of gv-05c2 again had to rerun git-cicd check with --target plan/git-dev-883c: on gv-05c2/impl with no upstream, check targets main and vendor-check fails on vendor files the integration branch already carries. The eval skill should name the target or impl branches should track their integration branch.
