import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def database():
    """These shell orchestration checks do not use PostgreSQL."""


@pytest.fixture
def dev_environment(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['DOCKER_LOG'], 'a') as log:\n"
        "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
    )
    docker.chmod(0o755)
    uv = bin_dir / "uv"
    uv.write_text("#!/bin/sh\nprintf 'synthetic-test-token\\n'\n")
    uv.chmod(0o755)
    env = os.environ.copy()
    env.pop("DEV_PROJECT_NAME", None)
    env.pop("MAKEFLAGS", None)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["DOCKER_LOG"] = str(tmp_path / "docker.jsonl")
    return env


def checkout(parent, name):
    root = parent / name
    root.mkdir()
    shutil.copytree(ROOT / "scripts", root / "scripts")
    shutil.copy(ROOT / "Makefile", root / "Makefile")
    return root


def run_make(root, env):
    subprocess.run(
        ["make", "dev", "dev-stop"], cwd=root, env=env, check=True, capture_output=True, text=True
    )
    log = Path(env["DOCKER_LOG"])
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    log.unlink()
    assert len(calls) == 2
    start, stop = calls
    assert start[:2] == stop[:2] == ["compose", "-p"]
    assert start[2] == stop[2]
    assert start[3:] == ["-f", "compose.dev.yaml", "up", "-d", "--wait"]
    assert stop[3:] == ["-f", "compose.dev.yaml", "stop"]
    return start[2]


def test_checkout_projects_are_distinct_and_stable(tmp_path, dev_environment):
    first = checkout(tmp_path, "first checkout")
    second = checkout(tmp_path, "second checkout")
    first_project = run_make(first, {**dev_environment, "DEV_DATABASE_PORT": "55440"})
    second_project = run_make(second, {**dev_environment, "DEV_DATABASE_PORT": "55441"})
    assert first_project != second_project
    assert first_project == run_make(first, dev_environment)
    alias = tmp_path / "alias"
    alias.symlink_to(first, target_is_directory=True)
    assert first_project == run_make(alias, dev_environment)


def test_project_override_wins(tmp_path, dev_environment):
    env = {**dev_environment, "DEV_PROJECT_NAME": "stride-custom"}
    for name in ("first", "second"):
        assert run_make(checkout(tmp_path, name), env) == "stride-custom"
