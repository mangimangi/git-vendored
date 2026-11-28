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

@test "auth header: CICD_READ_TOKEN first, over the write and old tokens" {
    export CICD_READ_TOKEN=read CICD_WRITE_TOKEN=write VENDOR_PAT=pat GH_TOKEN=tok
    run_lib '_vendor_auth_header'
    [ "$status" -eq 0 ]
    [ "$output" = "Authorization: token read" ]
}

@test "auth header: CICD_WRITE_TOKEN when CICD_READ_TOKEN is unset or empty" {
    export CICD_WRITE_TOKEN=write VENDOR_PAT=pat GH_TOKEN=tok
    run_lib '_vendor_auth_header'
    [ "$output" = "Authorization: token write" ]
    export CICD_READ_TOKEN=""
    run_lib '_vendor_auth_header'
    [ "$output" = "Authorization: token write" ]
}

@test "auth header: VENDOR_PAT when both new names are unset or empty" {
    export CICD_READ_TOKEN="" CICD_WRITE_TOKEN="" VENDOR_PAT=pat GH_TOKEN=tok
    run_lib '_vendor_auth_header'
    [ "$output" = "Authorization: token pat" ]
}

@test "download: CICD_READ_TOKEN alone selects the gh path" {
    export CICD_READ_TOKEN=read
    run_lib '_vendor_download src/a.txt a.txt'
    [ "$status" -eq 0 ]
    [ "$(stub_calls gh)" -eq 1 ]
    [ "$(stub_calls curl)" -eq 0 ]
}

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

# ── checkout mode (VENDOR_CHECKOUT) ─────────────────────────────────────

# make_checkout: a vendor checkout at $CO with a nested tree, an executable
# source file, a binary file, a symlink, a .git dir and a submodule stand-in.
make_checkout() {
    CO="$BATS_TEST_TMPDIR/checkout"
    mkdir -p "$CO/tpl/hooks/sub/deeper" "$CO/.git" "$CO/tpl/hooks/.git" \
        "$CO/tpl/hooks/module" "$CO/tpl/hooks/inited/.git"
    printf 'line one\nline two\n' > "$CO/tpl/hooks/a.sh"
    chmod +x "$CO/tpl/hooks/a.sh"
    printf '\x00\x01\xff\xfe binary\n\x00' > "$CO/tpl/hooks/sub/blob.bin"
    echo c > "$CO/tpl/hooks/sub/deeper/c.sh"
    echo z > "$CO/tpl/hooks/z.sh"
    echo hidden > "$CO/tpl/hooks/.hidden"
    echo in-submodule > "$CO/tpl/hooks/inited/x"
    echo git > "$CO/tpl/hooks/.git/HEAD"
    ln -s a.sh "$CO/tpl/hooks/link"
    echo top > "$CO/prl.py"
    chmod +x "$CO/prl.py"
    export VENDOR_CHECKOUT="$CO"
}

@test "checkout: fetch_file copies bytes exactly, no gh or curl even with a token" {
    make_checkout
    export GH_TOKEN=tok CICD_READ_TOKEN=read VENDOR_MANIFEST="$BATS_TEST_TMPDIR/m.files"
    run_lib 'fetch_file tpl/hooks/sub/blob.bin out/blob.bin; fetch_file tpl/hooks/a.sh out/a.sh'
    [ "$status" -eq 0 ]
    cmp "$CO/tpl/hooks/sub/blob.bin" out/blob.bin
    cmp "$CO/tpl/hooks/a.sh" out/a.sh
    [ "$(stub_calls gh)" -eq 0 ]
    [ "$(stub_calls curl)" -eq 0 ]
    [ "$(cat "$VENDOR_MANIFEST")" = "out/blob.bin
out/a.sh" ]
}

@test "checkout: without +x the umask mode is kept even if the source is executable" {
    make_checkout
    run_lib 'umask 022; fetch_file prl.py out/prl.py; fetch_file prl.py out/prl-x +x'
    [ "$status" -eq 0 ]
    [ ! -x out/prl.py ]
    [ "$(stat -c %a out/prl.py)" = "644" ]
    [ -x out/prl-x ]
}

@test "checkout: VENDOR_REPO and VENDOR_REF are not needed" {
    make_checkout
    unset VENDOR_REPO VENDOR_REF
    run_lib 'fetch_file prl.py prl.py && fetch_dir tpl/hooks/sub out'
    [ "$status" -eq 0 ]
    [ -f prl.py ] && [ -f out/deeper/c.sh ]
}

@test "checkout: a missing source returns nonzero, names the path, writes nothing" {
    make_checkout
    export VENDOR_MANIFEST="$BATS_TEST_TMPDIR/m.files"
    run_lib 'fetch_file nope.txt out/nope.txt || echo "rc=$?"'
    [[ "$output" == *"Error: nope.txt not found in the vendor checkout"* ]]
    [[ "$output" == *"rc=1"* ]]
    [ ! -e out/nope.txt ]
    [ ! -e "$VENDOR_MANIFEST" ]
    run_lib 'fetch_file tpl/hooks/link link || echo "rc=$?"'
    [[ "$output" == *"rc=1"* ]]
    [ "$(stub_calls curl)" -eq 0 ]
}

@test "checkout: fetch_dir copies the tree, skipping .git, symlinks and submodules" {
    make_checkout
    export VENDOR_MANIFEST="$BATS_TEST_TMPDIR/m.files"
    run_lib 'fetch_dir tpl/hooks out'
    [ "$status" -eq 0 ]
    cmp "$CO/tpl/hooks/a.sh" out/a.sh
    cmp "$CO/tpl/hooks/sub/blob.bin" out/sub/blob.bin
    [ "$(cat out/sub/deeper/c.sh)" = "c" ]
    [ "$(cat out/.hidden)" = "hidden" ]
    [ ! -e out/.git ] && [ ! -e out/link ] && [ ! -e out/module ] && [ ! -e out/inited ]
    [ ! -x out/a.sh ]
    [ "$(stub_calls gh)" -eq 0 ]
    [ "$(stub_calls curl)" -eq 0 ]
    [ "$(cat "$VENDOR_MANIFEST")" = "out/.hidden
out/a.sh
out/sub/blob.bin
out/sub/deeper/c.sh
out/z.sh" ]
}

@test "checkout: fetch_dir manifest lines match the API mode for the same tree" {
    make_checkout
    export VENDOR_MANIFEST="$BATS_TEST_TMPDIR/checkout.files"
    run_lib 'fetch_dir tpl/hooks out-co/'
    [ "$status" -eq 0 ]
    unset VENDOR_CHECKOUT
    listing tpl/hooks \
        $'file\ttpl/hooks/.hidden\t.hidden' $'file\ttpl/hooks/a.sh\ta.sh' \
        $'symlink\ttpl/hooks/link\tlink' $'submodule\ttpl/hooks/module\tmodule' \
        $'dir\ttpl/hooks/sub\tsub' $'file\ttpl/hooks/z.sh\tz.sh'
    listing tpl/hooks/sub $'file\ttpl/hooks/sub/blob.bin\tblob.bin' \
        $'dir\ttpl/hooks/sub/deeper\tdeeper'
    listing tpl/hooks/sub/deeper $'file\ttpl/hooks/sub/deeper/c.sh\tc.sh'
    export VENDOR_MANIFEST="$BATS_TEST_TMPDIR/api.files"
    run_lib 'fetch_dir tpl/hooks out-co/'
    [ "$status" -eq 0 ]
    [ "$(sort "$BATS_TEST_TMPDIR/checkout.files")" = "$(sort "$BATS_TEST_TMPDIR/api.files")" ]
}

@test "checkout: fetch_dir of a missing dir returns 1 with the listing error" {
    make_checkout
    run_lib 'fetch_dir nope out || echo "rc=$?"'
    [[ "$output" == *"Error: failed to list directory nope from o/r"* ]]
    [[ "$output" == *"rc=1"* ]]
    [ ! -e out ]
    run_lib 'fetch_dir prl.py out || echo "rc=$?"'
    [[ "$output" == *"rc=1"* ]]
    [ "$(stub_calls gh)" -eq 0 ]
}

@test "checkout: a failing file inside fetch_dir stops it with nonzero" {
    make_checkout
    chmod 000 "$CO/tpl/hooks/sub/deeper/c.sh"
    if cat "$CO/tpl/hooks/sub/deeper/c.sh" >/dev/null 2>&1; then
        skip "running as a user that reads mode-000 files"
    fi
    run_lib 'fetch_dir tpl/hooks out; echo after'
    [ "$status" -ne 0 ]
    [[ "$output" != *after* ]]
}

@test "checkout: no gh on PATH is fine" {
    make_checkout
    use_no_gh
    run_lib 'fetch_dir tpl/hooks/sub out && fetch_file prl.py prl.py +x'
    [ "$status" -eq 0 ]
    [ -f out/blob.bin ] && [ -x prl.py ]
}

@test "fallback: VENDOR_CHECKOUT empty uses the download path" {
    export VENDOR_CHECKOUT=""
    run_lib 'fetch_file prl.py prl.py'
    [ "$status" -eq 0 ]
    [ "$(cat prl.py)" = "curl:$RAW/o/r/v1.0.0/prl.py" ]
}

@test "fallback: VENDOR_CHECKOUT naming no directory uses the download path" {
    export VENDOR_CHECKOUT="$BATS_TEST_TMPDIR/does-not-exist"
    run_lib 'fetch_file prl.py prl.py'
    [ "$status" -eq 0 ]
    [ "$(cat prl.py)" = "curl:$RAW/o/r/v1.0.0/prl.py" ]
}

# ── the same vendor through both modes lands byte- and mode-identical ───

# A vendor whose install.sh uses the helpers the way git-cicd's and
# git-semver's do: nested dirs, a +x file, a workflow outside
# VENDOR_INSTALL_DIR. It is a local git repo, checked out with git.
VENDOR_SH='source "$VENDOR_LIB"
fetch_file tool "$VENDOR_INSTALL_DIR/tool" +x
fetch_file README.md "$VENDOR_INSTALL_DIR/README.md"
fetch_dir templates "$VENDOR_INSTALL_DIR/templates"
fetch_file workflows/tool.yml .github/workflows/tool.yml'

make_git_vendor() {
    local src="$BATS_TEST_TMPDIR/vendor-src"
    mkdir -p "$src/templates/hooks/deep" "$src/workflows"
    printf '#!/bin/bash\necho tool\n' > "$src/tool"
    chmod +x "$src/tool"
    printf '# readme\n' > "$src/README.md"
    printf 'hook\n' > "$src/templates/hooks/pre.sh"
    chmod +x "$src/templates/hooks/pre.sh"   # exec bit in git, never set by a download
    printf '\x00\x01binary\xff' > "$src/templates/hooks/deep/data.bin"
    printf 'a: 1\n' > "$src/templates/config.yml"
    printf 'on: push\n' > "$src/workflows/tool.yml"
    printf '%s\n' "$VENDOR_SH" > "$src/install.sh"
    local g=(git -c user.name=t -c user.email=t@t -c commit.gpgsign=false -C "$src")
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 "${g[@]}" init -q -b main
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 "${g[@]}" add -A
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 "${g[@]}" commit -q -m v1
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 "${g[@]}" tag v1.0.0
    CO="$BATS_TEST_TMPDIR/vendor-checkout"
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_ALLOW_PROTOCOL=file \
        git clone -q --depth 1 --branch v1.0.0 -c advice.detachedHead=false \
        "file://$src" "$CO"
}

# serve_tree_with_gh <dir>: make the gh stub serve <dir> (contents and
# directory listings), as GitHub would for the same tree.
serve_tree_with_gh() {
    local root="$1" d rel e name
    cp -R "$root/." "$GH_CONTENT/"
    rm -rf "$GH_CONTENT/.git"
    while IFS= read -r d; do
        rel="${d#$root}"; rel="${rel#/}"
        [ -z "$rel" ] && continue
        mkdir -p "$(dirname "$GH_LISTINGS/$rel")"
        : > "$GH_LISTINGS/$rel.tsv"
        for e in "$d"/*; do
            name="${e##*/}"
            if [ -d "$e" ]; then
                printf 'dir\t%s\t%s\n' "$rel/$name" "$name" >> "$GH_LISTINGS/$rel.tsv"
            else
                printf 'file\t%s\t%s\n' "$rel/$name" "$name" >> "$GH_LISTINGS/$rel.tsv"
            fi
        done
    done < <(find "$root" -type d -not -path '*/.git*')
}

install_into() {
    # install_into <dir> [VAR=value...]: run the vendor install.sh there
    local dir="$1"; shift
    mkdir -p "$dir"
    (cd "$dir" && env PATH="$RUN_PATH" VENDOR_LIB="$LIB" \
        VENDOR_INSTALL_DIR=.vendored/pkg/tool VENDOR_MANIFEST="$dir.files" "$@" \
        bash -c 'umask 022; source "$1"' _ "$CO/install.sh")
}

tree_state() {
    # Every file with its mode and checksum, relative to $1
    (cd "$1" && find . -type f -printf '%m %p\n' | sort && find . -type f -print0 | sort -z | xargs -0 cksum)
}

@test "both modes: same files, bytes, modes and manifest for a vendor using the helpers" {
    make_git_vendor
    serve_tree_with_gh "$CO"
    install_into "$BATS_TEST_TMPDIR/via-checkout" VENDOR_CHECKOUT="$CO"
    [ "$(stub_calls gh)" -eq 0 ]
    [ "$(stub_calls curl)" -eq 0 ]
    install_into "$BATS_TEST_TMPDIR/via-api" GH_TOKEN=tok
    [ "$(stub_calls gh)" -gt 0 ]
    a="$(tree_state "$BATS_TEST_TMPDIR/via-checkout")"
    b="$(tree_state "$BATS_TEST_TMPDIR/via-api")"
    [ "$a" = "$b" ]
    [[ "$a" == *"755 ./.vendored/pkg/tool/tool"* ]]
    [[ "$a" == *"644 ./.vendored/pkg/tool/templates/hooks/pre.sh"* ]]
    [[ "$a" == *"644 ./.github/workflows/tool.yml"* ]]
    [ "$(sort "$BATS_TEST_TMPDIR/via-checkout.files")" = "$(sort "$BATS_TEST_TMPDIR/via-api.files")" ]
    [ ! -e "$BATS_TEST_TMPDIR/via-checkout/.vendored/pkg/tool/.git" ]
}
