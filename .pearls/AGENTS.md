# Pearls Issue Tracking — AI Agent Instructions

This project uses **pearls** (`prl`) for issue tracking. Issues are stored in `.pearls/issues.jsonl`.

## File Permissions

> **NEVER edit installed files directly.** In consumer repos, update via the
> install workflow. In the pearls source repo, edit the source path shown below
> — NEVER `.github/workflows/`, `.pearls/prl.py`, `.pearls/AGENTS.md`, or
> `.claude/hooks/`. Installed copies are overwritten by the install workflow on
> every release.

| Installed path | Edit? | Install config | Source path (pearls repo) |
|---------------|-------|----------------|-------------------------------|
| `.pearls/prl.py` | **NO** | Always installed | `prl.py` (repo root) |
| `.pearls/merge-driver.py` | **NO** | Always installed | `merge-driver.py` (repo root) |
| `.pearls/.gitignore` | **NO** | Always installed | `templates/.gitignore` |
| `.pearls/.gitattributes` | **NO** | Always installed | `templates/.gitattributes` |
| `.pearls/AGENTS.md` | **NO** | `install.agents_md` | `templates/AGENTS.md` |
| `.claude/hooks/configure-prl.sh` | **NO** | `install.hooks` | `templates/hooks/configure-prl.sh` |
| `.github/workflows/*.yml` | **NO** | `install.workflows.*` | `templates/github/workflows/*.yml` |
| `.pearls/issues.jsonl` | **NO** | — | Use `prl` commands |
| `.pearls/config.json` | **YES** | — | — |

Install logic lives in `install.sh`.

### Issue Data

**Always use `prl` commands** to modify `.pearls/issues.jsonl`. Direct edits risk data corruption or format errors.

If you must edit `issues.jsonl` directly (e.g., `prl` is broken), note that this indicates tooling is failing and should be investigated.

## Quick Reference

**Always use `prl` commands** — the `configure-prl.sh` hook puts `prl` on PATH at session start. Never use `python3 prl.py` or `python3 .pearls/prl.py` directly.

```bash
prl list                    # List all issues
prl list --status=open      # List open issues
prl ready                   # Show issues ready for work
prl show <id>               # Show issue details
prl start <id>              # Mark as in_progress
prl impl <id> -a <model> -i <input> -o <output>  # Mark as implemented
prl eval <id> --evaluator <model> --correctness N --completeness N --quality N --testing N --documentation N
prl close <id>                                    # Close issue
```

## Workflow Lifecycle

Work flows through six stages. Each stage has a clear artifact and knowledge migrates forward, cleaning up the source as it moves.

```
planning → refinement → estimation → implementation → evaluate → cleanup
```

### Stages and Artifacts

| Stage | Artifact | Location |
|-------|----------|----------|
| **Planning** | Markdown docs | `docs/planning/` (exploratory) or `docs/planning/epics/<epic-id>.md` (ready for refinement) |
| **Refinement** | `prl` issues with acceptance criteria | `.pearls/issues.jsonl` (via `prl create`) |
| **Estimation** | Token cost estimates on issues | `.pearls/issues.jsonl` (via `prl estimate`) |
| **Implementation** | Code, tests, docs + implemented issues | Codebase + `.pearls/issues.jsonl` (via `prl impl`) |
| **Evaluate** | Scores, defect tickets, closed issues | `.pearls/issues.jsonl` (via `prl eval` + `prl close`) |
| **Cleanup** | Archived/closed stale issues | `.pearls/archive/` |

### Knowledge Migration

Knowledge migrates forward between stages. **The source is always cleaned up after migration** — delete or remove content that has been captured downstream.

**Planning → Planning/Epics** — When planning work spans multiple sessions and becomes clear enough for refinement, migrate the relevant content from `docs/planning/<topic>.md` into `docs/planning/epics/<epic-id>.md`. Create the epic with `prl create --type=epic` if it doesn't exist. Remove the migrated content from the source doc (delete the file if fully migrated).

**Planning/Epics → Issues** — During refinement, break down `docs/planning/epics/<epic-id>.md` into `prl` issues with clear acceptance criteria. After creating the issues, remove the refined items from the planning doc. Delete the file when everything has been refined into issues.

### Why Cleanup Matters

Each stage's artifact is the **single source of truth** for that stage. If planning docs stick around after their content has been refined into issues, you get drift — the doc says one thing, the issues say another. Cleaning up the source after migration keeps the system honest.

## One Commit Per Task (CRITICAL)

**Every task MUST be implemented in exactly one commit.**

### Why?

1. **Traceability** — Each issue links to exactly one commit
2. **Rollback** — Easy to revert a specific task
3. **Cost attribution** — Token costs map to a single unit of work
4. **Code review** — Reviewers see complete, self-contained changes

### Workflow

```
1. prl start <issue-id>           # Mark as in_progress
2. Implement the task             # Write code, tests, docs
3. git add <files>                # Stage changes
4. git commit -m "..."            # ONE commit for the task
5. prl impl <id> -a ... -i -o    # Mark as implemented with cost tracking
```

## Cost Tracking (REQUIRED)

**AI agents MUST record implementation costs when marking issues as implemented.**

```bash
prl impl proj-a3f8 \
    -a claude-opus-4-5-20251101 \
    -i 12500 -o 3200
```

### What to Track

Include ALL tokens spent on the task:
- Reading code to understand the codebase
- Failed attempts and retries
- Test iterations
- Documentation written

### Edge Cases

```bash
# Only if absolutely necessary (human closures, etc.)
prl impl proj-a3f8 --no-cost
```

## Issue Statuses

Issues progress through these statuses:

| Status | Icon | Description |
|--------|------|-------------|
| `open` | ○ | Not yet started |
| `in_progress` | ◐ | Currently being worked on |
| `implemented` | ◑ | Implementation complete, awaiting evaluation |
| `closed` | ● | Evaluated and accepted (or manually closed) |

## Estimates

Add estimates before starting work:

```bash
prl estimate proj-a3f8 \
    -e claude-opus-4-5-20251101 \
    -m claude-opus-4-5-20251101 \
    -i 8000 -o 2000
```

**Default implementer assumption**: When estimating, if the task doesn't specify who will implement it, assume `claude-opus-4-5-20251101` will be the implementer. Base your token estimates on opus 4.5's capabilities, not your own model or a human.

Estimates are intuition-based predictions. Comparing to actual costs improves accuracy over time.

## Dependencies

```bash
# Hard blocking (filters prl ready)
prl dep add proj-a3f8 proj-b2c1 --type=blocks

# Soft ordering (warning in prl ready)
prl dep add proj-a3f8 proj-b2c1 --type=precedes

# Related issues
prl link proj-a3f8 proj-b2c1

# Mark duplicate and close
prl dup proj-a3f8 proj-b2c1
```

## Bug Workflow (IMPORTANT)

**When you discover a bug during development, ALWAYS:**

1. **Create a bug ticket FIRST** — with references to where the bug manifests
2. **Fix and close with costs** — track the fix effort on the bug ticket
3. Add `caused_by` links manually if you know the introducing commit

### Defects Found During Evaluation

If you find a defect while evaluating an implemented issue, use `--defect-of` **and `--parent`** to create a linked bug ticket inside the same epic. Always include specific file/line references so the bug is actionable:

```bash
# Creates a bug with caused_by dep, ref to the original issue's commit,
# and parented under the same epic for traceability
prl create --title="Missing null check in handler" \
  --defect-of proj-a3f8 \
  --parent proj-a3f8-epic \
  --ref "file:src/handler.py,lines:42-50"
```

### Bugs Discovered During Development

If you find a bug while working on a task (e.g., CI fails, tests break):

```bash
# 1. Create the bug ticket with references to where the bug manifests
prl create --title="Fix mock curl -o flag handling" --type=bug \
  --ref "file:src/api.py,lines:42-50"

# 2. Start, fix, commit, and mark as implemented
prl start proj-c3d2
# ... fix the bug ...
git commit -m "Fix mock curl to handle -o flag"
prl impl proj-c3d2 -a claude-opus-4-5-20251101 -i 15000 -o 5000
```

You can also add references after creation:

```bash
# Add a file+line reference
prl ref add proj-c3d2 --file src/api.py --lines 42-50,100

# Add a commit reference (if you know the introducing commit)
prl ref add proj-c3d2 --commit abc123

# List references
prl ref list proj-c3d2

# Remove a reference by index
prl ref remove proj-c3d2 --index 0
```

**Why this matters:**
- The original task's costs reflect its actual implementation, not debugging
- Bug fix effort is tracked separately and attributed correctly
- References document WHERE the bug manifests for future analysis

### Standalone Bugs

For bugs with no clear cause (user reports, environmental issues):

```bash
prl create --title="Login fails on Safari" --type=bug
```

### Anti-Patterns

- **DON'T** fix bugs without a ticket — costs get lost or misattributed
- **DON'T** add bug fix costs to the original task — create a separate bug ticket
- **DON'T** use parent/child for bugs — that's for task decomposition

## Branch Naming (REQUIRED)

All branches **must** follow these naming conventions. A pre-push hook enforces these patterns — pushes from non-conforming branches will be rejected.

### Patterns

**First-class epic branches** (epics listed in `config.json` `epics` key, e.g., `1shots`, `enhncmnts`):

| Pattern | When | Example |
|---------|------|---------|
| `<prefix>-<epic>.<h1>+<h2>/<mode>` | Session on specific tasks | `prl-1shots.b2c1+a3f8/impl` |
| `<prefix>-<epic>.<hash>` | Single task | `prl-1shots.b2c1` |
| `<prefix>-<epic>.<h1>+<h2>+<h3>` | Multiple tasks (no mode) | `prl-1shots.b2c1+a3f8+d4e5` |

First-class epics are broad containers — branches **must** include the specific task hash(es) being worked on.

**Feature epic branches** (e.g., `prl-a3f8`):

| Pattern | When | Example |
|---------|------|---------|
| `<epic-id>/<mode>` | Session on the epic | `prl-a3f8/impl` |

**Planning branches** (planning happens before epics exist):

| Pattern | When | Example |
|---------|------|---------|
| `<prefix>-<planning-doc>/plan` | Planning session | `prl-auth-system/plan` |

The `<planning-doc>` is the filename (without extension) from `docs/planning/<filename>.md`.

**Special branches** (always allowed):

| Pattern | Example |
|---------|---------|
| `main` | `main` |
| `chore/install-pearls*` | `chore/install-pearls-v0.2.12` |

### Modes

Valid `<mode>` values: `plan`, `refine`, `estimate`, `impl`, `oneshot`, `eval`, `cleanup`

These correspond to `prl prompt` modes.

### Bypass

```bash
git push --no-verify
```

## Visualization

```bash
prl graph proj-a3f8    # Dependency graph
prl board              # Kanban board view
prl board --parent=proj-a3f8  # Board for subtasks
```
