from __future__ import annotations

import json
from pathlib import Path

import pytest

from pandat_bridge.models import JobSpec
from pandat_bridge.payload import encode_job
from pandat_bridge.worker_cli import main
from test_models import c63_mapping


ROOT = Path(__file__).resolve().parents[1]
FAKE = Path(__file__).with_name("fake_pandat.py")
RESULT = Path(__file__).parent / "fixtures" / "native-line.result"
TEMPLATE = ROOT / "config" / "line-template.pbfx"


def worker_job() -> JobSpec:
    return JobSpec.from_mapping(
        c63_mapping(
            composition=[
                {"element": "Fe", "value": 50.0},
                {"element": "Ni", "value": 50.0},
            ]
        )
    )


def configure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mode: str, payload: str | None = None
) -> Path:
    database = tmp_path / "local.pdb"
    database.write_bytes(b"private-database-placeholder")
    artifact = tmp_path / "artifact"
    monkeypatch.setenv("PANDAT_JOB_PAYLOAD", payload or encode_job(worker_job()))
    monkeypatch.setenv("PANDAT_EXE", str(FAKE))
    monkeypatch.setenv("PANDAT_DATABASE_PATH", str(database))
    monkeypatch.setenv("PANDAT_TEMPLATE_PATH", str(TEMPLATE))
    monkeypatch.setenv("PANDAT_ARTIFACT_DIR", str(artifact))
    monkeypatch.setenv("PANDAT_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("FAKE_PANDAT_MODE", mode)
    monkeypatch.setenv("FAKE_PANDAT_RESULT_SOURCE", str(RESULT))
    return artifact


def test_worker_success_creates_complete_artifact_and_removes_workdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = configure(tmp_path, monkeypatch, mode="success")

    exit_code = main([])

    assert exit_code == 0
    status = json.loads((artifact / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "success"
    assert status["error_code"] is None
    assert list(artifact.glob("pandat-result-*.zip"))
    assert not (artifact / "_work").exists()
    assert not list(artifact.glob("*.pbfx"))


def test_worker_failure_still_writes_categorized_status_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = configure(tmp_path, monkeypatch, mode="unsupported")

    exit_code = main([])

    assert exit_code == 1
    status = json.loads((artifact / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["error_code"] == "unsupported_element"
    assert "Ta" in status["message"]
    assert (artifact / "pandat.stdout.log").is_file()
    assert (artifact / "pandat.stderr.log").is_file()
    assert not list(artifact.glob("*.zip"))
    assert not (artifact / "_work").exists()


def test_worker_invalid_payload_fails_without_starting_pandat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = configure(tmp_path, monkeypatch, mode="success", payload="not-base64")

    exit_code = main([])

    assert exit_code == 2
    status = json.loads((artifact / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["error_code"] == "validation_error"
    assert not (artifact / "pandat.stdout.log").exists()


def test_worker_requires_local_paths_without_echoing_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = configure(tmp_path, monkeypatch, mode="success")
    monkeypatch.delenv("PANDAT_DATABASE_PATH")

    exit_code = main([])

    assert exit_code == 2
    status_text = (artifact / "status.json").read_text(encoding="utf-8")
    assert "PANDAT_DATABASE_PATH" in status_text
    assert str(tmp_path) not in status_text
