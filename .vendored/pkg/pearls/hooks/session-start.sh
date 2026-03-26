#!/bin/bash
# hooks/session-start.sh
# Runs on every Claude Code session start.
# Creates the prl CLI shim only — madreperla handles madp shim and prompt.
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
PRL_PY="$PEARLS_DIR/prl.py"

# Create prl wrapper in ~/.local/bin
SHIM_DIR="$HOME/.local/bin"
mkdir -p "$SHIM_DIR"

cat > "$SHIM_DIR/prl" << EOF
#!/bin/bash
exec python3 "$PRL_PY" "\$@"
EOF
chmod +x "$SHIM_DIR/prl"
