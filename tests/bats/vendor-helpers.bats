#!/usr/bin/env bats
# Tests for templates/lib/vendor-helpers.sh, with curl and gh stubbed.

load stubs

RAW="https://raw.githubusercontent.com"
LIB="$REPO_ROOT/templates/lib/vendor-helpers.sh"

setup() {
    stubs_setup
    PROJ="$BATS_TEST_TMPDIR/proj"
    mkdir -p "$PROJ"
    cd "$PROJ"
    export VENDOR_REPO=o/r
    export VENDOR_REF=v1.0.0
}

# Source the library (which turns on set -euo pipefail, as in a real vendor
# install.sh) and run the given shell snippet.
run_lib() {
    run env PATH="$RUN_PATH" bash -c 'source "$0"; eval "$1"' "$LIB" "$1"
}

# ── _vendor_auth_header ─────────────────────────────────────────────────

@test "auth header: VENDOR_PAT overrides GH_TOKEN" {
    export VENDOR_PAT=pat GH_TOKEN=tok
    run_lib '_vendor_auth_header'
    [ "$status" -eq 0 ]
    [ "$output" = "Authorization: token pat" ]
}

@test "auth header: GH_TOKEN when VENDOR_PAT unset" {
    export GH_TOKEN=tok
    run_lib '_vendor_auth_header'
    [ "$status" -eq 0 ]
    [ "$output" = "Authorization: token tok" ]
}

@test "auth header: GH_TOKEN when VENDOR_PAT empty" {
    export VENDOR_PAT="" GH_TOKEN=tok
    run_lib '_vendor_auth_header'
    [ "$output" = "Authorization: token tok" ]
}

@test "auth header: VENDOR_PAT alone" {
    export VENDOR_PAT=pat
    run_lib '_vendor_auth_header'
    [ "$output" = "Authorization: token pat" ]
}

@test "auth header: no token gives no header and status 0" {
    run_lib '_vendor_auth_header; echo "rc=$?"'
    [ "$status" -eq 0 ]
    [ "$output" = "rc=0" ]
}

@test "auth header: empty tokens give no header" {
    export VENDOR_PAT="" GH_TOKEN=""
    run_lib '_vendor_auth_header'
    [ "$status" -eq 0 ]
    [ -z "$output" ]
}

# ── _vendor_download ────────────────────────────────────────────────────

@test "download: VENDOR_REPO missing errors before any fetch" {
    unset VENDOR_REPO
    run_lib '_vendor_download a.txt out/a.txt; echo after'
    [ "$status" -ne 0 ]
    [[ "$output" == *"VENDOR_REPO not set"* ]]
    [[ "$output" != *after* ]]
    [ ! -e out ]
    [ "$(stub_calls curl)" -eq 0 ]
}

@test "download: VENDOR_REF missing errors before any fetch" {
    unset VENDOR_REF
    run_lib '_vendor_download a.txt out/a.txt'
    [ "$status" -ne 0 ]
    [[ "$output" == *"VENDOR_REF not set"* ]]
    [ ! -e out ]
    [ "$(stub_calls curl)" -eq 0 ]
}

@test "download: empty VENDOR_REPO is treated as missing" {
    export VENDOR_REPO=""
    run_lib '_vendor_download a.txt a.txt'
    [ "$status" -ne 0 ]
    [[ "$output" == *"VENDOR_REPO not set"* ]]
}

@test "download: creates parent directories" {
    run_lib '_vendor_download src/a.txt deep/nested/dir/a.txt'
    [ "$status" -eq 0 ]
    [ -d deep/nested/dir ]
    [ "$(cat deep/nested/dir/a.txt)" = "curl:$RAW/o/r/v1.0.0/src/a.txt" ]
}

@test "download: token + gh succeeds -> gh api contents, base64-decoded, no curl" {
    export GH_TOKEN=tok
    run_lib '_vendor_download src/a.txt a.txt'
    [ "$status" -eq 0 ]
    assert_logged "gh [api] [repos/o/r/contents/src/a.txt?ref=v1.0.0] [--jq] [.content]"
    [ "$(stub_calls curl)" -eq 0 ]
    [ "$(cat a.txt)" = "gh:src/a.txt@v1.0.0" ]
}

@test "download: gh path decodes multi-line base64 byte for byte" {
    export GH_TOKEN=tok
    mkdir -p "$GH_CONTENT/src"
    for i in $(seq 1 40); do echo "line $i of a long file that wraps base64 output"; done \
        > "$GH_CONTENT/src/big.txt"
    run_lib '_vendor_download src/big.txt big.txt'
    [ "$status" -eq 0 ]
    cmp "$GH_CONTENT/src/big.txt" big.txt
}

@test "download: VENDOR_PAT alone selects the gh path" {
    export VENDOR_PAT=pat
    run_lib '_vendor_download src/a.txt a.txt'
    [ "$status" -eq 0 ]
    [ "$(stub_calls gh)" -eq 1 ]
    [ "$(stub_calls curl)" -eq 0 ]
}

@test "download: gh failure falls back to curl with the auth header, gh stderr hidden" {
    export GH_TOKEN=tok GH_FAIL="*"
    run_lib '_vendor_download src/a.txt a.txt'
    [ "$status" -eq 0 ]
    [ "$(stub_calls gh)" -eq 1 ]
    assert_logged "curl [-fsSL] [-H] [Authorization: token tok] [$RAW/o/r/v1.0.0/src/a.txt] [-o] [a.txt]"
    [[ "$output" != *"Bad credentials"* ]]
    [ "$(cat a.txt)" = "curl:$RAW/o/r/v1.0.0/src/a.txt" ]
}

@test "download: curl fallback uses VENDOR_PAT over GH_TOKEN" {
    export GH_TOKEN=tok VENDOR_PAT=pat GH_FAIL="*"
    run_lib '_vendor_download src/a.txt a.txt'
    [ "$status" -eq 0 ]
    assert_logged "curl [-fsSL] [-H] [Authorization: token pat] [$RAW/o/r/v1.0.0/src/a.txt] [-o] [a.txt]"
}

@test "download: token but no gh on PATH -> curl with the auth header" {
    export GH_TOKEN=tok
    use_no_gh
    run_lib '_vendor_download src/a.txt a.txt'
    [ "$status" -eq 0 ]
    assert_logged "curl [-fsSL] [-H] [Authorization: token tok] [$RAW/o/r/v1.0.0/src/a.txt] [-o] [a.txt]"
    [ "$(stub_calls gh)" -eq 0 ]
}

@test "download: no token -> curl without -H, gh not used even when on PATH" {
    run_lib '_vendor_download src/a.txt a.txt'
    [ "$status" -eq 0 ]
    assert_logged "curl [-fsSL] [$RAW/o/r/v1.0.0/src/a.txt] [-o] [a.txt]"
    refute_logged_match "[-H]"
    [ "$(stub_calls gh)" -eq 0 ]
}

@test "download: curl failure (no token) returns nonzero" {
    export CURL_FAIL="*"
    run_lib '_vendor_download src/a.txt a.txt || echo "rc=$?"'
    [ "$status" -eq 0 ]
    [[ "$output" == *"rc=22"* ]]
}

@test "download: gh and curl both failing returns nonzero" {
    export GH_TOKEN=tok GH_FAIL="*" CURL_FAIL="*"
    run_lib '_vendor_download src/a.txt a.txt || echo "rc=$?"'
    [[ "$output" == *"rc=22"* ]]
    [ "$(stub_calls gh)" -eq 1 ]
    [ "$(stub_calls curl)" -eq 1 ]
}

# ── _vendor_manifest_append ─────────────────────────────────────────────

@test "manifest append: appends to \$VENDOR_MANIFEST, keeping existing lines" {
    export VENDOR_MANIFEST="$BATS_TEST_TMPDIR/m.files"
    echo existing > "$VENDOR_MANIFEST"
    run_lib '_vendor_manifest_append one; _vendor_manifest_append two'
    [ "$status" -eq 0 ]
    [ "$(cat "$VENDOR_MANIFEST")" = "existing
one
two" ]
}

@test "manifest append: VENDOR_MANIFEST unset or empty writes nothing, status 0" {
    run_lib '_vendor_manifest_append one; echo "rc=$?"'
    [ "$status" -eq 0 ]
    [ "$output" = "rc=0" ]
    export VENDOR_MANIFEST=""
    run_lib '_vendor_manifest_append one; echo "rc=$?"'
    [ "$output" = "rc=0" ]
    [ -z "$(ls -A "$PROJ")" ]
}

# ── fetch_file ──────────────────────────────────────────────────────────

@test "fetch_file: downloads, records in manifest, not executable without +x" {
    export VENDOR_MANIFEST="$BATS_TEST_TMPDIR/m.files"
    run_lib 'fetch_file prl.py pkg/prl/prl.py'
    [ "$status" -eq 0 ]
    [ "$(cat pkg/prl/prl.py)" = "curl:$RAW/o/r/v1.0.0/prl.py" ]
    [ ! -x pkg/prl/prl.py ]
    [ "$(cat "$VENDOR_MANIFEST")" = "pkg/prl/prl.py" ]
}

@test "fetch_file: +x makes the file executable" {
    run_lib 'fetch_file prl pkg/prl/prl +x'
    [ "$status" -eq 0 ]
    [ -x pkg/prl/prl ]
}

@test "fetch_file: a third arg other than +x does not chmod" {
    run_lib 'fetch_file prl prl x'
    [ "$status" -eq 0 ]
    [ ! -x prl ]
}

@test "fetch_file: no manifest when VENDOR_MANIFEST unset" {
    run_lib 'fetch_file a.txt a.txt'
    [ "$status" -eq 0 ]
    [ "$(ls -A "$PROJ")" = "a.txt" ]
    [ "$(ls -A "$BATS_TEST_TMPDIR" | tr '\n' ' ')" = "cache gh-content gh-listings home proj stub.log stubs " ]
}

@test "fetch_file: gh path writes decoded content" {
    export GH_TOKEN=tok VENDOR_MANIFEST="$BATS_TEST_TMPDIR/m.files"
    run_lib 'fetch_file bin/tool out/tool +x'
    [ "$status" -eq 0 ]
    [ "$(cat out/tool)" = "gh:bin/tool@v1.0.0" ]
    [ -x out/tool ]
    [ "$(cat "$VENDOR_MANIFEST")" = "out/tool" ]
}

@test "fetch_file: curl failure exits the script (set -e), no chmod, no manifest entry" {
    export CURL_FAIL="*" VENDOR_MANIFEST="$BATS_TEST_TMPDIR/m.files"
    run_lib 'fetch_file a a +x; echo after'
    [ "$status" -eq 22 ]
    [[ "$output" != *after* ]]
    [ ! -e a ]
    [ ! -e "$VENDOR_MANIFEST" ]
}

@test "fetch_file: missing VENDOR_REPO errors" {
    unset VENDOR_REPO
    run_lib 'fetch_file a a'
    [ "$status" -ne 0 ]
    [[ "$output" == *"VENDOR_REPO not set"* ]]
}

# ── fetch_dir ───────────────────────────────────────────────────────────

listing() {
    # listing <repo_path> <tsv lines...>
    local p="$1"; shift
    mkdir -p "$(dirname "$GH_LISTINGS/$p")"
    printf '%s\n' "$@" > "$GH_LISTINGS/$p.tsv"
}

@test "fetch_dir: missing VENDOR_REPO / VENDOR_REF error" {
    unset VENDOR_REPO
    run_lib 'fetch_dir hooks out'
    [ "$status" -ne 0 ]
    [[ "$output" == *"VENDOR_REPO not set"* ]]
    [ ! -e out ]
    export VENDOR_REPO=o/r
    unset VENDOR_REF
    run_lib 'fetch_dir hooks out'
    [ "$status" -ne 0 ]
    [[ "$output" == *"VENDOR_REF not set"* ]]
    [ ! -e out ]
}

@test "fetch_dir: lists via gh api with the type/path/name jq filter" {
    listing hooks
    run_lib 'fetch_dir hooks out'
    [ "$status" -eq 0 ]
    assert_logged 'gh [api] [repos/o/r/contents/hooks?ref=v1.0.0] [--jq] [.[] | "\(.type)\t\(.path)\t\(.name)"]'
}

@test "fetch_dir: empty listing still creates the local dir" {
    listing hooks
    run_lib 'fetch_dir hooks out/hooks'
    [ "$status" -eq 0 ]
    [ -d out/hooks ]
    [ -z "$(ls -A out/hooks)" ]
    [ "$(stub_calls curl)" -eq 0 ]
}

@test "fetch_dir: recurses into dirs, fetches files, skips blank lines and other types" {
    export VENDOR_MANIFEST="$BATS_TEST_TMPDIR/m.files"
    listing tpl/hooks \
        $'file\ttpl/hooks/a.sh\ta.sh' \
        '' \
        $'symlink\ttpl/hooks/link\tlink' \
        $'dir\ttpl/hooks/sub\tsub' \
        $'file\ttpl/hooks/z.sh\tz.sh'
    listing tpl/hooks/sub \
        $'file\ttpl/hooks/sub/b.sh\tb.sh' \
        $'dir\ttpl/hooks/sub/deeper\tdeeper'
    listing tpl/hooks/sub/deeper \
        $'file\ttpl/hooks/sub/deeper/c.sh\tc.sh'
    run_lib 'fetch_dir tpl/hooks out'
    [ "$status" -eq 0 ]
    [ "$(cat out/a.sh)" = "curl:$RAW/o/r/v1.0.0/tpl/hooks/a.sh" ]
    [ "$(cat out/z.sh)" = "curl:$RAW/o/r/v1.0.0/tpl/hooks/z.sh" ]
    [ "$(cat out/sub/b.sh)" = "curl:$RAW/o/r/v1.0.0/tpl/hooks/sub/b.sh" ]
    [ "$(cat out/sub/deeper/c.sh)" = "curl:$RAW/o/r/v1.0.0/tpl/hooks/sub/deeper/c.sh" ]
    [ ! -e out/link ]
    refute_logged_match "tpl/hooks/link"
    [ "$(stub_calls curl)" -eq 4 ]
    [ "$(stub_calls gh)" -eq 3 ]
    [ "$(cat "$VENDOR_MANIFEST")" = "out/a.sh
out/sub/b.sh
out/sub/deeper/c.sh
out/z.sh" ]
}

@test "fetch_dir: with a token, files come through gh contents" {
    export GH_TOKEN=tok
    listing d $'file\td/f.txt\tf.txt'
    run_lib 'fetch_dir d out'
    [ "$status" -eq 0 ]
    assert_logged "gh [api] [repos/o/r/contents/d/f.txt?ref=v1.0.0] [--jq] [.content]"
    [ "$(cat out/f.txt)" = "gh:d/f.txt@v1.0.0" ]
    [ "$(stub_calls curl)" -eq 0 ]
}

@test "fetch_dir: gh listing failure -> error message, return 1, nothing fetched" {
    export GH_FAIL="*"
    run_lib 'fetch_dir hooks out || echo "rc=$?"'
    [ "$status" -eq 0 ]
    [[ "$output" == *"Error: failed to list directory hooks from o/r"* ]]
    [[ "$output" == *"rc=1"* ]]
    [[ "$output" != *"Bad credentials"* ]]
    [ "$(stub_calls curl)" -eq 0 ]
}

@test "fetch_dir: gh listing failure exits the script with status 1 under set -e" {
    run_lib 'fetch_dir missing out; echo after'
    [ "$status" -eq 1 ]
    [[ "$output" == *"Error: failed to list directory missing from o/r"* ]]
    [[ "$output" != *after* ]]
}

@test "fetch_dir: no gh on PATH -> listing error, return 1" {
    use_no_gh
    run_lib 'fetch_dir hooks out || echo "rc=$?"'
    [[ "$output" == *"Error: failed to list directory hooks from o/r"* ]]
    [[ "$output" == *"rc=1"* ]]
}

@test "fetch_dir: a nested listing failure propagates" {
    listing top $'dir\ttop/sub\tsub'
    run_lib 'fetch_dir top out; echo after'
    [ "$status" -eq 1 ]
    [[ "$output" == *"Error: failed to list directory top/sub from o/r"* ]]
    [[ "$output" != *after* ]]
}

@test "fetch_dir: curl failure on a file propagates and stops later entries" {
    export VENDOR_MANIFEST="$BATS_TEST_TMPDIR/m.files"
    export CURL_FAIL="*/d/bad.txt"
    listing d $'file\td/ok.txt\tok.txt' $'file\td/bad.txt\tbad.txt' $'file\td/later.txt\tlater.txt'
    run_lib 'fetch_dir d out; echo after'
    [ "$status" -eq 22 ]
    [[ "$output" != *after* ]]
    [ -f out/ok.txt ]
    [ ! -e out/bad.txt ]
    [ ! -e out/later.txt ]
    [ "$(cat "$VENDOR_MANIFEST")" = "out/ok.txt" ]
}
