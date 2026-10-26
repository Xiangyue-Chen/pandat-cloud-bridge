from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Sequence

from .models import JobValidationError
from .payload import decode_job
from .pbfx import PbfxError, build_pbfx
from .result import ResultValidationError, package_result
from .runner import RunOutcome, RunnerError, run_pandat


class WorkerConfigError(ValueError):
    """Raised when the licensed workstation is not configured."""


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    artifact_dir = Path(os.environ.get("PANDAT_ARTIFACT_DIR", "artifacts/current")).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    try:
        payload = os.environ.get("PANDAT_JOB_PAYLOAD")
        if not payload:
            raise WorkerConfigError("PANDAT_JOB_PAYLOAD is required")
        job = decode_job(payload)
        executable = _required_file("PANDAT_EXE")
        database = _required_file("PANDAT_DATABASE_PATH")
        template = _required_file("PANDAT_TEMPLATE_PATH")
        timeout = _timeout()
    except (WorkerConfigError, JobValidationError) as exc:
        _status(artifact_dir, "failed", "validation_error", str(exc))
        return 2

    run: RunOutcome | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="_work-", dir=artifact_dir) as temp:
            work = Path(temp)
            pbfx = build_pbfx(job, template, database, work / "job.pbfx")
            run = run_pandat(pbfx, executable, timeout)
            if run.status != "success" or run.result_path is None:
                _copy_logs(run, artifact_dir)
                _status(artifact_dir, run.status, run.error_code, run.message, run.seconds)
                return 1
            _copy_logs(run, artifact_dir)
            package_result(job, run.result_path, run, artifact_dir)
            return 0
    except ResultValidationError as exc:
        if run is not None:
            _copy_logs(run, artifact_dir)
        _status(artifact_dir, "failed", "result_validation_failed", str(exc), run.seconds if run else None)
        return 1
    except (PbfxError, RunnerError) as exc:
        _status(artifact_dir, "failed", "worker_error", _safe_message(exc))
        return 2
    except Exception as exc:  # keep an artifact for unexpected runner failures
        _status(artifact_dir, "failed", "internal_error", type(exc).__name__)
        return 2


def _required_file(key: str) -> Path:
    value = os.environ.get(key)
    if not value:
        raise WorkerConfigError(f"{key} is required")
    path = Path(value)
    if not path.is_file():
        raise WorkerConfigError(f"{key} does not point to a file")
    return path.resolve()


def _timeout() -> float:
    raw = os.environ.get("PANDAT_TIMEOUT_SECONDS", "300")
    try:
        value = float(raw)
    except ValueError as exc:
        raise WorkerConfigError("PANDAT_TIMEOUT_SECONDS must be numeric") from exc
    if not 1 <= value <= 7200:
        raise WorkerConfigError("PANDAT_TIMEOUT_SECONDS must be between 1 and 7200")
    return value


def _copy_logs(run: RunOutcome, artifact_dir: Path) -> None:
    if run.stdout_path.is_file():
        shutil.copyfile(run.stdout_path, artifact_dir / "pandat.stdout.log")
    if run.stderr_path.is_file():
        shutil.copyfile(run.stderr_path, artifact_dir / "pandat.stderr.log")


def _status(
    artifact_dir: Path,
    status: str,
    error_code: str | None,
    message: str,
    seconds: float | None = None,
) -> None:
    data: dict[str, object] = {
        "status": status,
        "error_code": error_code,
        "message": message,
    }
    if seconds is not None:
        data["seconds"] = seconds
    (artifact_dir / "status.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _safe_message(exc: Exception) -> str:
    text = str(exc)
    if ":" in text:
        return text.split(":", 1)[0]
    return text


if __name__ == "__main__":
    raise SystemExit(main())
