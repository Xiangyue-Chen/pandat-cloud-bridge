from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "check_local.ps1"
START = ROOT / "scripts" / "start_runner.ps1"


def powershell(script: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        *args,
    ]
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env=env, timeout=20)


def fake_local_environment(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    exe = tmp_path / "Pandat.exe"
    database = tmp_path / "PanHEA.pdb"
    template = tmp_path / "line-template.pbfx"
    runner = tmp_path / "actions-runner"
    exe.write_bytes(b"exe")
    database.write_bytes(b"db")
    template.write_text("<pbfx />", encoding="utf-8")
    runner.mkdir()
    return exe, database, template, runner


def test_readiness_check_is_read_only_and_returns_machine_state(tmp_path: Path) -> None:
    exe, database, template, runner = fake_local_environment(tmp_path)
    run_cmd = runner / "run.cmd"
    run_cmd.write_text("@echo off\r\necho SHOULD_NOT_RUN\r\n", encoding="ascii")
    before = sorted(path.name for path in tmp_path.rglob("*"))

    completed = powershell(
        CHECK,
        "-PandatExe", str(exe),
        "-DatabasePath", str(database),
        "-TemplatePath", str(template),
        "-RunnerRoot", str(runner),
        "-Json",
    )

    assert completed.returncode == 0, completed.stderr
    state = json.loads(completed.stdout)
    assert state == {
        "ready": True,
        "pandat": True,
        "database": True,
        "template": True,
        "runner": True,
    }
    assert "SHOULD_NOT_RUN" not in completed.stdout
    assert sorted(path.name for path in tmp_path.rglob("*")) == before


def test_readiness_check_reports_missing_database_without_exposing_token(tmp_path: Path) -> None:
    exe, database, template, runner = fake_local_environment(tmp_path)
    (runner / "run.cmd").write_text("@echo off\r\n", encoding="ascii")
    database.unlink()
    env = {**os.environ, "GITHUB_TOKEN": "super-secret-token"}

    completed = powershell(
        CHECK,
        "-PandatExe", str(exe),
        "-DatabasePath", str(database),
        "-TemplatePath", str(template),
        "-RunnerRoot", str(runner),
        "-Json",
        env=env,
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["database"] is False
    assert "super-secret-token" not in completed.stdout + completed.stderr


def test_start_runner_validate_only_never_executes_runner(tmp_path: Path) -> None:
    exe, database, template, runner = fake_local_environment(tmp_path)
    marker = tmp_path / "started.txt"
    (runner / "run.cmd").write_text(f"@echo off\r\necho started>\"{marker}\"\r\n", encoding="ascii")

    completed = powershell(
        START,
        "-PandatExe", str(exe),
        "-DatabasePath", str(database),
        "-TemplatePath", str(template),
        "-RunnerRoot", str(runner),
        "-ValidateOnly",
    )

    assert completed.returncode == 0, completed.stderr
    assert "ready" in completed.stdout.lower()
    assert not marker.exists()


def test_start_runner_launches_existing_runner_interactively_with_local_environment(
    tmp_path: Path,
) -> None:
    exe, database, template, runner = fake_local_environment(tmp_path)
    marker = tmp_path / "runner-env.txt"
    (runner / "run.cmd").write_text(
        "@echo off\r\n"
        f"echo %PANDAT_EXE%^|%PANDAT_DATABASE_PATH%^|%PANDAT_TEMPLATE_PATH%>\"{marker}\"\r\n",
        encoding="ascii",
    )

    completed = powershell(
        START,
        "-PandatExe", str(exe),
        "-DatabasePath", str(database),
        "-TemplatePath", str(template),
        "-RunnerRoot", str(runner),
    )

    assert completed.returncode == 0, completed.stderr
    assert marker.read_text(encoding="utf-8").strip() == f"{exe}|{database}|{template}"
    assert not (runner / "config.cmd").exists()
