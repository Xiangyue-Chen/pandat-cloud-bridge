from __future__ import annotations

import re
import subprocess
import sys
import time
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
    match = re.search(r"(?m)^\d+:\s*(.+\.result)\.html\s*$", log)
    result = Path(match.group(1).strip()) if match else pbfx.with_suffix(".result")
    if not result.is_absolute():
        result = pbfx.parent / result
    if not result.is_file():
        return "failed", "missing_result", "Pandat reported success but result is missing", None
    if result.stat().st_mtime < started_wall - 2:
        return "failed", "stale_result", "Pandat result is stale", None
    return "success", None, "Pandat calculation completed", result, 


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
