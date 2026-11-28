#!/usr/bin/env bats
# Tests for the real install.sh (repo root), with curl and gh stubbed.

load stubs

RAW="https://raw.githubusercontent.com"
DEFAULT_REPO="mangimangi/git-vendored"
REQUIRED=(install check remove feedback audit lib/vendor-helpers.sh)
UNSORTED_MANIFEST=".vendored/install
.vendored/check
.vendored/remove
.vendored/feedback
.vendored/audit
.vendored/lib/vendor-helpers.sh
.github/workflows/install-vendored.yml
.github/workflows/check-vendor.yml"
SORTED_MANIFEST=".github/workflows/check-vendor.yml
.github/workflows/install-vendored.yml
.vendored/audit
.vendored/check
.vendored/feedback
.vendored/install
.vendored/lib/vendor-helpers.sh
.vendored/remove"

setup() {
    stubs_setup
    PROJ="$BATS_TEST_TMPDIR/proj"
    mkdir -p "$PROJ"
    cd "$PROJ"
}

run_install() {
    run env PATH="$RUN_PATH" bash "$REPO_ROOT/install.sh" "$@"
}

# ── version / ref ───────────────────────────────────────────────────────

@test "no VENDOR_REF and no \$1: usage error, nonzero exit, nothing created" {
    run_install
    [ "$status" -ne 0 ]
    [[ "$output" == *"Usage: install.sh <version> [<repo>]"* ]]
    [ ! -e .vendored ]
    [ "$(stub_calls curl)" -eq 0 ]
}

@test "empty VENDOR_REF and no \$1: usage error" {
    export VENDOR_REF=""
    run_install
    [ "$status" -ne 0 ]
    [[ "$output" == *"Usage: install.sh <version> [<repo>]"* ]]
}

@test "\$1 gives the version; ref is v<version>" {
    run_install 1.2.3
    [ "$status" -eq 0 ]
    [[ "$output" == *"Installing git-vendored v1.2.3 from $DEFAULT_REPO"* ]]
    assert_logged "curl [-fsSL] [$RAW/$DEFAULT_REPO/v1.2.3/templates/install] [-o] [.vendored/install]"
    [ "$(cat .vendored/manifests/git-vendored.version)" = "1.2.3" ]
}

@test "\$1 with v prefix is stripped" {
    run_install v1.2.3
    [ "$status" -eq 0 ]
    [[ "$output" == *"Installing git-vendored v1.2.3 from"* ]]
    [[ "$output" != *"vv1.2.3"* ]]
    assert_logged "curl [-fsSL] [$RAW/$DEFAULT_REPO/v1.2.3/templates/install] [-o] [.vendored/install]"
    [ "$(cat .vendored/manifests/git-vendored.version)" = "1.2.3" ]
}

@test "VENDOR_REF overrides \$1 and its v prefix is stripped" {
    export VENDOR_REF=v2.0.0
    run_install 1.2.3
    [ "$status" -eq 0 ]
    [[ "$output" == *"Installing git-vendored v2.0.0 from"* ]]
    assert_logged "curl [-fsSL] [$RAW/$DEFAULT_REPO/v2.0.0/templates/install] [-o] [.vendored/install]"
    refute_logged_match "v1.2.3"
    [ "$(cat .vendored/manifests/git-vendored.version)" = "2.0.0" ]
    [[ "$output" == *"Done! git-vendored v2.0.0 installed."* ]]
}

@test "VENDOR_REF without v prefix works with no \$1" {
    export VENDOR_REF=3.1.0
    run_install
    [ "$status" -eq 0 ]
    assert_logged "curl [-fsSL] [$RAW/$DEFAULT_REPO/v3.1.0/templates/check] [-o] [.vendored/check]"
    [ "$(cat .vendored/manifests/git-vendored.version)" = "3.1.0" ]
}

@test "empty VENDOR_REF falls back to \$1" {
    export VENDOR_REF=""
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [[ "$output" == *"Installing git-vendored v1.0.0"* ]]
}

# ── repo ────────────────────────────────────────────────────────────────

@test "default repo is mangimangi/git-vendored" {
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [[ "$output" == *"from mangimangi/git-vendored"* ]]
    assert_logged "curl [-fsSL] [$RAW/mangimangi/git-vendored/v1.0.0/templates/remove] [-o] [.vendored/remove]"
}

@test "\$2 sets the repo" {
    run_install 1.0.0 alt/fork
    [ "$status" -eq 0 ]
    [[ "$output" == *"Installing git-vendored v1.0.0 from alt/fork"* ]]
    assert_logged "curl [-fsSL] [$RAW/alt/fork/v1.0.0/templates/install] [-o] [.vendored/install]"
    refute_logged_match "mangimangi"
}

@test "VENDOR_REPO overrides \$2" {
    export VENDOR_REPO=env/repo
    run_install 1.0.0 alt/fork
    [ "$status" -eq 0 ]
    [[ "$output" == *"from env/repo"* ]]
    assert_logged "curl [-fsSL] [$RAW/env/repo/v1.0.0/templates/install] [-o] [.vendored/install]"
    refute_logged_match "alt/fork"
}

@test "VENDOR_REPO overrides the default" {
    export VENDOR_REPO=env/repo
    run_install 1.0.0
    [ "$status" -eq 0 ]
    assert_logged "curl [-fsSL] [$RAW/env/repo/v1.0.0/templates/audit] [-o] [.vendored/audit]"
}

@test "empty VENDOR_REPO falls back to \$2" {
    export VENDOR_REPO=""
    run_install 1.0.0 alt/fork
    [ "$status" -eq 0 ]
    [[ "$output" == *"from alt/fork"* ]]
}

# ── download path selection ─────────────────────────────────────────────

@test "curl path (no GH_TOKEN, gh on PATH): every file fetched with curl from raw URLs, gh unused" {
    run_install 1.2.3 o/r
    [ "$status" -eq 0 ]
    [ "$(stub_calls gh)" -eq 0 ]
    for f in "${REQUIRED[@]}"; do
        assert_logged "curl [-fsSL] [$RAW/o/r/v1.2.3/templates/$f] [-o] [.vendored/$f]"
        [ "$(cat ".vendored/$f")" = "curl:$RAW/o/r/v1.2.3/templates/$f" ]
    done
    assert_logged "curl [-fsSL] [$RAW/o/r/v1.2.3/templates/config.json] [-o] [.vendored/config.json]"
    for w in install-vendored.yml check-vendor.yml; do
        assert_logged "curl [-fsSL] [$RAW/o/r/v1.2.3/templates/github/workflows/$w] [-o] [.github/workflows/$w]"
    done
    [ "$(stub_calls curl)" -eq 9 ]
}

@test "empty GH_TOKEN takes the curl path" {
    export GH_TOKEN=""
    run_install 1.2.3 o/r
    [ "$status" -eq 0 ]
    [ "$(stub_calls gh)" -eq 0 ]
    [ "$(stub_calls curl)" -eq 9 ]
}

@test "GH_TOKEN set but gh not on PATH takes the curl path" {
    export GH_TOKEN=tok
    use_no_gh
    run_install 1.2.3 o/r
    [ "$status" -eq 0 ]
    [ "$(stub_calls curl)" -eq 9 ]
    [ "$(stub_calls gh)" -eq 0 ]
    [ "$(cat .vendored/install)" = "curl:$RAW/o/r/v1.2.3/templates/install" ]
    # curl in install.sh never sends an auth header
    refute_logged_match "[-H]"
}

@test "gh path (GH_TOKEN set, gh on PATH): gh api contents with ref, base64-decoded, curl unused" {
    export GH_TOKEN=tok
    run_install 1.2.3 o/r
    [ "$status" -eq 0 ]
    [ "$(stub_calls curl)" -eq 0 ]
    for f in "${REQUIRED[@]}"; do
        assert_logged "gh [api] [repos/o/r/contents/templates/$f?ref=v1.2.3] [--jq] [.content]"
        [ "$(cat ".vendored/$f")" = "gh:templates/$f@v1.2.3" ]
    done
    assert_logged "gh [api] [repos/o/r/contents/templates/config.json?ref=v1.2.3] [--jq] [.content]"
    for w in install-vendored.yml check-vendor.yml; do
        assert_logged "gh [api] [repos/o/r/contents/templates/github/workflows/$w?ref=v1.2.3] [--jq] [.content]"
        [ "$(cat ".github/workflows/$w")" = "gh:templates/github/workflows/$w@v1.2.3" ]
    done
    [ "$(stub_calls gh)" -eq 9 ]
}

@test "gh path decodes multi-line base64 content byte for byte" {
    export GH_TOKEN=tok
    mkdir -p "$GH_CONTENT/templates"
    for i in $(seq 1 40); do echo "line $i of a long file that wraps base64 output"; done \
        > "$GH_CONTENT/templates/install"
    run_install 1.2.3 o/r
    [ "$status" -eq 0 ]
    cmp "$GH_CONTENT/templates/install" .vendored/install
}

# ── files written ───────────────────────────────────────────────────────

@test "creates the directory layout" {
    run_install 1.0.0
    [ "$status" -eq 0 ]
    for d in .vendored .vendored/manifests .vendored/configs .vendored/pkg .vendored/lib .github/workflows; do
        [ -d "$d" ]
    done
}

@test "each required file is downloaded, made executable, and announced" {
    run_install 1.0.0
    [ "$status" -eq 0 ]
    for f in "${REQUIRED[@]}"; do
        [ -f ".vendored/$f" ]
        is_executable ".vendored/$f"
        [[ "$output" == *"Downloading .vendored/$f..."* ]]
    done
}

@test "re-installing makes previously non-executable files executable again" {
    mkdir -p .vendored/lib
    for f in "${REQUIRED[@]}"; do echo old > ".vendored/$f"; chmod 644 ".vendored/$f"; done
    run_install 1.0.0
    [ "$status" -eq 0 ]
    for f in "${REQUIRED[@]}"; do
        is_executable ".vendored/$f"
        [ "$(cat ".vendored/$f")" != old ]
    done
}

@test "removes legacy .vendored/add, .vendored/update and .vendored/.version" {
    mkdir -p .vendored
    echo x > .vendored/add
    echo x > .vendored/update
    echo 0.1 > .vendored/.version
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [ ! -e .vendored/add ]
    [ ! -e .vendored/update ]
    [ ! -e .vendored/.version ]
}

@test "absent legacy files are not an error" {
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [ ! -e .vendored/add ]
    [ ! -e .vendored/update ]
    [ ! -e .vendored/.version ]
}

@test "config.json is created when missing, not executable, not in the manifest" {
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [[ "$output" == *"Created .vendored/config.json"* ]]
    [ "$(cat .vendored/config.json)" = "curl:$RAW/$DEFAULT_REPO/v1.0.0/templates/config.json" ]
    [ ! -x .vendored/config.json ]
    ! grep -q config.json .vendored/manifests/git-vendored.files
}

@test "existing config.json is preserved and not fetched" {
    mkdir -p .vendored
    echo '{"mine": true}' > .vendored/config.json
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [ "$(cat .vendored/config.json)" = '{"mine": true}' ]
    [[ "$output" != *"Created .vendored/config.json"* ]]
    refute_logged_match "templates/config.json"
    [ "$(stub_calls curl)" -eq 8 ]
}

@test "config.json download failure exits nonzero (set -e)" {
    export CURL_FAIL="*templates/config.json"
    run_install 1.0.0
    [ "$status" -ne 0 ]
    [[ "$output" != *"Done!"* ]]
    [ ! -e .vendored/manifests/git-vendored.files ]
}

# ── workflows ───────────────────────────────────────────────────────────

@test "workflows are installed when the fetch succeeds" {
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [[ "$output" == *"Installed .github/workflows/install-vendored.yml"* ]]
    [[ "$output" == *"Installed .github/workflows/check-vendor.yml"* ]]
    [ -f .github/workflows/install-vendored.yml ]
    [ -f .github/workflows/check-vendor.yml ]
    grep -qx .github/workflows/install-vendored.yml .vendored/manifests/git-vendored.files
    grep -qx .github/workflows/check-vendor.yml .vendored/manifests/git-vendored.files
}

@test "existing workflows are skipped, preserved, not fetched, and still in the manifest" {
    mkdir -p .github/workflows
    echo mine1 > .github/workflows/install-vendored.yml
    echo mine2 > .github/workflows/check-vendor.yml
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [[ "$output" == *"Workflow .github/workflows/install-vendored.yml already exists, skipping"* ]]
    [[ "$output" == *"Workflow .github/workflows/check-vendor.yml already exists, skipping"* ]]
    [[ "$output" != *"Installed .github/workflows/"* ]]
    [ "$(cat .github/workflows/install-vendored.yml)" = mine1 ]
    [ "$(cat .github/workflows/check-vendor.yml)" = mine2 ]
    refute_logged_match "templates/github/workflows"
    [ "$(cat .vendored/manifests/git-vendored.files)" = "$SORTED_MANIFEST" ]
}

@test "one workflow present, one installed" {
    mkdir -p .github/workflows
    echo mine > .github/workflows/check-vendor.yml
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [[ "$output" == *"Installed .github/workflows/install-vendored.yml"* ]]
    [[ "$output" == *"Workflow .github/workflows/check-vendor.yml already exists, skipping"* ]]
    [ "$(cat .vendored/manifests/git-vendored.files)" = "$SORTED_MANIFEST" ]
}

@test "curl path: failed workflow fetch is silent, not fatal, and omitted from the manifest" {
    export CURL_FAIL="*/check-vendor.yml"
    export VENDOR_MANIFEST="$BATS_TEST_TMPDIR/out.files"
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [[ "$output" != *"check-vendor.yml"* ]]
    [[ "$output" != *"curl: (22)"* ]]
    [[ "$output" == *"Installed .github/workflows/install-vendored.yml"* ]]
    [ ! -e .github/workflows/check-vendor.yml ]
    ! grep -q check-vendor.yml .vendored/manifests/git-vendored.files
    ! grep -q check-vendor.yml "$VENDOR_MANIFEST"
    grep -qx .github/workflows/install-vendored.yml "$VENDOR_MANIFEST"
    [[ "$output" == *"Done! git-vendored v1.0.0 installed."* ]]
}

@test "gh path: failed workflow fetch is silent, omitted from the manifest, and leaves no empty file" {
    export GH_TOKEN=tok
    export GH_FAIL="*workflows/*"
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [[ "$output" != *"Bad credentials"* ]]
    [[ "$output" != *"Installed .github/workflows/"* ]]
    [ ! -e .github/workflows/install-vendored.yml ]
    [ ! -e .github/workflows/check-vendor.yml ]
    ! grep -q workflows .vendored/manifests/git-vendored.files
    [[ "$output" == *"Done!"* ]]
}

@test "gh path: a workflow whose bootstrap fetch failed is not added by the next install (an upgrade)" {
    export GH_TOKEN=tok
    export GH_FAIL="*check-vendor.yml*"
    run_install 1.0.0
    [ "$status" -eq 0 ]
    unset GH_FAIL
    run_install 1.0.1
    [ "$status" -eq 0 ]
    [[ "$output" == *"Not installing .github/workflows/check-vendor.yml: this is an upgrade"* ]]
    [ ! -e .github/workflows/check-vendor.yml ]
    ! grep -q check-vendor.yml .vendored/manifests/git-vendored.files
}

# ── bootstrap, upgrade, git-cicd ────────────────────────────────────────

@test "bootstrap (no earlier install): both workflows installed and listed" {
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [ -f .github/workflows/install-vendored.yml ]
    [ -f .github/workflows/check-vendor.yml ]
    [ "$(cat .vendored/manifests/git-vendored.files)" = "$SORTED_MANIFEST" ]
    [[ "$output" != *"Not installing"* ]]
}

@test "upgrade without the workflows: neither is fetched, written or listed" {
    run_install 1.0.0
    [ "$status" -eq 0 ]
    rm .github/workflows/install-vendored.yml .github/workflows/check-vendor.yml
    : > "$STUB_LOG"
    export VENDOR_MANIFEST="$BATS_TEST_TMPDIR/out.files"
    run_install 1.1.0
    [ "$status" -eq 0 ]
    [[ "$output" == *"Not installing .github/workflows/install-vendored.yml: this is an upgrade (.vendored/manifests/git-vendored.version exists) and the repository has no such workflow"* ]]
    [[ "$output" == *"Not installing .github/workflows/check-vendor.yml: this is an upgrade"* ]]
    [[ "$output" != *"Installed .github/workflows/"* ]]
    refute_logged_match "templates/github/workflows"
    [ ! -e .github/workflows/install-vendored.yml ]
    [ ! -e .github/workflows/check-vendor.yml ]
    ! grep -q workflows .vendored/manifests/git-vendored.files
    ! grep -q workflows "$VENDOR_MANIFEST"
    [ "$(cat .vendored/manifests/git-vendored.version)" = "1.1.0" ]
    [[ "$output" == *"Done! git-vendored v1.1.0 installed."* ]]
}

@test "upgrade keeps a workflow that is present and does not add the missing one" {
    run_install 1.0.0
    [ "$status" -eq 0 ]
    rm .github/workflows/check-vendor.yml
    echo mine > .github/workflows/install-vendored.yml
    run_install 1.1.0
    [ "$status" -eq 0 ]
    [ "$(cat .github/workflows/install-vendored.yml)" = mine ]
    [ ! -e .github/workflows/check-vendor.yml ]
    grep -qx .github/workflows/install-vendored.yml .vendored/manifests/git-vendored.files
    ! grep -q check-vendor.yml .vendored/manifests/git-vendored.files
}

@test "each earlier-install marker makes the run an upgrade" {
    for marker in .vendored/manifests/git-vendored.version \
            .vendored/manifests/git-vendored.files .vendored/.version .vendored/install; do
        rm -rf .vendored .github
        : > "$STUB_LOG"
        mkdir -p "$(dirname "$marker")"
        echo old > "$marker"
        run_install 1.0.0
        [ "$status" -eq 0 ]
        [[ "$output" == *"this is an upgrade ($marker exists)"* ]]
        refute_logged_match "templates/github/workflows"
        [ ! -e .github/workflows/check-vendor.yml ]
        [ ! -e .github/workflows/install-vendored.yml ]
    done
}

write_git_cicd_config() {
    mkdir -p .vendored/configs ci
    cat > ci/vendor-check.sh <<'SH'
#!/bin/bash
exec python3 .vendored/check --base "$CICD_BASE"
SH
    cat > .vendored/configs/git-cicd.json <<'JSON'
{"jobs": {
  "test": {"on": ["open"], "steps": ["ci/test.sh"]},
  "vendor-check": {"on": ["open"], "steps": ["ci/vendor-check.sh"]},
  "update-vendored": {"on": ["cron"], "steps": [["python3", ".vendored/install", "all", "--pr"]]}
}}
JSON
}

@test "bootstrap on git-cicd: jobs that run .vendored/check and .vendored/install replace both workflows" {
    write_git_cicd_config
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [[ "$output" == *"Not installing .github/workflows/install-vendored.yml: git-cicd job 'update-vendored' in .vendored/configs/git-cicd.json already runs .vendored/install"* ]]
    [[ "$output" == *"Not installing .github/workflows/check-vendor.yml: git-cicd job 'vendor-check' in .vendored/configs/git-cicd.json already runs .vendored/check"* ]]
    refute_logged_match "templates/github/workflows"
    [ ! -e .github/workflows/install-vendored.yml ]
    [ ! -e .github/workflows/check-vendor.yml ]
    ! grep -q workflows .vendored/manifests/git-vendored.files
}

@test "bootstrap on git-cicd: a step string naming the command counts; a job that runs neither does not" {
    mkdir -p .vendored/configs
    cat > .vendored/configs/git-cicd.json <<'JSON'
{"jobs": {
  "vendor-check": {"steps": ["python3 ./.vendored/check --base origin/main"]},
  "other": {"steps": ["ci/missing.sh", ".vendored/installer"]}
}}
JSON
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [[ "$output" == *"Not installing .github/workflows/check-vendor.yml: git-cicd job 'vendor-check'"* ]]
    [[ "$output" == *"Installed .github/workflows/install-vendored.yml"* ]]
    [ ! -e .github/workflows/check-vendor.yml ]
    grep -qx .github/workflows/install-vendored.yml .vendored/manifests/git-vendored.files
}

@test "bootstrap with an unreadable git-cicd config installs both workflows" {
    mkdir -p .vendored/configs
    echo 'not json' > .vendored/configs/git-cicd.json
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [ -f .github/workflows/install-vendored.yml ]
    [ -f .github/workflows/check-vendor.yml ]
}

# ── required download failures ──────────────────────────────────────────

@test "curl path: a required file download failure exits nonzero and stops" {
    export CURL_FAIL="*templates/check"
    run_install 1.0.0
    [ "$status" -ne 0 ]
    [[ "$output" == *"Downloading .vendored/check..."* ]]
    [[ "$output" != *"Downloading .vendored/remove..."* ]]
    [[ "$output" != *"Done!"* ]]
    [ -f .vendored/install ]
    [ ! -e .vendored/remove ]
    [ ! -e .vendored/manifests/git-vendored.files ]
    [ ! -e .vendored/manifests/git-vendored.version ]
}

@test "gh path: a required file download failure exits nonzero (pipefail)" {
    export GH_TOKEN=tok
    export GH_FAIL="*templates/lib/vendor-helpers.sh*"
    run_install 1.0.0
    [ "$status" -ne 0 ]
    [[ "$output" == *"Bad credentials"* ]]
    [[ "$output" != *"Done!"* ]]
    [ ! -e .vendored/manifests/git-vendored.files ]
    refute_logged_match "templates/config.json"
}

@test "each required file's download failure is fatal" {
    for f in "${REQUIRED[@]}"; do
        rm -rf .vendored .github
        : > "$STUB_LOG"
        export CURL_FAIL="*/templates/$f"
        run_install 1.0.0
        [ "$status" -ne 0 ]
        [[ "$output" != *"Done!"* ]]
    done
}

# ── manifests ───────────────────────────────────────────────────────────

@test "VENDOR_MANIFEST set: written in install order (unsorted)" {
    export VENDOR_MANIFEST="$BATS_TEST_TMPDIR/out/vendor.files"
    mkdir -p "$BATS_TEST_TMPDIR/out"
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [ "$(cat "$VENDOR_MANIFEST")" = "$UNSORTED_MANIFEST" ]
}

@test "VENDOR_MANIFEST is overwritten, not appended" {
    export VENDOR_MANIFEST="$BATS_TEST_TMPDIR/vendor.files"
    echo stale > "$VENDOR_MANIFEST"
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [ "$(cat "$VENDOR_MANIFEST")" = "$UNSORTED_MANIFEST" ]
}

@test "VENDOR_MANIFEST unset or empty: no extra manifest written" {
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [ "$(ls -A .vendored/manifests)" = "git-vendored.files
git-vendored.version" ]
    [ "$(ls -A "$BATS_TEST_TMPDIR" | sort | tr '\n' ' ')" = "cache gh-content gh-listings home proj stub.log stubs " ]

    rm -rf .vendored .github
    export VENDOR_MANIFEST=""
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [ "$(ls -A "$BATS_TEST_TMPDIR" | sort | tr '\n' ' ')" = "cache gh-content gh-listings home proj stub.log stubs " ]
}

@test ".vendored/manifests/git-vendored.files is sorted; .version holds the bare version" {
    run_install v4.5.6
    [ "$status" -eq 0 ]
    [ "$(cat .vendored/manifests/git-vendored.files)" = "$SORTED_MANIFEST" ]
    [ "$(cat .vendored/manifests/git-vendored.version)" = "4.5.6" ]
}

@test "existing manifest files are overwritten (an upgrade: no workflows added)" {
    mkdir -p .vendored/manifests
    echo stale > .vendored/manifests/git-vendored.files
    echo 0.0.1 > .vendored/manifests/git-vendored.version
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [ "$(cat .vendored/manifests/git-vendored.files)" = "$(grep -v workflows <<<"$SORTED_MANIFEST")" ]
    [ "$(cat .vendored/manifests/git-vendored.version)" = "1.0.0" ]
}

@test "output ends with a blank line and the Done message" {
    run_install 1.0.0
    [ "$status" -eq 0 ]
    [ "${lines[${#lines[@]}-1]}" = "Done! git-vendored v1.0.0 installed." ]
    [[ "$output" == *$'\n\nDone! git-vendored v1.0.0 installed.' ]]
    [ "${lines[0]}" = "Installing git-vendored v1.0.0 from $DEFAULT_REPO" ]
}

@test "stubs_setup removes token variables the outer environment holds" {
    export CICD_WRITE_TOKEN=outer-fake-write CICD_READ_TOKEN=outer-fake-read
    export VENDOR_PAT=outer-fake-pat GH_TOKEN=outer-fake-gh GITHUB_TOKEN=outer-fake-gt
    stubs_setup
    [ -z "${CICD_WRITE_TOKEN+set}" ]
    [ -z "${CICD_READ_TOKEN+set}" ]
    [ -z "${VENDOR_PAT+set}" ]
    [ -z "${GH_TOKEN+set}" ]
    [ -z "${GITHUB_TOKEN+set}" ]
}

# ── checkout mode (VENDOR_CHECKOUT): bootstrap with git ─────────────────

# A git-vendored checkout: this repository's own templates, which is what
# `git clone --branch v<X.Y.Z>` of git-vendored gives.
make_gv_checkout() {
    CO="$BATS_TEST_TMPDIR/gv-checkout"
    mkdir -p "$CO"
    cp -R "$REPO_ROOT/templates" "$CO/templates"
    cp "$REPO_ROOT/install.sh" "$CO/install.sh"
}

@test "checkout: every file is copied from VENDOR_CHECKOUT, no gh or curl even with GH_TOKEN" {
    make_gv_checkout
    export GH_TOKEN=tok VENDOR_CHECKOUT="$CO"
    run_install 1.2.3 o/r
    [ "$status" -eq 0 ]
    [ "$(stub_calls gh)" -eq 0 ]
    [ "$(stub_calls curl)" -eq 0 ]
    for f in "${REQUIRED[@]}"; do
        cmp "$CO/templates/$f" ".vendored/$f"
        is_executable ".vendored/$f"
    done
    cmp "$CO/templates/config.json" .vendored/config.json
    for w in install-vendored.yml check-vendor.yml; do
        cmp "$CO/templates/github/workflows/$w" ".github/workflows/$w"
    done
}

@test "checkout: works with gh absent from PATH (git bootstrap)" {
    make_gv_checkout
    use_no_gh
    run env PATH="$RUN_PATH" VENDOR_CHECKOUT="$CO" bash "$CO/install.sh" 1.2.3
    [ "$status" -eq 0 ]
    [ "$(stub_calls curl)" -eq 0 ]
    cmp "$CO/templates/install" .vendored/install
}

@test "checkout: config.json gets content only, not the checkout's mode" {
    make_gv_checkout
    chmod +x "$CO/templates/config.json"
    export VENDOR_CHECKOUT="$CO"
    run_install 1.2.3 o/r
    [ "$status" -eq 0 ]
    [ ! -x .vendored/config.json ]
}

@test "checkout: a file missing from the checkout fails the install" {
    make_gv_checkout
    rm "$CO/templates/check"
    export VENDOR_CHECKOUT="$CO"
    run_install 1.2.3 o/r
    [ "$status" -ne 0 ]
    [[ "$output" == *"templates/check not found in the git-vendored checkout"* ]]
    [ "$(stub_calls curl)" -eq 0 ]
}

@test "checkout: a workflow missing from the checkout is skipped, not fatal" {
    make_gv_checkout
    rm "$CO/templates/github/workflows/check-vendor.yml"
    export VENDOR_CHECKOUT="$CO" VENDOR_MANIFEST="$BATS_TEST_TMPDIR/m.files"
    run_install 1.2.3 o/r
    [ "$status" -eq 0 ]
    [ ! -e .github/workflows/check-vendor.yml ]
    [ -f .github/workflows/install-vendored.yml ]
    ! grep -q check-vendor.yml "$VENDOR_MANIFEST"
}

@test "checkout: empty VENDOR_CHECKOUT takes the download path" {
    export VENDOR_CHECKOUT=""
    run_install 1.2.3 o/r
    [ "$status" -eq 0 ]
    [ "$(stub_calls curl)" -eq 9 ]
}
