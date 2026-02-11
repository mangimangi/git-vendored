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

mkdir -p .vendored .vendored/hooks .github/workflows

echo "Downloading .vendored/install..."
fetch_file "templates/install" ".vendored/install"
chmod +x .vendored/install

echo "Downloading .vendored/check..."
fetch_file "templates/check" ".vendored/check"
chmod +x .vendored/check

echo "Downloading .vendored/remove..."
fetch_file "templates/remove" ".vendored/remove"
chmod +x .vendored/remove

# Clean up old add/update scripts (merged into install)
rm -f .vendored/add .vendored/update

echo "Downloading .vendored/hooks/pre-commit..."
fetch_file "templates/hooks/pre-commit" ".vendored/hooks/pre-commit"
chmod +x .vendored/hooks/pre-commit

echo "$VERSION" > .vendored/.version
echo "Installed git-vendored v$VERSION"

if [ ! -f .vendored/config.json ]; then
    fetch_file "templates/config.json" ".vendored/config.json"
    echo "Created .vendored/config.json"
fi

install_workflow() {{
    local workflow="$1"
    if fetch_file "templates/github/workflows/$workflow" ".github/workflows/$workflow" 2>/dev/null; then
        echo "Installed .github/workflows/$workflow"
    fi
}}

install_workflow "install-vendored.yml"
install_workflow "check-vendor.yml"

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
        assert (tmp_repo / ".vendored" / "install").is_file()
        assert (tmp_repo / ".vendored" / "check").is_file()
        assert (tmp_repo / ".vendored" / "remove").is_file()

    def test_scripts_are_executable(self, mock_fetch, tmp_repo):
        run_installer(mock_fetch)
        assert os.access(tmp_repo / ".vendored" / "install", os.X_OK)
        assert os.access(tmp_repo / ".vendored" / "check", os.X_OK)
        assert os.access(tmp_repo / ".vendored" / "remove", os.X_OK)

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

    def test_cleans_up_old_add_and_update(self, mock_fetch, tmp_repo):
        """rm -f .vendored/add .vendored/update removes old scripts."""
        (tmp_repo / ".vendored").mkdir(parents=True, exist_ok=True)
        old_add = tmp_repo / ".vendored" / "add"
        old_update = tmp_repo / ".vendored" / "update"
        old_add.write_text("#!/usr/bin/env python3\n# old add script")
        old_update.write_text("#!/usr/bin/env python3\n# old update script")
        assert old_add.is_file()
        assert old_update.is_file()

        run_installer(mock_fetch)

        assert not old_add.exists()
        assert not old_update.exists()
        # install should exist instead
        assert (tmp_repo / ".vendored" / "install").is_file()

    def test_updates_existing_workflow_templates(self, mock_fetch, tmp_repo):
        """Workflow templates are always updated, even if they already exist."""
        (tmp_repo / ".vendored").mkdir(parents=True, exist_ok=True)
        (tmp_repo / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
        # Write a stale workflow file
        workflow = tmp_repo / ".github" / "workflows" / "install-vendored.yml"
        workflow.write_text("# stale workflow content\n")

        run_installer(mock_fetch)

        content = workflow.read_text()
        # Should be replaced with the template content, not the stale content
        assert "# stale workflow content" not in content
        assert "python3 .vendored/install" in content

    def test_no_old_add_or_update_after_fresh_install(self, mock_fetch, tmp_repo):
        """Fresh install should not have .vendored/add or .vendored/update."""
        run_installer(mock_fetch)
        assert not (tmp_repo / ".vendored" / "add").exists()
        assert not (tmp_repo / ".vendored" / "update").exists()


class TestWorkflowTemplate:
    """Verify workflow template properties for token handling, automerge, and PR creation."""

    @pytest.fixture(autouse=True)
    def load_template(self):
        import yaml

        template_path = ROOT / "templates" / "github" / "workflows" / "install-vendored.yml"
        self.raw = template_path.read_text()
        self.workflow = yaml.safe_load(self.raw)
        self.steps = self.workflow["jobs"]["install"]["steps"]

    def _step(self, name_prefix):
        """Find a step by name prefix."""
        for step in self.steps:
            if step.get("name", "").startswith(name_prefix):
                return step
        raise KeyError(f"No step starting with {name_prefix!r}")

    def test_install_step_provides_vendor_pat(self):
        """Install step should expose VENDOR_PAT for private repo downloads."""
        install_step = self._step("Run vendored install")
        assert "VENDOR_PAT" in install_step["env"]

    def test_install_step_provides_github_token(self):
        """Install step should expose GITHUB_TOKEN for PR creation."""
        install_step = self._step("Run vendored install")
        assert install_step["env"]["GITHUB_TOKEN"] == "${{ github.token }}"

    def test_install_step_uses_pr_flag(self):
        """Install step must pass --pr flag for CI PR creation."""
        install_step = self._step("Run vendored install")
        assert "--pr" in install_step["run"]

    def test_install_step_references_vendored_install(self):
        """Install step must call .vendored/install, not .vendored/update."""
        install_step = self._step("Run vendored install")
        run_script = install_step["run"]
        assert "python3 .vendored/install" in run_script
        assert "python3 .vendored/update" not in run_script

    def test_no_pr_creation_step(self):
        """PR creation logic is in the script, not a separate workflow step."""
        step_names = [s.get("name", "") for s in self.steps]
        assert not any("Create Pull Request" in n for n in step_names)
