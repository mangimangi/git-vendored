#!/bin/bash
# session-resume.sh — resume session for pearls (prl shim + resume prompt)
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

# Resume prompt (minimal context)
prl prompt --resume
