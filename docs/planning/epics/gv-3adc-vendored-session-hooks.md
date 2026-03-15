# Vendored Session Hooks — Hook Convention & Query Primitives

**Status:** Planning → Ready for Refinement
**Priority:** P1
**Epic:** gv-3adc

## Problem

Vendored packages that need session-time configuration (Claude Code session start/resume) have no standardized way to declare hooks. Today pearls manually templates `.claude/hooks/configure.sh` and `.claude/settings.json` into consumer repos via `install.sh`. This doesn't scale — if git-semver, git-dogfood, or any other vendored tool wanted session hooks, they'd each independently write to `.claude/settings.json` and `.claude/hooks/`, causing conflicts.

## Scope (Rescoped 2026-03-15)

git-vendored's responsibility is limited to **standardizing how vendors declare hooks** and **exposing query primitives** for listing vendors and their hooks in dependency order. Session orchestration (generating orchestrator scripts, managing `.claude/settings.json`, post-install safety nets) is owned by **madreperla** — the Claude-aware methodology layer. See prl-a537 in the pearls repo for orchestration design.

### What git-vendored owns

1. **Hook declaration convention** — vendors place hooks at known paths
2. **`vendored --list`** — list installed vendors in dependency order
3. **`vendored --hooks <start|resume>`** — list hook script paths in dependency order
4. **`post-install.sh` execution** — run post-install hooks during `install` when `.git/` exists

### What madreperla owns (see prl-a537)

- Orchestrator script generation (`.claude/hooks/vendored-session.sh`)
- `.claude/settings.json` management (merge strategy for session hooks)
- Post-install safety net (version-stamp gated re-run at session start)
- Session start/resume lifecycle

## Design

### 1. Hook Declaration Convention

Vendors place hooks at a known path inside their install directory:

```
.vendored/pkg/<vendor>/hooks/
  session-start.sh    # runs on Claude Code session start
  session-resume.sh   # runs on Claude Code session resume
  post-install.sh     # runs after install.sh, in consumer repo context with .git/
```

All hooks are optional. A vendor declares only what it needs. Hooks must be executable shell scripts (`#!/bin/bash` or `#!/usr/bin/env bash`).

**Environment variables available to all hooks:**

| Var | Value |
|-----|-------|
| `VENDOR_NAME` | The vendor's name (e.g., `pearls`) |
| `VENDOR_PKG_DIR` | Absolute path to `.vendored/pkg/<vendor>` |
| `PROJECT_DIR` | Absolute path to the consumer repo root |

**Hook output:** All vendor hook stdout is session context (fed to the orchestrator's caller). Vendors control what they emit.

**post-install.sh contract:**
- Runs in the consumer repo root (cwd = repo root)
- Has `.git/` access
- Must be idempotent (may run multiple times)

### 2. `vendored --list` — Vendors in Dependency Order

New CLI command on the `install` coordinator:

```bash
python3 .vendored/install --list
```

Output: one vendor name per line, topologically sorted by dependency order (`.vendored/manifests/<vendor>.deps`). Vendors with no dependency relationship: alphabetical tiebreak.

```
git-semver
pearls
```

### 3. `vendored --hooks <start|resume>` — Hook Paths in Dependency Order

New CLI command:

```bash
python3 .vendored/install --hooks start
python3 .vendored/install --hooks resume
```

Output: absolute paths to matching hook scripts, one per line, in dependency order. Only includes vendors that have the requested hook file.

```
/path/to/.vendored/pkg/git-semver/hooks/session-start.sh
/path/to/.vendored/pkg/pearls/hooks/session-start.sh
```

### 4. post-install.sh Execution During Install

After `install.sh` completes, the framework checks for `$VENDOR_INSTALL_DIR/hooks/post-install.sh`. If it exists and `.git/` is present in the consumer repo, run it immediately.

- Sets `VENDOR_NAME`, `VENDOR_PKG_DIR`, `PROJECT_DIR` env vars
- Writes version stamp to `.vendored/manifests/<vendor>.post-installed`
- The version stamp is available for downstream tools (madreperla) to implement safety-net re-runs

## Dependency Order

Hook execution order uses the existing dependency system:

1. Read `.vendored/manifests/<vendor>.deps` for each vendor with hooks
2. Topological sort — vendors with no deps first, dependents after
3. Vendors with no dependency relationship: alphabetical tiebreak
4. Cycles: error (same as existing dep resolution)

Example: if pearls depends on git-semver, git-semver's hooks run first.

## What Vendors Must Change

For a vendor to declare session hooks:

1. Place hook scripts at `.vendored/pkg/<vendor>/hooks/` (via `$VENDOR_INSTALL_DIR/hooks/` in their `install.sh`)
2. Add hook files to their manifest output
3. Remove any direct `.claude/` file management from `install.sh`
4. That's it — the orchestrator (madreperla) discovers hooks via `vendored --hooks`

## Task Breakdown

**gv-3adc.1 — Hook convention and post-install execution**
- Document hook declaration convention (hook paths, env vars, contracts)
- After `install.sh` completes, check for `$VENDOR_INSTALL_DIR/hooks/post-install.sh`
- Run it if `.git/` exists in consumer repo
- Write version stamp to `.vendored/manifests/<vendor>.post-installed`

**gv-3adc.2 — `--list` and `--hooks` query commands**
- Add `--list` flag to coordinator: scan `.vendored/manifests/`, topological sort, output vendor names
- Add `--hooks <start|resume>` flag: map hook type to filename (`session-start.sh` / `session-resume.sh`), filter to vendors that have the file, output absolute paths in dependency order
- Tests for both commands

## Decisions

- **Orchestration ownership:** madreperla, not git-vendored. git-vendored is a generic vendoring tool (Layer 0) and should not have Claude Code session knowledge.
- **Query interface:** Simple line-oriented stdout — easy to consume from shell or Python.
- **post-install stamps:** Written by git-vendored during install. Read by madreperla for safety-net logic. Decoupled via filesystem convention.
- **Hook order:** Dependency order from existing `deps.json`/`.deps` system, alphabetical tiebreak.

## Migrated to madreperla (prl-a537)

The following tasks from the original gv-3adc design were reassigned to madreperla on 2026-03-15:

- ~~gv-3adc.2 (orchestrator generation)~~ → prl-00dc task 1
- ~~gv-3adc.3 (settings.json management)~~ → prl-00dc task 2
- ~~gv-3adc.4 (post-install safety net)~~ → prl-00dc task 3
- ~~gv-3adc.5 (pearls hook split)~~ → prl-00dc task 4
