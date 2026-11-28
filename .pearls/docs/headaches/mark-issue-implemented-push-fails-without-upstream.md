# mark-issue-implemented push fails on a branch with no upstream

> Captured: 2026-11-28

## What was happening

Implementing epic gv-26c4 on branch `gv-26c4/impl`. Each `/mark-issue-implemented <id> <sha>` run (gv-26c4.1 to .4) did `prl impl` and committed `.pearls/issues.jsonl`, then failed at `git push` with exit 128: "fatal: The current branch gv-26c4/impl has no upstream branch." The skill only allows a plain `git push`, so it stopped there, and every tracker commit (6d0b5aa, 5016fb1, d8c8eb2, 766f2c8) is still only local.

## Headache

mark-issue-implemented's git push fails on a fresh impl branch (no upstream), so every tracker commit stays local; the skill only allows plain git push, not --set-upstream
