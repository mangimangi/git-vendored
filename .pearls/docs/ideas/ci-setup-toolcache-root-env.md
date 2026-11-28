# Let ci/setup.sh take the tool-cache root from an env var so its bats test stays in a temp dir

> Captured: 2026-11-28

## Context

Eval pass on epic gv-f492 (gv-f492.6, commit 4cae561). `tests/bats/ci-setup.bats` test "the runner tool cache is used when python<floor> is not on PATH" (around line 77) has to write a fake interpreter under the real `/opt/hostedtoolcache/Python/<floor>.1/` because `ci/setup.sh` hardcodes that path. The test cleans up the version dir (and the whole tree if it created it), but when `/opt/hostedtoolcache` exists without a `Python/` subdir, the `Python/` dir it creates is left behind. It skips when `/opt` is not writable.

## Idea

ci-setup.bats tool-cache test writes to the real /opt/hostedtoolcache (and can leave an empty Python/ dir behind when it creates that subdir); let ci/setup.sh read the tool-cache root from an env var (e.g. RUNNER_TOOL_CACHE, which Actions sets) so the test can point it at a temp dir
