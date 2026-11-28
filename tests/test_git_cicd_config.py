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


def _jobs():
    with CONFIG_PATH.open() as f:
        return json.load(f)["jobs"]


def test_job_set():
    assert set(_jobs()) == {"test", "vendor-check", "release",
                            "update-vendored", "validate"}


def test_every_step_is_an_executable_file():
    for name, job in _jobs().items():
        for step in [job.get("setup")] + job["steps"]:
            if step is None:
                continue
            path = ROOT / (step if isinstance(step, str) else step[0])
            assert path.is_file(), f"job {name}: {path} is missing"
            assert os.access(path, os.X_OK), f"job {name}: {path} is not executable"


def test_release_job():
    job = _jobs()["release"]
    assert job["on"] == ["merge"]
    assert job["branches"] == ["main"]
    assert job.get("manual", True) is True
    assert job["steps"] == [".vendored/pkg/git-semver/release"]
    inputs = job["inputs"]
    assert set(inputs) == {"bump_type", "subdirectory", "changelog_description"}
    assert inputs["bump_type"]["choices"] == ["patch", "minor", "major"]
    assert inputs["bump_type"]["default"] == "patch"
    assert inputs["subdirectory"]["default"] == ""
    assert inputs["changelog_description"]["default"] == ""


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
