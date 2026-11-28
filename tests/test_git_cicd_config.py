"""Guard the jobs in .vendored/configs/git-cicd.json (gv-05c2.5).

The repository's own CI, release, vendor update and vendor validation run as
git-cicd jobs; these tests keep their triggers, inputs and steps from
drifting, and check that the steps they name exist and are executable.
"""

import json
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / ".vendored" / "configs" / "git-cicd.json"
SEMVER_CONFIG_PATH = ROOT / ".vendored" / "configs" / "git-semver.json"


def _jobs():
    with CONFIG_PATH.open() as f:
        return json.load(f)["jobs"]


def test_job_set():
    assert set(_jobs()) == {"test", "vendor-check", "version-check", "release",
                            "update-vendored", "validate"}


def test_every_step_is_an_executable_file():
    for name, job in _jobs().items():
        for step in [job.get("setup")] + job["steps"]:
            if step is None:
                continue
            path = ROOT / (step if isinstance(step, str) else step[0])
            assert path.is_file(), f"job {name}: {path} is missing"
            assert os.access(path, os.X_OK), f"job {name}: {path} is not executable"


def test_version_check_job():
    """Pull requests into main must raise the version when they change a
    file git-semver watches (bump_on: pull_request)."""
    job = _jobs()["version-check"]
    assert job["on"] == ["open"]
    assert job["branches"] == ["main"]
    assert job["paths"] == ["**"]
    assert job["steps"] == [[".vendored/pkg/git-semver/git-semver", "check-bump"]]


def test_release_job():
    """release tags the landed commit: no subcommand, and none of the bump
    inputs, which git-semver refuses in bump_on: pull_request mode."""
    job = _jobs()["release"]
    assert job["on"] == ["merge"]
    assert job["branches"] == ["main"]
    assert job.get("manual", True) is True
    assert job["steps"] == [".vendored/pkg/git-semver/release"]
    assert "inputs" not in job


def test_semver_files_are_not_needs_nothing():
    """A change to only a file git-semver watches still runs version-check."""
    with CONFIG_PATH.open() as f:
        needs_nothing = json.load(f)["needs_nothing"]
    with SEMVER_CONFIG_PATH.open() as f:
        semver = json.load(f)
    assert semver["bump_on"] == "pull_request"
    for pattern in semver["files"]:
        assert pattern not in needs_nothing
    assert "*.md" not in needs_nothing


def test_update_vendored_job():
    job = _jobs()["update-vendored"]
    assert job["on"] == ["cron"]
    assert job["cron"] == "0 9 * * 1"
    assert job["branches"] == ["main"]
    assert job.get("manual", True) is True
    assert job["steps"] == ["ci/update-vendored.sh"]
    inputs = job["inputs"]
    assert set(inputs) == {"vendor", "version", "private"}
    assert inputs["vendor"]["default"] == "all"
    assert inputs["version"]["default"] == "latest"
    assert inputs["private"]["choices"] == ["false", "true"]
    assert inputs["private"]["default"] == "false"


def test_validate_job_is_manual_only():
    job = _jobs()["validate"]
    assert job["on"] == []
    assert job.get("manual", True) is True
    assert job["steps"] == ["ci/validate.sh"]
    inputs = job["inputs"]
    assert set(inputs) == {"repo", "version"}
    assert inputs["repo"]["required"] is True
    assert "default" not in inputs["repo"]
    assert inputs["version"]["default"] == "latest"
