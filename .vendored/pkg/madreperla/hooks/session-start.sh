#!/bin/bash
# hooks/session-start.sh (madreperla)
# Creates the madp CLI shim and generates session prompt.
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

# Generate session prompt (always call madp for startup context)
if [ -n "${MADP_MODE:-}" ]; then
    # Use specified prompt mode
    madp "$MADP_MODE"
else
    # Default: just output the intro
    madp
fi
