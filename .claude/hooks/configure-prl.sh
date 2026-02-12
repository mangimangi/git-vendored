#!/bin/bash
# .claude/hooks/configure-prl.sh
# Configures prl CLI for this project (runs on Claude Code session start)
set -euo pipefail

# Parse arguments
RESUME_MODE=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --resume)
            RESUME_MODE=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
PRL_PY="$PROJECT_DIR/.pearls/prl.py"

# Verify prl.py exists
if [ ! -f "$PRL_PY" ]; then
    echo "Error: .pearls/prl.py not found. Run the install-pearls workflow first." >&2
    exit 1
fi

# Create wrapper in ~/.local/bin
SHIM_DIR="$HOME/.local/bin"
mkdir -p "$SHIM_DIR"

cat > "$SHIM_DIR/prl" << EOF
#!/bin/bash
exec python3 "$PRL_PY" "\$@"
EOF
chmod +x "$SHIM_DIR/prl"

# Register merge driver for issues.jsonl (idempotent)
MERGE_DRIVER="$PROJECT_DIR/.pearls/merge-driver.py"
if [ -f "$MERGE_DRIVER" ]; then
    git config merge.prl-jsonl.name "Pearls JSONL merge driver"
    git config merge.prl-jsonl.driver "python3 \"$MERGE_DRIVER\" %O %A %B"
fi

# Install pre-commit hook
# Try .vendored/hooks/pre-commit first (vendor file protection check),
# fall back to .pearls/hooks/pre-commit (legacy location)
PRE_COMMIT_DST="$PROJECT_DIR/.git/hooks/pre-commit"
PRE_COMMIT_SRC=""
PRE_COMMIT_REL=""
if [ -f "$PROJECT_DIR/.vendored/hooks/pre-commit" ]; then
    PRE_COMMIT_SRC="$PROJECT_DIR/.vendored/hooks/pre-commit"
    PRE_COMMIT_REL="../../.vendored/hooks/pre-commit"
elif [ -f "$PROJECT_DIR/.pearls/hooks/pre-commit" ]; then
    PRE_COMMIT_SRC="$PROJECT_DIR/.pearls/hooks/pre-commit"
    PRE_COMMIT_REL="../../.pearls/hooks/pre-commit"
fi
if [ -n "$PRE_COMMIT_SRC" ]; then
    if [ -L "$PRE_COMMIT_DST" ]; then
        # Already a symlink — verify it points to a known hook
        LINK_TARGET=$(readlink "$PRE_COMMIT_DST")
        if [[ "$LINK_TARGET" != *".vendored/hooks/pre-commit"* ]] && \
           [[ "$LINK_TARGET" != *".pearls/hooks/pre-commit"* ]]; then
            echo "Warning: .git/hooks/pre-commit is a symlink to $LINK_TARGET, skipping hook install" >&2
        fi
    elif [ -f "$PRE_COMMIT_DST" ]; then
        echo "Warning: .git/hooks/pre-commit already exists, skipping hook install" >&2
    else
        ln -s "$PRE_COMMIT_REL" "$PRE_COMMIT_DST"
    fi
fi

# Install pre-push hook
# Try .vendored/hooks/pre-push first, fall back to .pearls/hooks/pre-push
PRE_PUSH_DST="$PROJECT_DIR/.git/hooks/pre-push"
PRE_PUSH_SRC=""
PRE_PUSH_REL=""
if [ -f "$PROJECT_DIR/.vendored/hooks/pre-push" ]; then
    PRE_PUSH_SRC="$PROJECT_DIR/.vendored/hooks/pre-push"
    PRE_PUSH_REL="../../.vendored/hooks/pre-push"
elif [ -f "$PROJECT_DIR/.pearls/hooks/pre-push" ]; then
    PRE_PUSH_SRC="$PROJECT_DIR/.pearls/hooks/pre-push"
    PRE_PUSH_REL="../../.pearls/hooks/pre-push"
fi
if [ -n "$PRE_PUSH_SRC" ]; then
    if [ -L "$PRE_PUSH_DST" ]; then
        # Already a symlink — verify it points to a known hook
        LINK_TARGET=$(readlink "$PRE_PUSH_DST")
        if [[ "$LINK_TARGET" != *".vendored/hooks/pre-push"* ]] && \
           [[ "$LINK_TARGET" != *".pearls/hooks/pre-push"* ]]; then
            echo "Warning: .git/hooks/pre-push is a symlink to $LINK_TARGET, skipping hook install" >&2
        fi
    elif [ -f "$PRE_PUSH_DST" ]; then
        echo "Warning: .git/hooks/pre-push already exists, skipping hook install" >&2
    else
        ln -s "$PRE_PUSH_REL" "$PRE_PUSH_DST"
    fi
fi

# Verify it works
if ! command -v prl &>/dev/null; then
    exit 0
fi

# On resume, skip prompt generation (keep context minimal)
if [ "$RESUME_MODE" = true ]; then
    prl prompt --resume
    exit 0
fi

# Generate session prompt (always call prl prompt for startup context)
if [ -n "${PRL_PROMPT_MODE:-}" ]; then
    # Use specified prompt mode
    prl prompt "$PRL_PROMPT_MODE"
else
    # Default: just output the intro
    prl prompt
fi
