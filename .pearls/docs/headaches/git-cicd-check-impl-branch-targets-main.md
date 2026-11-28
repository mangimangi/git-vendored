# git-cicd check on an impl branch targets main instead of the integration branch

> Captured: 2026-11-28

## What was happening

Eval of epic gv-05c2 (`/eval gv-05c2`), step 3b: in-session run of `.vendored/pkg/git-cicd/git-cicd check --setup` on `gv-05c2/impl`. With no upstream set on the branch, git-cicd decided `target main`, so `vendor-check` diffed against `main` and failed (`::error::Protected vendor files were modified!` listing git-cicd, git-semver and git-vendored files that `plan/git-dev-883c` already brought in from main in #128). The test job passed. Rerunning with `--target plan/git-dev-883c` passed both jobs (`No vendor file violations detected.`).

## Headache

git-cicd check on an impl branch with no upstream defaults its target to main, so vendor-check fails on vendor files the integration branch (plan/git-dev-883c) already brought in from main; eval had to rerun with --target plan/git-dev-883c to get the real verdict. Impl branches should track their integration branch, or the eval skill should name the target.
