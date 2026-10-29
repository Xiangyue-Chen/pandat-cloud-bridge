from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from pandat_bridge.runner import RunnerError, run_pandat


FAKE = Path(__file__).with_name("fake_pandat.py")
WINDOWS_LAUNCHER = Path(__file__).resolve().parents[1] / "scripts" / "run_pandat_process.ps1"


def make_pbfx(tmp_path: Path) -> Path:
    path = tmp_path / "job.pbfx"
    path.write_text("<pbfx />", encoding="utf-8")
    return path


def test_detects_success_and_fresh_native_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_PANDAT_MODE", "success")

    outcome = run_pandat(make_pbfx(tmp_path), FAKE, timeout_s=2)

    assert outcome.status == "success"
    assert outcome.error_code is None
    assert outcome.result_path == tmp_path / "job.result"
    assert outcome.result_path.read_text(encoding="utf-8") == "<result />"
    assert "Simulation is done with Success" in outcome.stdout_path.read_text(encoding="utf-8")
    assert outcome.seconds < 2


def test_detects_matching_fresh_result_in_native_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "pandat-temp"
    output_dir.mkdir()
    pbfx = tmp_path / "job.pbfx"
    pbfx.write_text(
        '<pbfx><calculation name="target-job" type="line" /></pbfx>',
        encoding="utf-8",
    )
    fake = _write_fake_executable_script(
        tmp_path / "native_output_fake.py",
        "import os\n"
        "from pathlib import Path\n"
        "out = Path(os.environ['FAKE_PANDAT_OUTPUT_DIR'])\n"
        "(out / 'calc_foreign.result').write_text(\"<Pandat_Result><section name='other-job' type='line'/></Pandat_Result>\", encoding='utf-8')\n"
        "(out / 'calc_target.result').write_text(\"<Pandat_Result><section name='target-job' type='line'/></Pandat_Result>\", encoding='utf-8')\n"
        "table = out / 'job.dat.table'\n"
        "table.write_text('table', encoding='utf-8')\n"
        "print(f'1: {table}', flush=True)\n"
        "print('Simulation is done with Success for [target-job].', flush=True)\n",
    )
    monkeypatch.setenv("FAKE_PANDAT_OUTPUT_DIR", str(output_dir))

    outcome = run_pandat(pbfx, fake, timeout_s=2)

    assert outcome.status == "success"
    assert outcome.error_code is None
    assert outcome.result_path == output_dir / "calc_target.result"


def test_rejects_matching_native_result_that_predates_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "pandat-temp"
    output_dir.mkdir()
    stale = output_dir / "calc_target.result"
    stale.write_text(
        "<Pandat_Result><section name='target-job' type='line'/></Pandat_Result>",
        encoding="utf-8",
    )
    pbfx = tmp_path / "job.pbfx"
    pbfx.write_text(
        '<pbfx><calculation name="target-job" type="line" /></pbfx>',
        encoding="utf-8",
    )
    fake = _write_fake_executable_script(
        tmp_path / "native_output_without_result.py",
        "import os\n"
        "from pathlib import Path\n"
        "out = Path(os.environ['FAKE_PANDAT_OUTPUT_DIR'])\n"
        "table = out / 'job.dat.table'\n"
        "table.write_text('table', encoding='utf-8')\n"
        "print(f'1: {table}', flush=True)\n"
        "print('Simulation is done with Success for [target-job].', flush=True)\n",
    )
    monkeypatch.setenv("FAKE_PANDAT_OUTPUT_DIR", str(output_dir))

    outcome = run_pandat(pbfx, fake, timeout_s=2)

    assert outcome.status == "failed"
    assert outcome.error_code == "stale_result"


def test_does_not_fall_back_to_pbfx_result_after_native_output_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "pandat-temp"
    output_dir.mkdir()
    pbfx = tmp_path / "job.pbfx"
    pbfx.write_text(
        '<pbfx><calculation name="target-job" type="line" /></pbfx>',
        encoding="utf-8",
    )
    fake = _write_fake_executable_script(
        tmp_path / "native_output_with_wrong_fallback.py",
        "import os, sys\n"
        "from pathlib import Path\n"
        "pbfx = Path(sys.argv[1]).resolve()\n"
        "pbfx.with_suffix('.result').write_text(\"<Pandat_Result><section name='wrong-job' type='line'/></Pandat_Result>\", encoding='utf-8')\n"
        "out = Path(os.environ['FAKE_PANDAT_OUTPUT_DIR'])\n"
        "table = out / 'job.dat.table'\n"
        "table.write_text('table', encoding='utf-8')\n"
        "print(f'1: {table}', flush=True)\n"
        "print('Simulation is done with Success for [target-job].', flush=True)\n",
    )
    monkeypatch.setenv("FAKE_PANDAT_OUTPUT_DIR", str(output_dir))

    outcome = run_pandat(pbfx, fake, timeout_s=2)

    assert outcome.status == "failed"
    assert outcome.error_code == "missing_result"


@pytest.mark.parametrize(
    ("mode", "status", "code", "message"),
    [
        ("license", "failed", "license_unavailable", "license"),
        ("unsupported", "failed", "unsupported_element", "Ta"),
        ("failure", "failed", "pandat_failure", "failure"),
        ("early_exit", "failed", "early_exit", "exit"),
        ("missing", "failed", "missing_result", "missing"),
        ("stale", "failed", "stale_result", "stale"),
        ("timeout", "failed", "timeout", "timeout"),
    ],
)
def test_classifies_native_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    status: str,
    code: str,
    message: str,
) -> None:
    monkeypatch.setenv("FAKE_PANDAT_MODE", mode)

    outcome = run_pandat(make_pbfx(tmp_path), FAKE, timeout_s=0.35)

    assert outcome.status == status
    assert outcome.error_code == code
    assert message.lower() in outcome.message.lower()


def test_timeout_terminates_only_the_started_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    monkeypatch.setenv("FAKE_PANDAT_MODE", "timeout")
    try:
        outcome = run_pandat(make_pbfx(tmp_path), FAKE, timeout_s=0.25)
        assert outcome.error_code == "timeout"
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_rejects_missing_inputs_before_launch(tmp_path: Path) -> None:
    pbfx = make_pbfx(tmp_path)

    with pytest.raises(RunnerError, match="executable"):
        run_pandat(pbfx, tmp_path / "missing.exe", timeout_s=1)
    with pytest.raises(RunnerError, match="PBFX"):
        run_pandat(tmp_path / "missing.pbfx", FAKE, timeout_s=1)
    with pytest.raises(RunnerError, match="timeout"):
        run_pandat(pbfx, FAKE, timeout_s=0)


def test_windows_executable_uses_start_process_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pandat_bridge.runner as runner

    pbfx = make_pbfx(tmp_path)
    executable = tmp_path / "Pandat.exe"
    executable.write_bytes(b"placeholder")
    monkeypatch.setattr(
        runner.shutil,
        "which",
        lambda name: r"C:\Tools\pwsh.exe" if name == "pwsh.exe" else None,
    )

    command = runner._start_process_command(
        pbfx,
        executable,
        pbfx.with_suffix(".stdout.log"),
        pbfx.with_suffix(".stderr.log"),
        pbfx.with_suffix(".launcher.json"),
        1,
    )

    assert Path(command[0]).name.lower() == "pwsh.exe"
    assert any(str(value).endswith("run_pandat_process.ps1") for value in command)


def test_windows_launcher_uses_configured_powershell_core(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pandat_bridge.runner as runner

    pbfx = make_pbfx(tmp_path)
    executable = tmp_path / "Pandat.exe"
    executable.write_bytes(b"placeholder")
    powershell = tmp_path / "pwsh.exe"
    powershell.write_bytes(b"placeholder")
    monkeypatch.setenv("PANDAT_POWERSHELL_EXE", str(powershell))
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)

    command = runner._start_process_command(
        pbfx,
        executable,
        pbfx.with_suffix(".stdout.log"),
        pbfx.with_suffix(".stderr.log"),
        pbfx.with_suffix(".launcher.json"),
        1,
    )

    assert Path(command[0]) == powershell


def test_windows_launcher_does_not_use_legacy_windows_powershell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pandat_bridge.runner as runner

    pbfx = make_pbfx(tmp_path)
    executable = tmp_path / "Pandat.exe"
    executable.write_bytes(b"placeholder")
    monkeypatch.delenv("PANDAT_POWERSHELL_EXE", raising=False)
    monkeypatch.setattr(
        runner.shutil,
        "which",
        lambda name: r"C:\Windows\powershell.exe" if name == "powershell.exe" else None,
    )

    with pytest.raises(RunnerError, match="PowerShell Core"):
        runner._start_process_command(
            pbfx,
            executable,
            pbfx.with_suffix(".stdout.log"),
            pbfx.with_suffix(".stderr.log"),
            pbfx.with_suffix(".launcher.json"),
            1,
        )


def _write_fake_executable_script(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _windows_process_exists(pid: int) -> bool:
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher contract")
def test_stderr_terminal_state_stops_the_started_child(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    pbfx = _write_fake_executable_script(
        tmp_path / "job.pbfx",
        "import os, sys, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "print('Failed to connect to HASP key', file=sys.stderr, flush=True)\n"
        "time.sleep(30)\n",
    )
    child_pid = 0
    try:
        outcome = run_pandat(pbfx, Path(sys.executable), timeout_s=5)
        child_pid = int(pid_file.read_text(encoding="utf-8"))

        assert outcome.error_code == "license_unavailable"
        assert outcome.pid == child_pid
        assert not _windows_process_exists(child_pid)
    finally:
        if child_pid and _windows_process_exists(child_pid):
            os.kill(child_pid, signal.SIGTERM)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher contract")
def test_windows_launcher_preserves_pbfx_names_with_spaces(tmp_path: Path) -> None:
    pbfx = _write_fake_executable_script(
        tmp_path / "job with space.pbfx",
        "from pathlib import Path\n"
        "Path(__file__).with_suffix('.result').write_text('<result />')\n"
        "print('Simulation is done with Success', flush=True)\n",
    )

    outcome = run_pandat(pbfx, Path(sys.executable), timeout_s=5)

    assert outcome.status == "success"
    assert outcome.result_path == pbfx.with_suffix(".result")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher contract")
def test_windows_launcher_preserves_native_exit_code(tmp_path: Path) -> None:
    pbfx = _write_fake_executable_script(tmp_path / "job.pbfx", "raise SystemExit(7)\n")

    outcome = run_pandat(pbfx, Path(sys.executable), timeout_s=5)

    assert outcome.error_code == "early_exit"
    assert outcome.message.endswith("7")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher contract")
def test_windows_launcher_timeout_stops_only_its_child(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    pbfx = _write_fake_executable_script(
        tmp_path / "job.pbfx",
        "import os, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(30)\n",
    )
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    child_pid = 0
    try:
        outcome = run_pandat(pbfx, Path(sys.executable), timeout_s=0.35)
        child_pid = int(pid_file.read_text(encoding="utf-8"))

        assert outcome.error_code == "timeout"
        assert outcome.pid == child_pid
        assert not _windows_process_exists(child_pid)
        assert unrelated.poll() is None
    finally:
        if child_pid and _windows_process_exists(child_pid):
            os.kill(child_pid, signal.SIGTERM)
        if unrelated.poll() is None:
            unrelated.terminate()
            unrelated.wait(timeout=5)


def test_windows_launcher_tolerates_natural_exit_during_cleanup() -> None:
    source = WINDOWS_LAUNCHER.read_text(encoding="utf-8")

    assert "catch [InvalidOperationException]" in source


def test_windows_launcher_writes_status_as_utf8_without_bom() -> None:
    source = WINDOWS_LAUNCHER.read_text(encoding="utf-8")

    assert "[Text.UTF8Encoding]::new($false)" in source
    assert "[IO.File]::WriteAllText" in source
