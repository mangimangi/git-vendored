# archive-epic skill does not commit or push the archive

> Captured: 2026-11-28

## What was happening

Running `/cleanup gv-f492`. `/close-issue gv-f492` closed the epic and committed and pushed `.pearls/issues.jsonl`. `/archive-epic gv-f492` then ran `prl archive gv-f492`, which archived the epic and its 6 children to `.pearls/archive/gv-f492.jsonl`. But the skill stopped after reporting and did not commit or push. `/archive-scope-doc` does commit and push. Cleanup had to commit the archive by hand (`pearls: archive gv-f492`).

## Headache

archive-epic: unlike close-issue and archive-scope-doc, it leaves the `prl archive` result uncommitted and unpushed, so the caller has to add a manual git add/commit/push step.
