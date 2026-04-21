# Migrate to .pearls/docs/ and simplified providers config

> Per-repo planning doc for epic `gv-3e1b`

## Design decisions

- **One issue**: entire migration is one atomic issue — config + move + regenerate + verify. No partial states.
- **All planning docs move**: everything under `docs/planning/` moves to `.pearls/docs/`. Standalone docs at `docs/planning/` root (e.g. `gh-extension.md`) move to `.pearls/docs/` root.
- **Retros**: create `.pearls/docs/retros/` with `.gitkeep` even if no retros exist yet.
- **`docs:` in madreperla.yaml**: stays as-is (`[AGENTS.md, README.md, docs/]`). It's the repo context list, not the pearls doc structure.
- **Missing dirs**: skip `git mv` for dirs that don't exist. Use `2>/dev/null || true`.

## Migration steps

### 1. Update pearls.yaml

Add `docs:` section:

```yaml
docs:
  planning: .pearls/docs
  epics: .pearls/docs/epics
  ideas: .pearls/docs/ideas
  headaches: .pearls/docs/headaches
  retros: .pearls/docs/retros
```

### 2. Move doc directories

```bash
mkdir -p .pearls/docs/retros
# Move subdirs
git mv docs/planning/epics .pearls/docs/epics 2>/dev/null || true
git mv docs/planning/ideas .pearls/docs/ideas 2>/dev/null || true
git mv docs/planning/headaches .pearls/docs/headaches 2>/dev/null || true
# Move standalone docs at docs/planning/ root
for f in docs/planning/*.md; do git mv "$f" .pearls/docs/ 2>/dev/null || true; done
touch .pearls/docs/retros/.gitkeep
# Remove empty docs/planning/ if nothing left
rmdir docs/planning 2>/dev/null || true
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
# Check generated commands have resolved paths — no literal {docs. remaining
grep -r '{docs\.' commands/ && echo "FAIL: unresolved vars" || echo "PASS"
git add -A
git commit -m "chore: migrate to .pearls/docs/, simplify providers config"
git push
```

## Acceptance criteria

- `.pearls/docs/` structure exists with epics, ideas, headaches, retros subdirs
- No `docs/planning/epics/`, `docs/planning/ideas/`, `docs/planning/headaches/` remain
- `madreperla.yaml` has simplified `providers: {issues: pearls, docs: pearls}`
- Generated commands have fully resolved paths (no `{docs.*}` literals)
- `docs/planning/` is empty or removed — all content moved to `.pearls/docs/`
