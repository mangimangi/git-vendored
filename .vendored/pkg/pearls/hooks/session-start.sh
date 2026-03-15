#!/bin/bash
# session-start.sh — full startup for pearls (prl shim + prompt)
set -euo pipefail

PEARLS_DIR="${VENDOR_PKG_DIR:-.vendored/pkg/pearls}"
PRL_PY="$PEARLS_DIR/prl.py"

# Create prl shim in ~/.local/bin
SHIM_DIR="$HOME/.local/bin"
mkdir -p "$SHIM_DIR"

cat > "$SHIM_DIR/prl" << EOF
#!/bin/bash
exec python3 "$PRL_PY" "\$@"
EOF
chmod +x "$SHIM_DIR/prl"

# Verify shim works
if ! command -v prl &>/dev/null; then
    exit 0
fi

# Generate session prompt
if [ -n "${PRL_PROMPT_MODE:-}" ]; then
    prl prompt "$PRL_PROMPT_MODE"
else
    prl prompt
fi
