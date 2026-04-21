# Interpolation cleanup — per-repo migration guide

> Per-repo planning doc for epic `mdci-dev-fd2f` (all target repos)

## Migration steps

Run in each target repo after pearls + madreperla ship:

### 1. Update pearls.yaml

Add `docs:` section:

```yaml
docs:
  epics: .pearls/docs/epics
  ideas: .pearls/docs/ideas
  headaches: .pearls/docs/headaches
  retros: .pearls/docs/retros
```

### 2. Move doc directories

```bash
mkdir -p .pearls/docs
git mv docs/planning/epics .pearls/docs/epics 2>/dev/null || true
git mv docs/planning/ideas .pearls/docs/ideas 2>/dev/null || true
git mv docs/planning/headaches .pearls/docs/headaches 2>/dev/null || true
# retros may be at docs/planning/ root or a subdir — check first
```

Not all repos have all directories. Skip what doesn't exist.

### 3. Simplify madreperla.yaml

Replace providers block:

```yaml
# before
providers:
  issues:
    name: pearls
    config: "prl configure"
    usage: "prl docs"
  docs:
    name: repo
    usage: "cat docs/README.md"
    planning: docs/planning
    epics: docs/planning/epics
    ideas: docs/planning/ideas
    headaches: docs/planning/headaches
    retro: docs/planning

# after
providers:
  issues: pearls
  docs: pearls
```

### 4. Regenerate

```bash
prl configure
madp configure --provider claude
```

### 5. Verify and commit

```bash
# Check generated commands have resolved paths
cat commands/review-docs.md | grep -v '{docs\.'  # should have real paths
git add -A
git commit -m "chore: migrate to .pearls/docs/, simplify providers config"
git push
```

## Target repos

All repos in medici.yaml: pearls, madreperla, medici, git-vendored, git-semver, git-dogfood.

Plus medici-dev workspace itself (orchestration dirs move from `docs/epics/` to `.pearls/docs/epics/`).

## Acceptance criteria

- All target repos have `.pearls/docs/` structure
- No `docs/planning/epics/`, `docs/planning/ideas/`, `docs/planning/headaches/` in any repo
- `madreperla.yaml` has simplified providers config in all repos
- Generated commands have fully resolved paths
