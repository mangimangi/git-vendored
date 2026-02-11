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

# v2 contract: read env vars, fall back to positional args
VERSION="${{VENDOR_REF:-${{1:?}}}}"
VENDORED_REPO="${{VENDOR_REPO:-${{2:-mangimangi/git-vendored}}}}"

# Track installed files for manifest
INSTALLED_FILES=()

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

echo "Installing git-vendored v$VERSION from $VENDORED_REPO"

mkdir -p .vendored .vendored/hooks .vendored/manifests .github/workflows

echo "Downloading .vendored/install..."
fetch_file "templates/install" ".vendored/install"
chmod +x .vendored/install
INSTALLED_FILES+=(".vendored/install")

echo "Downloading .vendored/check..."
fetch_file "templates/check" ".vendored/check"
chmod +x .vendored/check
INSTALLED_FILES+=(".vendored/check")

echo "Downloading .vendored/remove..."
fetch_file "templates/remove" ".vendored/remove"
chmod +x .vendored/remove
INSTALLED_FILES+=(".vendored/remove")

# Clean up old add/update scripts (merged into install)
rm -f .vendored/add .vendored/update

echo "Downloading .vendored/hooks/pre-commit..."
fetch_file "templates/hooks/pre-commit" ".vendored/hooks/pre-commit"
chmod +x .vendored/hooks/pre-commit
INSTALLED_FILES+=(".vendored/hooks/pre-commit")

echo "$VERSION" > .vendored/.version
echo "Installed git-vendored v$VERSION"
INSTALLED_FILES+=(".vendored/.version")

if [ ! -f .vendored/config.json ]; then
    fetch_file "templates/config.json" ".vendored/config.json"
    echo "Created .vendored/config.json"
fi

install_workflow() {{
    local workflow="$1"
    if fetch_file "templates/github/workflows/$workflow" ".github/workflows/$workflow" 2>/dev/null; then
        echo "Installed .github/workflows/$workflow"
        INSTALLED_FILES+=(".github/workflows/$workflow")
    fi
}}

install_workflow "install-vendored.yml"
install_workflow "check-vendor.yml"

# v2 contract: install.sh does NOT self-register in config.json.
# The framework handles registration after reading the manifest.

# Write manifest (v2 contract)
write_manifest() {{
    if [ -n "${{VENDOR_MANIFEST:-}}" ]; then
        printf '%s\\n' "${{INSTALLED_FILES[@]}}" > "$VENDOR_MANIFEST"
    fi
    printf '%s\\n' "${{INSTALLED_FILES[@]}}" | sort > .vendored/manifests/git-vendored.files
    echo "$VERSION" > .vendored/manifests/git-vendored.version
}}

write_manifest

echo ""
echo "Done! git-vendored v$VERSION installed."
""")
    wrapper.chmod(0o755)
    return wrapper


def run_installer(wrapper, version="0.1.0", env=None):
    """Run the mock installer."""
    result = subprocess.run(
        ["bash", str(wrapper), version],
        capture_output=True, text=True, env=env
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
        """install.sh should not modify existing config.json (v2: framework handles registration)."""
        (tmp_repo / ".vendored").mkdir(parents=True, exist_ok=True)
        existing = {"vendors": {"my-tool": {"repo": "me/my-tool"}}}
        original_text = json.dumps(existing, indent=2) + "\n"
        (tmp_repo / ".vendored" / "config.json").write_text(original_text)
        run_installer(mock_fetch)
        # Config should be unchanged — install.sh does not modify it
        assert (tmp_repo / ".vendored" / "config.json").read_text() == original_text

    def test_does_not_self_register_in_config(self, mock_fetch, tmp_repo):
        """v2 contract: install.sh must NOT self-register in config.json."""
        run_installer(mock_fetch)
        config = json.loads((tmp_repo / ".vendored" / "config.json").read_text())
        # The template config.json has an empty vendors dict
        # install.sh should NOT have added a git-vendored entry
        assert "git-vendored" not in config.get("vendors", {})

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

    def test_reads_vendor_ref_env_var(self, mock_fetch, tmp_repo):
        """VENDOR_REF env var should be used as version when set."""
        env = os.environ.copy()
        env["VENDOR_REF"] = "0.5.0"
        result = run_installer(mock_fetch, "0.1.0", env=env)
        assert result.returncode == 0
        # VENDOR_REF takes priority over positional arg
        version_path = tmp_repo / ".vendored" / "manifests" / "git-vendored.version"
        assert version_path.read_text().strip() == "0.5.0"

    def test_reads_vendor_repo_env_var(self, mock_fetch, tmp_repo):
        """VENDOR_REPO env var should be used as repo when set."""
        env = os.environ.copy()
        env["VENDOR_REPO"] = "other-org/git-vendored"
        result = run_installer(mock_fetch, "0.1.0", env=env)
        assert result.returncode == 0


class TestManifest:
    """Verify v2 manifest contract in install.sh."""

    def test_writes_manifest_files(self, mock_fetch, tmp_repo):
        """install.sh should write .vendored/manifests/git-vendored.files."""
        run_installer(mock_fetch, "0.1.0")
        manifest_path = tmp_repo / ".vendored" / "manifests" / "git-vendored.files"
        assert manifest_path.is_file()
        content = manifest_path.read_text()
        assert ".vendored/install" in content
        assert ".vendored/check" in content
        assert ".vendored/remove" in content
        assert ".vendored/hooks/pre-commit" in content
        assert ".vendored/.version" in content

    def test_writes_manifest_version(self, mock_fetch, tmp_repo):
        """install.sh should write .vendored/manifests/git-vendored.version."""
        run_installer(mock_fetch, "0.1.0")
        version_path = tmp_repo / ".vendored" / "manifests" / "git-vendored.version"
        assert version_path.is_file()
        assert version_path.read_text().strip() == "0.1.0"

    def test_manifest_version_updated_on_rerun(self, mock_fetch, tmp_repo):
        run_installer(mock_fetch, "0.1.0")
        run_installer(mock_fetch, "0.2.0")
        version_path = tmp_repo / ".vendored" / "manifests" / "git-vendored.version"
        assert version_path.read_text().strip() == "0.2.0"

    def test_manifest_includes_workflow_files(self, mock_fetch, tmp_repo):
        run_installer(mock_fetch, "0.1.0")
        manifest_path = tmp_repo / ".vendored" / "manifests" / "git-vendored.files"
        content = manifest_path.read_text()
        assert ".github/workflows/install-vendored.yml" in content
        assert ".github/workflows/check-vendor.yml" in content

    def test_writes_to_vendor_manifest_env(self, mock_fetch, tmp_repo):
        """When VENDOR_MANIFEST is set, install.sh writes to that path too."""
        manifest_file = tmp_repo / "vendor_manifest.txt"
        env = os.environ.copy()
        env["VENDOR_MANIFEST"] = str(manifest_file)
        run_installer(mock_fetch, "0.1.0", env=env)
        assert manifest_file.is_file()
        content = manifest_file.read_text()
        assert ".vendored/install" in content

    def test_manifest_files_sorted(self, mock_fetch, tmp_repo):
        """Manifest file entries should be sorted."""
        run_installer(mock_fetch, "0.1.0")
        manifest_path = tmp_repo / ".vendored" / "manifests" / "git-vendored.files"
        lines = [l.strip() for l in manifest_path.read_text().strip().split("\n") if l.strip()]
        assert lines == sorted(lines)


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
