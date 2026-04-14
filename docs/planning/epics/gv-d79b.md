# Docs cohesion: git-vendored changes

> Per-repo planning doc for git-vendored.
>
> **Parent:** [orchestrator.md](orchestrator.md)
> **Phase:** 3

## What ships

### 1. Align madreperla.yaml to canonical shape

Current config has wrong field names (`docs:` instead of `usage:`) — these are invisible to madreperla. Fix to canonical shape: `usage:` fields, remove `designs`, add `planning` + `epics` path keys (currently missing).

### 2. pearls.yaml — no changes

Already correct: `prefix: gv`, `eval.threshold: 80`.

### 3. Audit/update root README.md, create AGENTS.md

- README.md (278 lines) — audit for accuracy
- AGENTS.md — currently missing, create with contributing conventions

### 4. Create docs/README.md

Contents for git-vendored's docs/:
- docs/adoption.md — adoption guide
- docs/vendor-install-dir-guide.md — install dir guide
- docs/planning/ — active planning
- docs/planning/epics/ — epic planning docs

## Acceptance criteria

- Config aligned, field name bugs fixed
- AGENTS.md created, README.md audited
- docs/README.md exists
- `madp configure --provider claude` succeeds
