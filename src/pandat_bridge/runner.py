from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


class RunnerError(ValueError):
    """Raised before Pandat starts when local runner inputs are invalid."""


@dataclass(frozen=True, slots=True)
class RunOutcome:
    status: str
    error_code: str | None
    message: str
    result_path: Path | None
    stdout_path: Path
    stderr_path: Path
    seconds: float
    pid: int


def run_pandat(pbfx: Path, executable: Path, timeout_s: int | float) -> RunOutcome:
    pbfx = Path(pbfx)
    executable = Path(executable)
    if not pbfx.is_file():
        raise RunnerError(f"PBFX file not found: {pbfx}")
    if not executable.is_file():
        raise RunnerError(f"Pandat executable not found: {executable}")
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
        raise RunnerError("timeout must be positive")

    stdout_path = pbfx.with_suffix(".stdout.log")
    stderr_path = pbfx.with_suffix(".stderr.log")
    started_wall = time.time()
    started = time.monotonic()
    if sys.platform == "win32" and executable.suffix.lower() == ".exe":
        return _run_windows_executable(
            pbfx, executable, timeout_s, stdout_path, stderr_path, started_wall, started
        )

    command = (
        [sys.executable, str(executable), pbfx.name, "2"]
        if executable.suffix.lower() == ".py"
        else [str(executable), pbfx.name, "2"]
    )
    with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout, stderr_path.open(
        "w", encoding="utf-8", errors="replace"
    ) as stderr:
        process = subprocess.Popen(
            command,
            cwd=pbfx.parent,
            stdout=stdout,
            stderr=stderr,
            text=True,
        )
        outcome: tuple[str, str | None, str, Path | None] | None = None
        while outcome is None:
            stdout.flush()
            stderr.flush()
            log = _read_log(stdout_path) + "\n" + _read_log(stderr_path)
            outcome = _classify_log(log, pbfx, started_wall)
            if outcome is not None:
                break
            exit_code = process.poll()
            if exit_code is not None:
                outcome = ("failed", "early_exit", f"Pandat exited before success: {exit_code}", None)
                break
            if time.monotonic() - started >= timeout_s:
                outcome = ("failed", "timeout", f"Pandat calculation timeout after {timeout_s:g} s", None)
                break
            time.sleep(0.025)
        _stop_child(process)

    status, error_code, message, result_path = outcome
    return RunOutcome(
        status=status,
        error_code=error_code,
        message=message,
        result_path=result_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        seconds=round(time.monotonic() - started, 3),
        pid=process.pid,
    )


def _run_windows_executable(
    pbfx: Path,
    executable: Path,
    timeout_s: int | float,
    stdout_path: Path,
    stderr_path: Path,
    started_wall: float,
    started: float,
) -> RunOutcome:
    status_path = pbfx.with_suffix(".launcher.json")
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    status_path.unlink(missing_ok=True)
    command = _start_process_command(
        pbfx, executable, stdout_path, stderr_path, status_path, timeout_s
    )
    launcher = subprocess.Popen(
        command,
        cwd=pbfx.parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    launcher_exit = launcher.wait()
    status = _read_launcher_status(status_path)
    child_pid = status.get("pid")
    child_exit = status.get("exit_code")
    timed_out = status.get("timed_out") is True
    if not isinstance(child_pid, int) or child_pid <= 0:
        raise RunnerError("Pandat launcher did not report a valid child process")

    log = _read_log(stdout_path) + "\n" + _read_log(stderr_path)
    outcome = _classify_log(log, pbfx, started_wall)
    if outcome is None and timed_out:
        outcome = (
            "failed",
            "timeout",
            f"Pandat calculation timeout after {timeout_s:g} s",
            None,
        )
    if outcome is None:
        exit_code = child_exit if isinstance(child_exit, int) else launcher_exit
        outcome = (
            "failed",
            "early_exit",
            f"Pandat exited before success: {exit_code}",
            None,
        )

    run_status, error_code, message, result_path = outcome
    return RunOutcome(
        status=run_status,
        error_code=error_code,
        message=message,
        result_path=result_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        seconds=round(time.monotonic() - started, 3),
        pid=child_pid,
    )


def _start_process_command(
    pbfx: Path,
    executable: Path,
    stdout_path: Path,
    stderr_path: Path,
    status_path: Path,
    timeout_s: int | float,
) -> list[str]:
    launcher = Path(__file__).resolve().parents[2] / "scripts" / "run_pandat_process.ps1"
    if not launcher.is_file():
        raise RunnerError(f"Pandat process launcher not found: {launcher}")
    configured_powershell = os.environ.get("PANDAT_POWERSHELL_EXE", "").strip()
    if configured_powershell:
        configured_path = Path(configured_powershell)
        if not configured_path.is_file():
            raise RunnerError("Configured PowerShell Core executable not found")
        powershell = str(configured_path)
    else:
        powershell = shutil.which("pwsh.exe")
    if not powershell:
        raise RunnerError("PowerShell Core executable not found")
    return [
        powershell,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(launcher),
        "-Executable",
        str(executable),
        "-Pbfx",
        str(pbfx),
        "-StdoutPath",
        str(stdout_path),
        "-StderrPath",
        str(stderr_path),
        "-StatusPath",
        str(status_path),
        "-TimeoutSeconds",
        str(float(timeout_s)),
    ]


def _read_launcher_status(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunnerError("Pandat launcher status is missing or invalid") from exc
    if not isinstance(value, dict):
        raise RunnerError("Pandat launcher status is missing or invalid")
    return value


def _classify_log(
    log: str, pbfx: Path, started_wall: float
) -> tuple[str, str | None, str, Path | None] | None:
    if re.search(r"not activated|Failed to connect to HASP", log, flags=re.IGNORECASE):
        return "failed", "license_unavailable", "Pandat license is unavailable", None
    unsupported = re.search(r"Database does not have component\s+(\w+)", log, flags=re.IGNORECASE)
    if unsupported:
        element = unsupported.group(1)
        return "failed", "unsupported_element", f"Database does not support element {element}", None
    if re.search(r"Simulation done with Failure", log, flags=re.IGNORECASE):
        return "failed", "pandat_failure", "Pandat reported calculation failure", None
    if "Simulation is done with Success" not in log:
        return None
    result_match = re.search(r"(?m)^\d+:\s*(.+\.result)\.html\s*$", log)
    table_match = re.search(r"(?m)^\d+:\s*(.+\.dat\.table)\s*$", log)
    if result_match:
        result = Path(result_match.group(1).strip())
    elif table_match:
        result, stale = _native_result_from_table(
            Path(table_match.group(1).strip()).parent, pbfx, started_wall
        )
        if result is None:
            code = "stale_result" if stale else "missing_result"
            message = "Pandat result is stale" if stale else "Pandat reported success but result is missing"
            return "failed", code, message, None
    else:
        result = pbfx.with_suffix(".result")
    if not result.is_absolute():
        result = pbfx.parent / result
    if not result.is_file():
        return "failed", "missing_result", "Pandat reported success but result is missing", None
    if result.stat().st_mtime < started_wall - 2:
        return "failed", "stale_result", "Pandat result is stale", None
    return "success", None, "Pandat calculation completed", result, 


def _native_result_from_table(
    output_dir: Path, pbfx: Path, started_wall: float
) -> tuple[Path | None, bool]:
    if not output_dir.is_dir():
        return None, False
    try:
        expected_name = ET.parse(pbfx).getroot().find("calculation").get("name")
    except (AttributeError, ET.ParseError, OSError):
        return None, False
    stale_match = False
    for candidate in sorted(output_dir.glob("*.result"), key=lambda path: path.stat().st_mtime, reverse=True):
        try:
            section = ET.parse(candidate).getroot().find("section")
        except (ET.ParseError, OSError):
            continue
        if section is not None and section.get("name") == expected_name:
            if candidate.stat().st_mtime < started_wall:
                stale_match = True
                continue
            return candidate, False
    return None, stale_match


def _read_log(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _stop_child(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
