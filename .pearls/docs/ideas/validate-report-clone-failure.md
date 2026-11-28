# validate: report a git clone failure as its own failed check

> Captured: 2026-11-28

## Context

This came up while evaluating gv-26c4.4 (commit 9f22834), the change that makes `validate` check a vendor with git through templates/install's `ls_remote_tags`, `pick_version` and `fetch_vendor`. The relevant code is `_fetch()` in `validate`, which catches the `SystemExit` that `fetch_vendor` raises when the clone fails. `check_install_sh_exists` then receives `checkout=None`.

## Idea

validate: report a git clone failure as its own failed check

Today a clone that fails after `git ls-remote` succeeded is reported as check 2 failing with `no install.sh at root of <repo>`. That message is misleading, because the installer was never looked for. Instead, check 2 should fail with a detail like `could not fetch <repo> at <tag>`, or include git's stderr (with the token already scrubbed by `fetch_vendor`) as the detail.
