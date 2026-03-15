# Session Hooks

git-vendored provides a framework-level hook lifecycle that lets vendor tools
run scripts during Claude Code session events (startup, resume) and after
installation (post-install).

## Hook Convention

Vendors place hook scripts in their package's `hooks/` directory:

```
.vendored/pkg/<vendor>/hooks/
  session-start.sh    # Runs on Claude Code session startup
  session-resume.sh   # Runs on Claude Code session resume
  post-install.sh     # Runs after install.sh when .git/ exists
```

All hooks are optional — vendors include only the ones they need.

## Hook Types

### session-start.sh

Called during Claude Code session startup. Use for:
- Creating CLI shims
- Generating session context/prompts
- Setting up runtime environment

### session-resume.sh

Called when a Claude Code session resumes. Use for:
- Lightweight re-initialization
- Abbreviated prompts

### post-install.sh

Called after `install.sh` completes, **only when `.git/` exists** in the
consumer repo. Use for git-dependent setup:
- Registering merge drivers
- Installing git hooks (symlinks)
- Configuring git attributes

Must be idempotent. Skipped in CI download contexts where `.git/` doesn't exist.

## Environment Variables

All hooks receive:

| Variable | Description |
|----------|-------------|
| `VENDOR_NAME` | Vendor identifier (e.g., `pearls`) |
| `VENDOR_PKG_DIR` | Absolute path to vendor package (e.g., `/repo/.vendored/pkg/pearls`) |
| `PROJECT_DIR` | Absolute path to consumer repo root |
| `CLAUDE_PROJECT_DIR` | Passed through from Claude Code (session hooks only) |

## How It Works

### Orchestrator Generation

After `install` or `remove` commands, the framework:

1. **Discovers hooks** — scans `.vendored/pkg/*/hooks/` for hook scripts
2. **Orders vendors** — topological sort by dependency with alphabetical tiebreak
3. **Generates orchestrator** — writes `.claude/hooks/vendored-session.sh`
4. **Merges settings** — updates `.claude/settings.json` with orchestrator entries

### Orchestrator Script

The generated `.claude/hooks/vendored-session.sh`:
- Accepts `--start` or `--resume` mode argument
- Dispatches to each vendor's hooks in dependency order
- Includes post-install safety net (re-runs post-install if version stamp is stale)
- Uses `set -euo pipefail` (fail-fast on any hook failure)

### Settings Merge

The framework merges its entries into `.claude/settings.json`:
- **Adds** two `SessionStart` entries (startup → `--start`, resume → `--resume`)
- **Preserves** all non-vendor hooks and other top-level keys
- **Idempotent** — safe to run multiple times
- **Cleans up** — removes vendored entries when no vendors have hooks

### Post-Install Version Stamping

Post-install hooks track execution via version stamps:
- Stamp file: `.vendored/manifests/<vendor>.post-installed`
- Contains the version string from `.vendored/manifests/<vendor>.version`
- Skips execution when stamp matches current version
- Re-runs on version change (upgrade scenario)
- Not written on failure (retries next time)

## Directory Layout

```
.claude/
  hooks/
    vendored-session.sh    # Auto-generated orchestrator (do not edit)
  settings.json            # Framework merges vendor entries here

.vendored/
  pkg/<vendor>/hooks/
    session-start.sh       # Vendor-provided hooks
    session-resume.sh
    post-install.sh
  manifests/
    <vendor>.post-installed # Version stamp for post-install idempotency
```

## Migration from Legacy configure.sh

If a vendor previously managed `.claude/hooks/configure.sh` directly:

1. Split configure.sh logic into `hooks/post-install.sh`, `hooks/session-start.sh`,
   and `hooks/session-resume.sh`
2. Remove `.claude/hooks/configure.sh` and `.claude/settings.json` from the
   vendor's install.sh manifest output
3. On next `install all`, the framework will:
   - Remove the old configure.sh (no longer in manifest)
   - Generate the orchestrator
   - Update settings.json with framework-managed entries
