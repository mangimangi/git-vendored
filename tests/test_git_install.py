"""The installer reads vendors with git: local repositories as vendors.

Each vendor here is a local git repository (the ``vendor_repo`` fixture in
conftest.py) addressed by a file:// URL, so nothing reaches the network and
no platform is involved. The end-to-end tests run the installer as a
program with ``gh`` absent from PATH.
"""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
INSTALL = ROOT / "templates" / "install"


def _import_install():
    filepath = str(INSTALL)
    loader = importlib.machinery.SourceFileLoader("vendored_install_git", filepath)
    spec = importlib.util.spec_from_loader("vendored_install_git", loader,
                                           origin=filepath)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = filepath
    spec.loader.exec_module(module)
    return module


inst = _import_install()

# install.sh of the fixture vendor: copies its files from the checkout itself
# and writes the manifest; deps.json and the schema sit next to it.
VENDOR_INSTALL_SH = """#!/bin/bash
set -euo pipefail
mkdir -p "$VENDOR_INSTALL_DIR"
cp "$VENDOR_CHECKOUT/tool.sh" "$VENDOR_INSTALL_DIR/tool.sh"
echo "$VENDOR_REF" > "$VENDOR_INSTALL_DIR/ref.txt"
printf '%s\\n' "$VENDOR_INSTALL_DIR/tool.sh" "$VENDOR_INSTALL_DIR/ref.txt" \\
    > "$VENDOR_MANIFEST"
"""


def make_tool(vendor_repo, name="tool"):
    """A vendor at v1.0.0 (lightweight tag); returns (repo, commit)."""
    repo = vendor_repo(name)
    repo.write("install.sh", VENDOR_INSTALL_SH)
    repo.write("tool.sh", "echo one\n")
    repo.write("templates/config.schema", json.dumps({"vendor": "tool", "v": 1}))
    repo.commit("v1")
    return repo, repo.tag("v1.0.0")


@pytest.fixture
def adopter(tmp_path, monkeypatch):
    """An adopting repository (cwd) with an empty git-vendored setup."""
    path = tmp_path / "adopter"
    (path / ".vendored").mkdir(parents=True)
    (path / ".vendored" / "config.json").write_text('{"vendors": {}}\n')
    monkeypatch.chdir(path)
    return path


@pytest.fixture
def no_gh_path(tmp_path):
    """A PATH with every tool of the system's PATH but gh."""
    bindir = tmp_path / "bin-no-gh"
    bindir.mkdir()
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not os.path.isdir(d):
            continue
        for entry in os.listdir(d):
            src = os.path.join(d, entry)
            dst = bindir / entry
            if entry == "gh" or dst.exists() or not os.access(src, os.X_OK):
                continue
            if os.path.isfile(src):
                dst.symlink_to(src)
    assert not (bindir / "gh").exists()
    return str(bindir)


def run_installer(args, cwd, path):
    env = dict(os.environ, PATH=path)
    return subprocess.run([sys.executable, str(INSTALL), *args], cwd=str(cwd),
                          capture_output=True, text=True, env=env, timeout=120)


def _mkdtemp_spy(monkeypatch):
    made = []
    real = tempfile.mkdtemp

    def spy(*args, **kwargs):
        path = real(*args, **kwargs)
        made.append(path)
        return path
    monkeypatch.setattr(inst.tempfile, "mkdtemp", spy)
    return made


# ── fetch_vendor ──────────────────────────────────────────────────────────

class TestFetchVendor:
    def test_fetches_tag_outside_repo_and_removes_it(self, vendor_repo, adopter):
        repo, commit = make_tool(vendor_repo)
        repo.write("tool.sh", "echo later\n")
        repo.commit("after the tag")
        with inst.fetch_vendor(repo.url, "v1.0.0", "", commit) as checkout:
            assert os.path.isabs(checkout)
            assert os.path.basename(checkout).startswith("gv-vendor-")
            assert not os.path.realpath(checkout).startswith(
                os.path.realpath(str(adopter)))
            assert Path(checkout, "tool.sh").read_text() == "echo one\n"
        assert not os.path.exists(checkout)

    def test_removed_when_install_exits(self, vendor_repo, adopter):
        repo, commit = make_tool(vendor_repo)
        with pytest.raises(SystemExit):
            with inst.fetch_vendor(repo.url, "v1.0.0", "", commit) as checkout:
                sys.exit(1)
        assert not os.path.exists(checkout)

    def test_clone_failure_names_repo_and_tag_without_token(
            self, vendor_repo, adopter, monkeypatch, capsys):
        repo, _ = make_tool(vendor_repo)
        made = _mkdtemp_spy(monkeypatch)
        with pytest.raises(SystemExit) as exc_info:
            with inst.fetch_vendor(repo.url, "v9.9.9", "s3cret"):
                pass  # pragma: no cover - the fetch fails before this
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert f"::error::Failed to fetch {repo.url} at v9.9.9" in out
        assert "s3cret" not in out
        assert made and not os.path.exists(made[0])

    def test_moved_tag_between_list_and_fetch(self, vendor_repo, adopter, capsys):
        repo, commit = make_tool(vendor_repo)
        listed = "f" * 40
        with pytest.raises(SystemExit) as exc_info:
            with inst.fetch_vendor(repo.url, "v1.0.0", "", listed):
                pass  # pragma: no cover - the check fails before this
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert listed in out and commit in out
        assert "moved while fetching" in out

    def test_token_scoped_to_vendor_url(self, monkeypatch):
        for key in list(os.environ):
            if key.startswith("GIT_CONFIG_"):
                monkeypatch.delenv(key)
        env = inst._git_env("tok", "https://git.example.com/t/tool.git")
        assert env["GIT_CONFIG_KEY_0"] == \
            "http.https://git.example.com/t/tool.git.extraHeader"


# ── Add and upgrade from a file:// vendor (in-process) ────────────────────

def _main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["install", *args])
    inst.main()


class TestInstallFromGit:
    def test_add_then_upgrade(self, vendor_repo, adopter, monkeypatch, capsys):
        repo, c1 = make_tool(vendor_repo)
        made = _mkdtemp_spy(monkeypatch)
        _main(monkeypatch, repo.url)
        manifests = adopter / ".vendored" / "manifests"
        assert (manifests / "tool.version").read_text() == "1.0.0\n"
        assert (manifests / "tool.commit").read_text() == c1 + "\n"
        assert (manifests / "tool.files").read_text().split() == [
            ".vendored/pkg/tool/ref.txt", ".vendored/pkg/tool/tool.sh"]
        assert (adopter / ".vendored/pkg/tool/ref.txt").read_text() == "v1.0.0\n"
        registry = json.loads((manifests / "tool.registry").read_text())
        assert registry["repo"] == repo.url
        assert json.loads((manifests / "tool.schema").read_text())["v"] == 1

        repo.write("tool.sh", "echo two\n")
        repo.write("templates/config.schema", json.dumps({"vendor": "tool", "v": 2}))
        repo.commit("v2")
        c2 = repo.tag("v2.0.0", annotated=True)
        _main(monkeypatch, "tool")
        assert (manifests / "tool.version").read_text() == "2.0.0\n"
        assert (manifests / "tool.commit").read_text() == c2 + "\n"
        assert (adopter / ".vendored/pkg/tool/tool.sh").read_text() == "echo two\n"
        assert json.loads((manifests / "tool.schema").read_text())["v"] == 2
        assert len(made) == 2
        assert not any(os.path.exists(p) for p in made)

    def test_deps_and_schema_read_at_the_tag(self, vendor_repo, adopter,
                                             monkeypatch, capsys):
        dep, _ = make_tool(vendor_repo, "dep")
        repo, _ = make_tool(vendor_repo)
        repo.write("deps.json", json.dumps({"dep": {"repo": dep.url}}))
        repo.commit("declare dep")
        repo.tag("v1.1.0")
        # A change on the default branch after the tag is not seen
        repo.write("deps.json", json.dumps({"other": {"repo": "o/other"}}))
        repo.write("templates/config.schema", "{broken")
        repo.commit("after the tag")
        _main(monkeypatch, repo.url, "--deps", "install")
        manifests = adopter / ".vendored" / "manifests"
        assert (manifests / "tool.deps").read_text() == "dep\n"
        assert (manifests / "dep.version").read_text() == "1.0.0\n"
        assert json.loads((manifests / "tool.schema").read_text())["v"] == 1

    def test_no_install_sh_at_the_tag(self, vendor_repo, adopter, monkeypatch,
                                      capsys):
        repo = vendor_repo()
        repo.write("README", "no installer\n")
        repo.commit("one")
        repo.tag("v1.0.0")
        repo.write("install.sh", VENDOR_INSTALL_SH)
        repo.commit("installer only after the tag")
        made = _mkdtemp_spy(monkeypatch)
        with pytest.raises(SystemExit) as exc_info:
            _main(monkeypatch, repo.url)
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert f"::error::Repo does not implement git-vendored: {repo.url}" in out
        assert not any(os.path.exists(p) for p in made)

    def test_failing_install_sh_removes_checkout(self, vendor_repo, adopter,
                                                 monkeypatch, capsys):
        repo = vendor_repo()
        repo.write("install.sh", "#!/bin/bash\nexit 4\n")
        repo.commit("one")
        repo.tag("v1.0.0")
        made = _mkdtemp_spy(monkeypatch)
        with pytest.raises(SystemExit):
            _main(monkeypatch, repo.url)
        assert "install.sh failed" in capsys.readouterr().out
        assert made and not any(os.path.exists(p) for p in made)

    def test_url_target_named_by_basename_without_git(self, vendor_repo,
                                                      adopter, monkeypatch,
                                                      capsys):
        repo, _ = make_tool(vendor_repo, "tool.git")
        _main(monkeypatch, repo.url)
        assert (adopter / ".vendored/manifests/tool.version").is_file()
        assert "vendor=tool" in capsys.readouterr().out
        # The same URL updates the registered vendor
        _main(monkeypatch, repo.url)
        assert "is registered as vendor 'tool'" in capsys.readouterr().out


class TestTargets:
    @pytest.mark.parametrize("target", [
        "https://git.example.com/team/tool.git",
        "ssh://git@example.com/team/tool.git",
        "git@example.com:team/tool.git",
        "file:///srv/git/tool",
    ])
    def test_url_is_a_repo_target(self, target):
        assert inst._is_repo_spec(target)
        assert inst.validate_target(target) is None
        assert inst.vendor_name_for(target) == "tool"

    def test_url_without_name_rejected(self):
        assert inst.validate_target("file:///") == "the URL names no repository"

    def test_malformed_owner_repo_rejected_before_git(self, adopter, monkeypatch,
                                                      capsys):
        calls = []
        monkeypatch.setattr(inst.subprocess, "run",
                            lambda *a, **k: calls.append(a))
        with pytest.raises(SystemExit):
            _main(monkeypatch, "a/b/c")
        assert "owner/repo must contain exactly one '/'" in capsys.readouterr().out
        assert calls == []


# ── End to end: the installer as a program, gh absent ─────────────────────

class TestNoGh:
    def test_add_and_upgrade_without_gh(self, vendor_repo, adopter, no_gh_path):
        repo, c1 = make_tool(vendor_repo)
        result = run_installer([repo.url], adopter, no_gh_path)
        assert result.returncode == 0, result.stdout + result.stderr
        manifests = adopter / ".vendored" / "manifests"
        assert (manifests / "tool.version").read_text() == "1.0.0\n"
        assert (manifests / "tool.commit").read_text() == c1 + "\n"

        repo.write("tool.sh", "echo two\n")
        repo.commit("v2")
        c2 = repo.tag("v2.0.0")
        result = run_installer(["tool"], adopter, no_gh_path)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "tool: 1.0.0 -> 2.0.0" in result.stdout
        assert (manifests / "tool.version").read_text() == "2.0.0\n"
        assert (manifests / "tool.commit").read_text() == c2 + "\n"
        assert (manifests / "tool.files").read_text().split() == [
            ".vendored/pkg/tool/ref.txt", ".vendored/pkg/tool/tool.sh"]
        assert (adopter / ".vendored/pkg/tool/tool.sh").read_text() == "echo two\n"

    def test_moved_tag_warns(self, vendor_repo, adopter, no_gh_path):
        repo, c1 = make_tool(vendor_repo)
        assert run_installer([repo.url], adopter, no_gh_path).returncode == 0
        repo.write("tool.sh", "echo retagged\n")
        c2 = repo.commit("retag")
        repo.move_tag("v1.0.0")
        result = run_installer(["tool"], adopter, no_gh_path)
        assert result.returncode == 0, result.stdout + result.stderr
        assert (f"::warning::tool: tag v1.0.0 now points at {c2}, "
                f"recorded {c1}") in result.stdout
        assert "already at v1.0.0, skipping" in result.stdout


HELPER_INSTALL_SH = """#!/bin/bash
set -euo pipefail
source "$VENDOR_LIB"
fetch_file tool "$VENDOR_INSTALL_DIR/tool" +x
fetch_dir templates "$VENDOR_INSTALL_DIR/templates"
"""


class TestHelperVendorNoGh:
    def test_helper_using_vendor_installs_from_checkout(self, vendor_repo,
                                                        adopter, no_gh_path):
        lib = adopter / ".vendored" / "lib"
        lib.mkdir()
        (lib / "vendor-helpers.sh").write_bytes(
            (ROOT / "templates" / "lib" / "vendor-helpers.sh").read_bytes())
        repo = vendor_repo()
        repo.write("install.sh", HELPER_INSTALL_SH)
        repo.write("tool", "#!/bin/bash\necho tool\n", mode=0o755)
        repo.write("templates/hooks/pre.sh", "hook\n", mode=0o755)
        repo.write("templates/a.txt", "a\n")
        repo.commit("v1")
        repo.tag("v1.0.0")
        result = run_installer([repo.url], adopter, no_gh_path)
        assert result.returncode == 0, result.stdout + result.stderr
        pkg = adopter / ".vendored" / "pkg" / "tool"
        assert (pkg / "tool").read_text() == "#!/bin/bash\necho tool\n"
        assert os.access(pkg / "tool", os.X_OK)
        assert (pkg / "templates/hooks/pre.sh").read_text() == "hook\n"
        assert not os.access(pkg / "templates/hooks/pre.sh", os.X_OK)
        assert (adopter / ".vendored/manifests/tool.files").read_text().split() == [
            ".vendored/pkg/tool/templates/a.txt",
            ".vendored/pkg/tool/templates/hooks/pre.sh",
            ".vendored/pkg/tool/tool",
        ]
