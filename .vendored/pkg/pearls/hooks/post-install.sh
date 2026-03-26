#!/bin/bash
# hooks/post-install.sh
# Runs once after vendored install (when .git/ exists).
# Registers merge driver and installs pre-push hook symlink.
set -euo pipefail

# Resolve project root — prefer env var, fall back to discovery
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}}"
# Resolve package dir — prefer env var, fall back to discovery
if [ -n "${VENDOR_PKG_DIR:-}" ]; then
    PEARLS_DIR="$VENDOR_PKG_DIR"
elif [ -f "$PROJECT_DIR/.vendored/pkg/pearls/prl.py" ]; then
    PEARLS_DIR="$PROJECT_DIR/.vendored/pkg/pearls"
elif [ -f "$PROJECT_DIR/.pearls/prl.py" ]; then
    PEARLS_DIR="$PROJECT_DIR/.pearls"
else
    echo "Error: prl.py not found. Run the install workflow first." >&2
    exit 1
fi

# Require .git/ — post-install hooks only run when git is available
if [ ! -d "$PROJECT_DIR/.git" ]; then
    echo "Skipping post-install: .git/ not found (CI install without checkout?)" >&2
    exit 0
fi

# Register merge driver for issues.jsonl (idempotent)
MERGE_DRIVER="$PEARLS_DIR/merge-driver.py"
if [ -f "$MERGE_DRIVER" ]; then
    git config merge.prl-jsonl.name "Pearls JSONL merge driver"
    git config merge.prl-jsonl.driver "python3 \"$MERGE_DRIVER\" %O %A %B"
fi

# Install pre-push hook (symlink)
PRE_PUSH_SRC="$PEARLS_DIR/hooks/pre-push"
PRE_PUSH_DST="$PROJECT_DIR/.git/hooks/pre-push"
if [ -f "$PRE_PUSH_SRC" ]; then
    # Compute relative symlink target from .git/hooks/ to the pre-push source
    PRE_PUSH_REL=$(python3 -c "import os.path; print(os.path.relpath('$PRE_PUSH_SRC', '$PROJECT_DIR/.git/hooks'))")
    if [ -L "$PRE_PUSH_DST" ]; then
        # Already a symlink — verify it points to our hook
        LINK_TARGET=$(readlink "$PRE_PUSH_DST")
        if [[ "$LINK_TARGET" != *"hooks/pre-push"* ]] && [[ "$LINK_TARGET" != *"pearls"* ]]; then
            echo "Warning: .git/hooks/pre-push is a symlink to $LINK_TARGET, skipping prl pre-push hook" >&2
        fi
    elif [ -f "$PRE_PUSH_DST" ]; then
        echo "Warning: .git/hooks/pre-push already exists, skipping prl pre-push hook" >&2
    else
        ln -s "$PRE_PUSH_REL" "$PRE_PUSH_DST"
    fi
fi
