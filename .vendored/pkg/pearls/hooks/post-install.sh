#!/bin/bash
# post-install.sh — git-dependent setup for pearls
# Runs after install.sh when .git/ exists. Must be idempotent.
set -euo pipefail

PEARLS_DIR="${VENDOR_PKG_DIR:-.vendored/pkg/pearls}"
PROJECT="${PROJECT_DIR:-.}"

# Register merge driver for issues.jsonl (idempotent)
MERGE_DRIVER="$PEARLS_DIR/merge-driver.py"
if [ -f "$MERGE_DRIVER" ]; then
    git config merge.prl-jsonl.name "Pearls JSONL merge driver"
    git config merge.prl-jsonl.driver "python3 \"$MERGE_DRIVER\" %O %A %B"
fi

# Install pre-push hook (symlink)
PRE_PUSH_SRC="$PEARLS_DIR/hooks/pre-push"
PRE_PUSH_DST="$PROJECT/.git/hooks/pre-push"
if [ -f "$PRE_PUSH_SRC" ]; then
    PRE_PUSH_REL=$(python3 -c "import os.path; print(os.path.relpath('$PRE_PUSH_SRC', '$PROJECT/.git/hooks'))")
    if [ -L "$PRE_PUSH_DST" ]; then
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
