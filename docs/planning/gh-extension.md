# gh-vendored: GitHub CLI Extension Plan

**Status:** Future
**Depends on:** Stable vendor contract (v1 or v2)

## Context

git-vendored currently bootstraps via curl:

```bash
curl -fsSL https://raw.githubusercontent.com/mangimangi/git-vendored/v0.1.0/install.sh | bash -s 0.1.0
```

This works but has trust/discoverability downsides. A `gh` CLI extension would provide a cleaner UX while keeping the curl/manual path as fallback.

## Current Bootstrap Methods (ship now)

### 1. curl (primary)

```bash
curl -fsSL https://raw.githubusercontent.com/mangimangi/git-vendored/v0.1.0/install.sh | bash -s 0.1.0
```

### 2. Manual (fallback, no dependencies beyond git)

```bash
git clone --depth 1 --branch v0.1.0 https://github.com/mangimangi/git-vendored /tmp/gv
bash /tmp/gv/install.sh 0.1.0
rm -rf /tmp/gv
```

## gh Extension Plan (future)

### What it is

A `gh-vendored` executable at the repo root that makes this repo installable as a GitHub CLI extension:

```bash
gh extension install mangimangi/git-vendored
gh vendored init
```

### Implementation

One bash script at repo root: `gh-vendored`

```bash
#!/usr/bin/env bash
set -e

cmd="${1:-}"

case "$cmd" in
  init)
    shift
    version="${1:-latest}"

    if [ "$version" = "latest" ]; then
      version=$(gh api repos/mangimangi/git-vendored/releases/latest --jq '.tag_name' 2>/dev/null \
        || gh api repos/mangimangi/git-vendored/contents/VERSION --jq '.content' | base64 -d | tr -d '[:space:]')
      version="${version#v}"
    fi

    # Download and run the bootstrap installer
    tmpdir=$(mktemp -d)
    trap 'rm -rf "$tmpdir"' EXIT
    gh api "repos/mangimangi/git-vendored/contents/install.sh?ref=v${version}" \
      --jq '.content' | base64 -d > "$tmpdir/install.sh"
    bash "$tmpdir/install.sh" "$version"
    ;;

  version)
    echo "gh-vendored extension (bootstrap only)"
    echo "Framework version is managed per-repo in .vendored/.version"
    ;;

  *)
    echo "Usage: gh vendored <command>"
    echo ""
    echo "Commands:"
    echo "  init [version]   Bootstrap git-vendored in the current repo"
    echo "  version          Show extension info"
    echo ""
    echo "After init, use .vendored/ commands directly:"
    echo "  python3 .vendored/add <owner/repo>    Add a vendor"
    echo "  python3 .vendored/update <vendor|all>  Update vendors"
    ;;
esac
```

### Why only bootstrap?

The `gh` extension handles **one thing**: getting git-vendored into a new repo. After that, all commands (add, update, check, remove) run from the vendored `.vendored/` directory. This is intentional:

- **Vendored tools are pinned per-repo.** A global `gh vendored update` would bypass version pinning.
- **No gh dependency at runtime.** CI and pre-commit hooks must work without `gh`.
- **One distribution model.** Vendored tools stay vendored. The extension is just a nicer front door.

### Why NOT make semver/dogfood gh extensions

The same reasoning applies to all vendored tools:

| Concern | gh extension (global) | Vendored (per-repo) |
|---------|----------------------|---------------------|
| Version pinning | User's machine, uncontrolled | Committed to git, deterministic |
| CI compatibility | Must install extension in workflow | Already in the repo |
| Multi-repo consistency | Each dev may have different version | Everyone uses the committed version |
| Offline/airgapped | Needs gh + internet | Already cloned |

`gh extension` = **distribution channel for bootstrap**.
Vendoring = **distribution channel for tools**.

These serve different purposes and should not be conflated.

### Repo rename consideration

For `gh extension install` to work, the repo must be named `gh-vendored` (gh requires the `gh-` prefix and looks for an executable matching the repo name at root). Options:

1. **Rename repo to `gh-vendored`** — cleanest, `gh extension install` works immediately
2. **Keep `git-vendored`, publish `gh-vendored` as separate repo** — more repos to maintain
3. **Keep `git-vendored`, add `gh-vendored` executable anyway** — won't work with `gh extension install` (name mismatch)

**Recommendation:** Rename to `gh-vendored` when we're ready to ship the extension. The `git-vendored` name still works as a concept/brand; the repo just has a `gh-` prefix for CLI compatibility.

### Rollout

1. Stabilize v1 bootstrap (curl + manual) — **now**
2. Ship vendor contract v2 (gv-cf3f) — **next**
3. Add `gh-vendored` script + rename repo — **after v2 is stable**
4. Update README quick start to show both paths

## Open Questions

- Should `gh vendored init` also run `.vendored/add` for common starter tools?
- Should we support `gh vendored init --with semver,dogfood` as a convenience?
- Is there value in `gh vendored status` that reads `.vendored/config.json` and shows update availability?
