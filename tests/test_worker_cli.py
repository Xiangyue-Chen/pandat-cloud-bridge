from __future__ import annotations

import json
import hashlib
import zipfile
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


def worker_job(
    *, catalog_digest: str | None = None, composition: list[dict[str, object]] | None = None
) -> JobSpec:
    overrides: dict[str, object] = {
        "composition": composition
        or [
            {"element": "Fe", "value": 50.0},
            {"element": "Ni", "value": 50.0},
        ]
    }
    if catalog_digest is not None:
        overrides.update(
            schema_version=2,
            database_id="test-database",
            catalog_digest=catalog_digest,
        )
    return JobSpec.from_mapping(c63_mapping(**overrides))


def write_catalog(
    path: Path, database: Path, *, elements: list[str] | None = None
) -> str:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-10-28",
                "source": "test",
                "databases": [
                    {
                        "id": "test-database",
                        "display_name": "Test Database",
                        "format": "pdb",
                        "file_path": str(database.resolve()),
                        "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
                        "elements": elements or ["Fe", "Ni"],
                        "enabled": True,
                        "default": True,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def configure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mode: str, payload: str | None = None
) -> tuple[Path, Path, str, Path]:
    database = tmp_path / "local.pdb"
    database.write_bytes(b"private-database-placeholder")
    catalog = tmp_path / "databases.json"
    digest = write_catalog(catalog, database)
    artifact = tmp_path / "artifact"
    monkeypatch.setenv(
        "PANDAT_JOB_PAYLOAD", payload or encode_job(worker_job(catalog_digest=digest))
    )
    monkeypatch.setenv("PANDAT_EXE", str(FAKE))
    monkeypatch.setenv("PANDAT_DATABASE_CATALOG", str(catalog))
    monkeypatch.setenv("PANDAT_TEMPLATE_PATH", str(TEMPLATE))
    monkeypatch.setenv("PANDAT_ARTIFACT_DIR", str(artifact))
    monkeypatch.setenv("PANDAT_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("FAKE_PANDAT_MODE", mode)
    monkeypatch.setenv("FAKE_PANDAT_RESULT_SOURCE", str(RESULT))
    return artifact, catalog, digest, database


def test_worker_success_creates_complete_artifact_and_removes_workdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, _, _, _ = configure(tmp_path, monkeypatch, mode="success")

    exit_code = main([])

    assert exit_code == 0
    status = json.loads((artifact / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "success"
    assert status["error_code"] is None
    archive = next(iter(artifact.glob("pandat-result-*.zip")))
    assert (artifact / "pandat.stdout.log").is_file()
    assert (artifact / "pandat.stderr.log").is_file()
    with zipfile.ZipFile(archive) as bundle:
        assert "pandat.stdout.log" in bundle.namelist()
        assert "pandat.stderr.log" in bundle.namelist()
    assert not (artifact / "_work").exists()
    assert not list(artifact.glob("*.pbfx"))


def test_worker_failure_still_writes_categorized_status_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, _, _, _ = configure(tmp_path, monkeypatch, mode="unsupported")

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
    artifact, _, _, _ = configure(tmp_path, monkeypatch, mode="success", payload="not-base64")

    exit_code = main([])

    assert exit_code == 2
    status = json.loads((artifact / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["error_code"] == "validation_error"
    assert not (artifact / "pandat.stdout.log").exists()


def test_worker_requires_local_paths_without_echoing_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, _, _, _ = configure(tmp_path, monkeypatch, mode="success")
    monkeypatch.delenv("PANDAT_DATABASE_CATALOG")

    exit_code = main([])

    assert exit_code == 2
    status_text = (artifact / "status.json").read_text(encoding="utf-8")
    assert "PANDAT_DATABASE_CATALOG" in status_text
    assert str(tmp_path) not in status_text


def test_worker_resolves_only_registered_database_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, _, _, _ = configure(tmp_path, monkeypatch, mode="success")
    monkeypatch.setenv("PANDAT_DATABASE_PATH", str(tmp_path / "client-selected.pdb"))

    assert main([]) == 0
    metadata = json.loads((artifact / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["database"]["id"] == "test-database"
    assert "file_path" not in metadata["database"]


def test_worker_rejects_digest_change_before_pandat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, _, _, _ = configure(tmp_path, monkeypatch, mode="success")
    monkeypatch.setenv(
        "PANDAT_JOB_PAYLOAD", encode_job(worker_job(catalog_digest="f" * 64))
    )

    assert main([]) == 2
    status = json.loads((artifact / "status.json").read_text(encoding="utf-8"))
    assert status["error_code"] == "catalog_changed"
    assert not (artifact / "pandat.stdout.log").exists()


def test_worker_rejects_unsupported_element_before_pandat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, _, digest, _ = configure(tmp_path, monkeypatch, mode="success")
    job = worker_job(
        catalog_digest=digest,
        composition=[
            {"element": "Fe", "value": 50.0},
            {"element": "Ta", "value": 50.0},
        ],
    )
    monkeypatch.setenv("PANDAT_JOB_PAYLOAD", encode_job(job))

    assert main([]) == 2
    status = json.loads((artifact / "status.json").read_text(encoding="utf-8"))
    assert status["error_code"] == "unsupported_element"
    assert "Ta" in status["message"]
    assert not (artifact / "pandat.stdout.log").exists()


def test_worker_hides_missing_registered_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, _, _, database = configure(tmp_path, monkeypatch, mode="success")
    database.unlink()

    assert main([]) == 2
    status_text = (artifact / "status.json").read_text(encoding="utf-8")
    assert json.loads(status_text)["error_code"] == "database_unavailable"
    assert str(tmp_path) not in status_text
