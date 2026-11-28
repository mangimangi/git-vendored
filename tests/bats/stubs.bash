# tests/bats/stubs.bash - shared setup for install.bats and vendor-helpers.bats.
#
# Every test runs in its own temp dir with HOME and XDG_CACHE_HOME pointed
# inside it. `curl` and `gh` are replaced by stub scripts in $STUB_BIN that
# never touch the network and log each call to $STUB_LOG, one line per call,
# with every argument wrapped in [brackets] so tests can match exact args:
#
#   curl [-fsSL] [-H] [Authorization: token t] [https://...] [-o] [dest]
#
# curl stub: writes "curl:<url>" to the -o destination. Exits 22 without
#   creating the destination when the URL matches the glob in $CURL_FAIL.
# gh stub (`gh api <endpoint> --jq <expr>`): when <expr> is `.content`, prints
#   base64 of $GH_CONTENT/<path> if that file exists, else of
#   "gh:<path>@<ref>". Any other <expr> is a directory listing: prints
#   $GH_LISTINGS/<path>.tsv, or fails (exit 1) when that file is missing.
#   Exits 1 with an error on stderr when <endpoint> matches the glob in
#   $GH_FAIL.
#
# Commands run with PATH=$RUN_PATH (default: stubs first, then the normal
# PATH). use_no_gh drops the gh stub and builds RUN_PATH from a restricted
# bin dir of symlinks, so no gh (stub or real) is on it.

REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"

stubs_setup() {
    export LC_ALL=C
    export HOME="$BATS_TEST_TMPDIR/home"
    export XDG_CACHE_HOME="$BATS_TEST_TMPDIR/cache"
    mkdir -p "$HOME" "$XDG_CACHE_HOME"
    # No test reads a token from the ambient environment (CI holds real
    # secrets); a test that needs one passes a fake value.
    unset GH_TOKEN VENDOR_PAT CICD_WRITE_TOKEN CICD_READ_TOKEN VENDOR_REF VENDOR_REPO VENDOR_MANIFEST VENDOR_CHECKOUT \
        VENDOR_INSTALL_DIR CURL_FAIL GH_FAIL GITHUB_TOKEN

    STUB_BIN="$BATS_TEST_TMPDIR/stubs"
    export STUB_LOG="$BATS_TEST_TMPDIR/stub.log"
    export GH_CONTENT="$BATS_TEST_TMPDIR/gh-content"
    export GH_LISTINGS="$BATS_TEST_TMPDIR/gh-listings"
    mkdir -p "$STUB_BIN" "$GH_CONTENT" "$GH_LISTINGS"
    : > "$STUB_LOG"

    cat > "$STUB_BIN/curl" <<'STUB'
#!/bin/bash
line="curl"
for a in "$@"; do line+=" [$a]"; done
printf '%s\n' "$line" >> "$STUB_LOG"
dest="" url=""
while [ $# -gt 0 ]; do
    case "$1" in
        -o) dest="$2"; shift 2 ;;
        -H) shift 2 ;;
        -*) shift ;;
        *) url="$1"; shift ;;
    esac
done
if [ -n "${CURL_FAIL:-}" ] && [[ "$url" == $CURL_FAIL ]]; then
    echo "curl: (22) The requested URL returned error: 404" >&2
    exit 22
fi
printf 'curl:%s\n' "$url" > "$dest"
STUB

    cat > "$STUB_BIN/gh" <<'STUB'
#!/bin/bash
line="gh"
for a in "$@"; do line+=" [$a]"; done
printf '%s\n' "$line" >> "$STUB_LOG"
endpoint="$2" expr="$4"
path="${endpoint#repos/*/*/contents/}"
path="${path%%\?*}"
ref="${endpoint##*ref=}"
if [ -n "${GH_FAIL:-}" ] && [[ "$endpoint" == $GH_FAIL ]]; then
    echo "gh: HTTP 401: Bad credentials" >&2
    exit 1
fi
if [ "$expr" = ".content" ]; then
    if [ -f "$GH_CONTENT/$path" ]; then
        base64 < "$GH_CONTENT/$path"
    else
        printf 'gh:%s@%s\n' "$path" "$ref" | base64
    fi
else
    [ -f "$GH_LISTINGS/$path.tsv" ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
    cat "$GH_LISTINGS/$path.tsv"
fi
STUB
    chmod +x "$STUB_BIN/curl" "$STUB_BIN/gh"
    RUN_PATH="$STUB_BIN:$PATH"
}

# Remove gh from the PATH commands run with: drop the stub, and replace the
# system PATH with a bin dir holding only the tools the scripts need.
use_no_gh() {
    rm -f "$STUB_BIN/gh"
    local sysbin="$BATS_TEST_TMPDIR/sysbin" tool src
    mkdir -p "$sysbin"
    for tool in bash base64 cat chmod mkdir rm sort dirname env; do
        # Prefer the system copy: PATH may hold wrappers that need other tools.
        src="$(PATH=/usr/bin:/bin:/usr/local/bin:$PATH command -v "$tool")"
        ln -sf "$src" "$sysbin/$tool"
    done
    RUN_PATH="$STUB_BIN:$sysbin"
    run env PATH="$RUN_PATH" bash -c 'command -v gh'
    [ "$status" -ne 0 ]
}

# Number of logged calls to the given stub.
stub_calls() {
    grep -c "^$1 " "$STUB_LOG" || true
}

# Assert the stub log has a line equal to $1.
assert_logged() {
    grep -qxF -- "$1" "$STUB_LOG" || {
        echo "expected log line: $1" >&2
        echo "--- stub log ---" >&2
        cat "$STUB_LOG" >&2
        return 1
    }
}

refute_logged_match() {
    if grep -qF -- "$1" "$STUB_LOG"; then
        echo "unexpected log text: $1" >&2
        cat "$STUB_LOG" >&2
        return 1
    fi
}

is_executable() { [ -x "$1" ]; }
