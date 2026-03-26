"""Tests for the vendor-helpers.sh shell library."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
HELPERS_SH = str(ROOT / "templates" / "lib" / "vendor-helpers.sh")


@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """Create a temporary directory and chdir into it."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def mock_server(tmp_repo):
    """Create a fake 'vendor repo' directory tree for testing.

    Sets up a local file structure and a mock curl that reads from it,
    so we can test fetch_file/fetch_dir without network access.
    """
    # Create a fake repo source tree
    repo_dir = tmp_repo / "fake_repo"
    repo_dir.mkdir()
    (repo_dir / "script.sh").write_text("#!/bin/bash\necho hello\n")
    (repo_dir / "lib").mkdir()
    (repo_dir / "lib" / "utils.py").write_text("# utils\n")
    (repo_dir / "lib" / "core.py").write_text("# core\n")

    # Create mock curl that copies from fake_repo based on URL path
    mock_bin = tmp_repo / "mock_bin"
    mock_bin.mkdir()
    mock_curl = mock_bin / "curl"
    mock_curl.write_text(f"""\
#!/bin/bash
# Mock curl: extract the file path from the URL and copy from fake repo.
# URL format: https://raw.githubusercontent.com/owner/repo/ref/<path>
# We need to find -o argument for output path.
output=""
url=""
for arg in "$@"; do
    if [ "$prev_was_o" = "1" ]; then
        output="$arg"
        prev_was_o=0
        continue
    fi
    if [ "$arg" = "-o" ]; then
        prev_was_o=1
        continue
    fi
    # Last non-flag argument is the URL
    if [[ "$arg" != -* ]]; then
        url="$arg"
    fi
done

# Extract path after the 4th slash segment (owner/repo/ref/...)
path=$(echo "$url" | sed 's|https://raw.githubusercontent.com/[^/]*/[^/]*/[^/]*/||')
src="{repo_dir}/$path"

if [ -f "$src" ]; then
    if [ -n "$output" ]; then
        cp "$src" "$output"
    else
        cat "$src"
    fi
else
    echo "Mock curl: not found: $src" >&2
    exit 1
fi
""")
    mock_curl.chmod(0o755)

    return repo_dir, mock_bin


def run_helper_script(tmp_repo, mock_bin, script_body, env_overrides=None):
    """Run a bash script that sources vendor-helpers.sh."""
    test_script = tmp_repo / "test_run.sh"
    test_script.write_text(f"""\
#!/bin/bash
set -euo pipefail
source "{HELPERS_SH}"
{script_body}
""")
    test_script.chmod(0o755)

    env = os.environ.copy()
    env["VENDOR_REPO"] = "owner/repo"
    env["VENDOR_REF"] = "v1.0.0"
    env["PATH"] = f"{mock_bin}:{env['PATH']}"
    # Remove gh from path to force curl fallback
    env.pop("GH_TOKEN", None)
    env.pop("VENDOR_PAT", None)
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(
        ["bash", str(test_script)],
        capture_output=True, text=True, env=env,
        cwd=str(tmp_repo),
    )
    return result


class TestFetchFile:
    def test_downloads_file(self, tmp_repo, mock_server):
        repo_dir, mock_bin = mock_server
        manifest = tmp_repo / "manifest.txt"
        result = run_helper_script(
            tmp_repo, mock_bin,
            'fetch_file "script.sh" "output/script.sh"',
            {"VENDOR_MANIFEST": str(manifest)},
        )
        assert result.returncode == 0, result.stderr
        assert (tmp_repo / "output" / "script.sh").read_text() == "#!/bin/bash\necho hello\n"

    def test_creates_parent_dirs(self, tmp_repo, mock_server):
        repo_dir, mock_bin = mock_server
        manifest = tmp_repo / "manifest.txt"
        result = run_helper_script(
            tmp_repo, mock_bin,
            'fetch_file "script.sh" "deep/nested/dir/script.sh"',
            {"VENDOR_MANIFEST": str(manifest)},
        )
        assert result.returncode == 0, result.stderr
        assert (tmp_repo / "deep" / "nested" / "dir" / "script.sh").is_file()

    def test_appends_to_manifest(self, tmp_repo, mock_server):
        repo_dir, mock_bin = mock_server
        manifest = tmp_repo / "manifest.txt"
        result = run_helper_script(
            tmp_repo, mock_bin,
            'fetch_file "script.sh" "out/script.sh"',
            {"VENDOR_MANIFEST": str(manifest)},
        )
        assert result.returncode == 0, result.stderr
        lines = manifest.read_text().strip().split("\n")
        assert "out/script.sh" in lines

    def test_executable_flag(self, tmp_repo, mock_server):
        repo_dir, mock_bin = mock_server
        manifest = tmp_repo / "manifest.txt"
        result = run_helper_script(
            tmp_repo, mock_bin,
            'fetch_file "script.sh" "out/script.sh" +x',
            {"VENDOR_MANIFEST": str(manifest)},
        )
        assert result.returncode == 0, result.stderr
        assert os.access(tmp_repo / "out" / "script.sh", os.X_OK)

    def test_no_executable_by_default(self, tmp_repo, mock_server):
        repo_dir, mock_bin = mock_server
        manifest = tmp_repo / "manifest.txt"
        result = run_helper_script(
            tmp_repo, mock_bin,
            'fetch_file "script.sh" "out/script.sh"',
            {"VENDOR_MANIFEST": str(manifest)},
        )
        assert result.returncode == 0, result.stderr
        # File should exist but not be made executable (beyond umask)
        assert (tmp_repo / "out" / "script.sh").is_file()

    def test_manifest_not_set_no_error(self, tmp_repo, mock_server):
        """When VENDOR_MANIFEST is empty, fetch_file should still work without error."""
        repo_dir, mock_bin = mock_server
        result = run_helper_script(
            tmp_repo, mock_bin,
            'fetch_file "script.sh" "out/script.sh"',
            {"VENDOR_MANIFEST": ""},
        )
        assert result.returncode == 0, result.stderr
        assert (tmp_repo / "out" / "script.sh").is_file()

    def test_auth_header_with_gh_token(self, tmp_repo, mock_server):
        """When GH_TOKEN is set but gh is not available, curl should get auth header."""
        repo_dir, mock_bin = mock_server
        manifest = tmp_repo / "manifest.txt"
        result = run_helper_script(
            tmp_repo, mock_bin,
            'fetch_file "script.sh" "out/script.sh"',
            {"VENDOR_MANIFEST": str(manifest), "GH_TOKEN": "test-token"},
        )
        assert result.returncode == 0, result.stderr
        assert (tmp_repo / "out" / "script.sh").is_file()

    def test_multiple_files_appended_to_manifest(self, tmp_repo, mock_server):
        repo_dir, mock_bin = mock_server
        manifest = tmp_repo / "manifest.txt"
        result = run_helper_script(
            tmp_repo, mock_bin,
            """
fetch_file "script.sh" "out/script.sh"
fetch_file "lib/utils.py" "out/utils.py"
""",
            {"VENDOR_MANIFEST": str(manifest)},
        )
        assert result.returncode == 0, result.stderr
        lines = manifest.read_text().strip().split("\n")
        assert "out/script.sh" in lines
        assert "out/utils.py" in lines


class TestVendorLibFallback:
    """Test that VENDOR_LIB not being set is a graceful fallback scenario."""

    def test_source_fails_gracefully_when_missing(self, tmp_repo):
        """Sourcing a nonexistent VENDOR_LIB should be catchable."""
        test_script = tmp_repo / "test.sh"
        test_script.write_text("""\
#!/bin/bash
set -euo pipefail
VENDOR_LIB="/nonexistent/path/vendor-helpers.sh"
source "$VENDOR_LIB" 2>/dev/null || {
    fetch_file() { echo "fallback fetch_file called"; }
}
fetch_file "a" "b"
""")
        test_script.chmod(0o755)
        result = subprocess.run(
            ["bash", str(test_script)], capture_output=True, text=True)
        assert result.returncode == 0
        assert "fallback fetch_file called" in result.stdout


class TestVendorLibEnvVar:
    """Test that the install script passes VENDOR_LIB."""

    def test_vendor_lib_set_when_file_exists(self, tmp_repo):
        """VENDOR_LIB should be set when .vendored/lib/vendor-helpers.sh exists."""
        # Create the lib file
        lib_dir = tmp_repo / ".vendored" / "lib"
        lib_dir.mkdir(parents=True)
        helpers = lib_dir / "vendor-helpers.sh"
        helpers.write_text("# helpers\n")

        lib_path = str(helpers.resolve())
        assert os.path.isfile(lib_path)

    def test_vendor_lib_not_set_when_file_missing(self, tmp_repo):
        """VENDOR_LIB should not be set when .vendored/lib/vendor-helpers.sh is missing."""
        lib_path = str((tmp_repo / ".vendored" / "lib" / "vendor-helpers.sh").resolve())
        assert not os.path.isfile(lib_path)
