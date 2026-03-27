#!/bin/bash
# hooks/session-resume.sh (madreperla)
# Creates the madp CLI shim and generates minimal resume prompt.
set -euo pipefail

# Resolve project root — prefer env var, fall back to discovery
PROJECT_DIR="${PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}}"

# Resolve madreperla package dir
if [ -n "${VENDOR_PKG_DIR:-}" ]; then
    MADP_DIR="$VENDOR_PKG_DIR"
elif [ -d "$PROJECT_DIR/.vendored/pkg/pearls/.madreperla" ]; then
    MADP_DIR="$PROJECT_DIR/.vendored/pkg/pearls/.madreperla"
elif [ -d "$PROJECT_DIR/.madreperla" ]; then
    MADP_DIR="$PROJECT_DIR/.madreperla"
else
    echo "Warning: madreperla not found, skipping madp setup." >&2
    exit 0
fi

# Create madp wrapper in ~/.local/bin
SHIM_DIR="$HOME/.local/bin"
mkdir -p "$SHIM_DIR"

if [ -f "$MADP_DIR/cli.py" ]; then
    cat > "$SHIM_DIR/madp" << EOF
#!/bin/bash
exec python3 "$MADP_DIR/cli.py" "\$@"
EOF
    chmod +x "$SHIM_DIR/madp"
fi

# Verify madp shim works
if ! command -v madp &>/dev/null; then
    exit 0
fi

# Resume: mode-aware when MADP_MODE is set
if [ -n "${MADP_MODE:-}" ]; then
    madp --resume "$MADP_MODE"
else
    madp --resume
fi
