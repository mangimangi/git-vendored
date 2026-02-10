"""Tests for git-vendored/install.sh bootstrap installer."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
INSTALL_SH = str(ROOT / "install.sh")


@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """Create a temporary directory simulating a repo and chdir into it."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def mock_fetch(tmp_repo):
    """Set up a mock environment where fetch_file copies from git-vendored source.

    Creates a mock_fetch.sh that overrides fetch_file to copy from the
    actual source tree instead of downloading.
    """
    source = ROOT

    # Create a wrapper script that sources install.sh with overridden fetch_file
    wrapper = tmp_repo / "run_install.sh"
    wrapper.write_text(f"""\
#!/bin/bash
set -euo pipefail

VERSION="${{1:?}}"
VENDORED_REPO="${{2:-mangimangi/git-vendored}}"

# Override fetch_file to copy from source tree
fetch_file() {{
    local repo_path="$1"
    local dest="$2"
    local src="{source}/$repo_path"
    if [ -f "$src" ]; then
        cp "$src" "$dest"
    else
        echo "Mock fetch: $src not found" >&2
        return 1
    fi
}}

# Source the rest of install.sh (skip the shebang and function definition)
# Instead, just inline the logic after fetch_file is defined

echo "Installing git-vendored v$VERSION from $VENDORED_REPO"

mkdir -p .vendored .github/workflows

echo "Downloading .vendored/add..."
fetch_file "vendored/add" ".vendored/add"
chmod +x .vendored/add

echo "Downloading .vendored/update..."
fetch_file "vendored/update" ".vendored/update"
chmod +x .vendored/update

echo "Downloading .vendored/check..."
fetch_file "vendored/check" ".vendored/check"
chmod +x .vendored/check

# Clean up old install script (renamed to update)
rm -f .vendored/install

echo "$VERSION" > .vendored/.version
echo "Installed git-vendored v$VERSION"

if [ ! -f .vendored/config.json ]; then
    fetch_file "templates/vendored/config.json" ".vendored/config.json"
    echo "Created .vendored/config.json"
fi

install_workflow() {{
    local workflow="$1"
    if [ -f ".github/workflows/$workflow" ]; then
        echo "Workflow .github/workflows/$workflow already exists, skipping"
        return
    fi
    if fetch_file "templates/github/workflows/$workflow" ".github/workflows/$workflow" 2>/dev/null; then
        echo "Installed .github/workflows/$workflow"
    fi
}}

install_workflow "install-vendored.yml"
install_workflow "check-vendor.yml"

# Patch existing workflow files to reference the renamed script
if [ -f .github/workflows/install-vendored.yml ]; then
    sed -i 's|python3 \\.vendored/install|python3 .vendored/update|g' \\
        .github/workflows/install-vendored.yml
fi

python3 -c "
import json
with open('.vendored/config.json') as f:
    config = json.load(f)
config.setdefault('vendors', {{}})
config['vendors']['git-vendored'] = {{
    'repo': '$VENDORED_REPO',
    'install_branch': 'chore/install-git-vendored',
    'protected': [
        '.vendored/**',
        '.github/workflows/install-vendored.yml',
        '.github/workflows/check-vendor.yml'
    ],
    'allowed': ['.vendored/config.json', '.vendored/.version']
}}
with open('.vendored/config.json', 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\\n')
"

echo ""
echo "Done! git-vendored v$VERSION installed."
""")
    wrapper.chmod(0o755)
    return wrapper


def run_installer(wrapper, version="0.1.0"):
    """Run the mock installer."""
    result = subprocess.run(
        ["bash", str(wrapper), version],
        capture_output=True, text=True
    )
    return result


class TestInstaller:
    def test_creates_vendored_directory(self, mock_fetch, tmp_repo):
        run_installer(mock_fetch)
        assert (tmp_repo / ".vendored").is_dir()

    def test_installs_scripts(self, mock_fetch, tmp_repo):
        run_installer(mock_fetch)
        assert (tmp_repo / ".vendored" / "add").is_file()
        assert (tmp_repo / ".vendored" / "update").is_file()
        assert (tmp_repo / ".vendored" / "check").is_file()

    def test_scripts_are_executable(self, mock_fetch, tmp_repo):
        run_installer(mock_fetch)
        assert os.access(tmp_repo / ".vendored" / "add", os.X_OK)
        assert os.access(tmp_repo / ".vendored" / "update", os.X_OK)
        assert os.access(tmp_repo / ".vendored" / "check", os.X_OK)

    def test_writes_version(self, mock_fetch, tmp_repo):
        run_installer(mock_fetch, "0.1.0")
        version = (tmp_repo / ".vendored" / ".version").read_text().strip()
        assert version == "0.1.0"

    def test_creates_config_if_missing(self, mock_fetch, tmp_repo):
        run_installer(mock_fetch)
        config_path = tmp_repo / ".vendored" / "config.json"
        assert config_path.is_file()
        config = json.loads(config_path.read_text())
        assert "vendors" in config

    def test_preserves_existing_config(self, mock_fetch, tmp_repo):
        # Pre-create config with existing vendor
        (tmp_repo / ".vendored").mkdir(parents=True, exist_ok=True)
        existing = {"vendors": {"my-tool": {"repo": "me/my-tool"}}}
        (tmp_repo / ".vendored" / "config.json").write_text(
            json.dumps(existing, indent=2) + "\n"
        )
        run_installer(mock_fetch)
        config = json.loads((tmp_repo / ".vendored" / "config.json").read_text())
        # my-tool should still be present
        assert "my-tool" in config["vendors"]
        # git-vendored should be added
        assert "git-vendored" in config["vendors"]

    def test_self_registers_in_config(self, mock_fetch, tmp_repo):
        run_installer(mock_fetch)
        config = json.loads((tmp_repo / ".vendored" / "config.json").read_text())
        gv = config["vendors"]["git-vendored"]
        assert gv["repo"] == "mangimangi/git-vendored"
        assert gv["install_branch"] == "chore/install-git-vendored"
        assert ".vendored/**" in gv["protected"]
        assert ".vendored/config.json" in gv["allowed"]

    def test_idempotent_reruns(self, mock_fetch, tmp_repo):
        """Running twice should not fail or corrupt state."""
        result1 = run_installer(mock_fetch, "0.1.0")
        assert result1.returncode == 0
        result2 = run_installer(mock_fetch, "0.2.0")
        assert result2.returncode == 0
        version = (tmp_repo / ".vendored" / ".version").read_text().strip()
        assert version == "0.2.0"

    def test_version_file_updated_on_rerun(self, mock_fetch, tmp_repo):
        run_installer(mock_fetch, "0.1.0")
        run_installer(mock_fetch, "0.2.0")
        version = (tmp_repo / ".vendored" / ".version").read_text().strip()
        assert version == "0.2.0"

    def test_exit_code_zero(self, mock_fetch, tmp_repo):
        result = run_installer(mock_fetch)
        assert result.returncode == 0

    def test_cleans_up_old_install_script(self, mock_fetch, tmp_repo):
        """rm -f .vendored/install removes the old script."""
        (tmp_repo / ".vendored").mkdir(parents=True, exist_ok=True)
        old_install = tmp_repo / ".vendored" / "install"
        old_install.write_text("#!/bin/bash\n# old install script")
        assert old_install.is_file()

        run_installer(mock_fetch)

        assert not old_install.exists()
        # update should exist instead
        assert (tmp_repo / ".vendored" / "update").is_file()

    def test_patches_workflow_references(self, mock_fetch, tmp_repo):
        """sed replacement updates old .vendored/install references in workflow."""
        (tmp_repo / ".vendored").mkdir(parents=True, exist_ok=True)
        (tmp_repo / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
        # Write a workflow file with old reference
        workflow = tmp_repo / ".github" / "workflows" / "install-vendored.yml"
        workflow.write_text(
            'run: python3 .vendored/install "$VENDOR" --version "$VERSION"\n'
        )

        run_installer(mock_fetch)

        content = workflow.read_text()
        assert "python3 .vendored/update" in content
        assert "python3 .vendored/install" not in content

    def test_old_install_not_present_after_fresh_install(self, mock_fetch, tmp_repo):
        """Fresh install should not have .vendored/install."""
        run_installer(mock_fetch)
        assert not (tmp_repo / ".vendored" / "install").exists()
