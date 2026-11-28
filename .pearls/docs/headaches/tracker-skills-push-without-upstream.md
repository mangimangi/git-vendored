# Tracker skills fail to push on a fresh impl branch with no upstream

> Captured: 2026-11-28

## What was happening

Solo run of gv-3dd0 on branch `gv-3dd0/impl`, which had never been pushed. `/create-issue-estimate`, `/mark-issue-implemented` and `/create-issue-eval` each committed their tracker change, then failed `git push` with `fatal: The current branch gv-3dd0/impl has no upstream branch`. The commits stayed local until a manual `git push -u origin gv-3dd0/impl` before opening the PR.

## Headache

solo: tracker skills (create-issue-estimate, mark-issue-implemented, create-issue-eval) each fail their git push on a fresh gv-*/impl branch with no upstream; solo should push -u before step 3 or the skills should use push -u origin HEAD
