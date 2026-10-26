from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from pandat_bridge.github_api import GitHubBroker
from pandat_bridge.payload import decode_job
from pandat_bridge.worker_cli import main as run_worker
from streamlit_app import build_job_from_rows, fetch_current_artifact, submit_job


ROOT = Path(__file__).resolve().parents[1]
FAKE_PANDAT = Path(__file__).with_name("fake_pandat.py")
TEMPLATE = ROOT / "config" / "line-template.pbfx"


class Response:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any] | None = None,
        *,
        content: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.headers = {"Content-Length": str(len(content))} if content else {}

    def json(self) -> dict[str, Any]:
        return self._payload


class EndToEndGitHubSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.dispatched_payload = ""
        self.artifact = b""

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        if method == "POST" and url.endswith("/dispatches"):
            self.dispatched_payload = kwargs["json"]["inputs"]["payload_b64"]
            return Response(
                200,
                {
                    "workflow_run_id": 4242,
                    "html_url": "https://github.example/actions/runs/4242",
                },
            )
        if method == "GET" and url.endswith("/actions/runs/4242/artifacts"):
            job = decode_job(self.dispatched_payload)
            return Response(
                200,
                {
                    "artifacts": [
                        {
                            "id": 73,
                            "name": f"pandat-result-{job.job_id}",
                            "expired": False,
                        }
                    ]
                },
            )
        if method == "GET" and url.endswith("/actions/artifacts/73/zip"):
            return Response(200, content=self.artifact)
        raise AssertionError(f"unexpected request: {method} {url}")


def c63_native_result(path: Path, bulk: dict[str, float]) -> None:
    components = "".join(
        f'<component name="{element}" weight="1" />' for element in bulk
    )
    state = "".join(
        f'<component name="{element}" x="{value}" />' for element, value in bulk.items()
    )
    points = []
    for temperature_k, phase in ((298.15, "Fcc"), (1000.0, "Fcc"), (1773.15, "Liquid")):
        points.append(
            "<point>"
            f"<statespace><T>{temperature_k}</T><P>101325</P>{state}</statespace>"
            '<property G="-1000" />'
            '<phasepoint in_equilibrium="true">'
            f'<phase name="{phase}" nth="0" /><property f="1" />'
            f"<statespace>{state}</statespace>"
            "</phasepoint>"
            "</point>"
        )
    path.write_text(
        "<result><section name=\"c63\"><components>"
        + components
        + "</components><line>"
        + "".join(points)
        + "</line></section></result>",
        encoding="utf-8",
    )


def github_artifact_zip(directory: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if path.is_file():
                archive.write(path, arcname=path.name)
    return buffer.getvalue()


def test_cloud_dispatch_local_worker_and_web_download_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = build_job_from_rows(
        "C63(C9)",
        "at",
        [
            {"元素": "Fe", "含量": 57.93},
            {"元素": "Co", "含量": 9.66},
            {"元素": "Ni", "含量": 26.28},
            {"元素": "Cr", "含量": 1.10},
            {"元素": "Ti", "含量": 4.97},
            {"元素": "B", "含量": 0.05},
        ],
        25.0,
        1500.0,
        201,
        1.0,
    )
    transport = EndToEndGitHubSession()
    broker = GitHubBroker(
        token="test-token",
        owner="owner",
        repo="pandat-cloud-bridge",
        workflow="pandat-calculate.yml",
        session=transport,
    )
    browser_session: dict[str, object] = {"authenticated": True}

    run = submit_job(browser_session, broker, job)

    received = decode_job(transport.dispatched_payload)
    assert received == job
    assert run.run_id == 4242

    database = tmp_path / "private.pdb"
    database.write_bytes(b"local-only-database-placeholder")
    native_result = tmp_path / "c63.result"
    c63_native_result(
        native_result,
        {entry.element: entry.value / 100.0 for entry in job.composition},
    )
    artifact_dir = tmp_path / "artifact"
    monkeypatch.setenv("PANDAT_JOB_PAYLOAD", transport.dispatched_payload)
    monkeypatch.setenv("PANDAT_EXE", str(FAKE_PANDAT))
    monkeypatch.setenv("PANDAT_DATABASE_PATH", str(database))
    monkeypatch.setenv("PANDAT_TEMPLATE_PATH", str(TEMPLATE))
    monkeypatch.setenv("PANDAT_ARTIFACT_DIR", str(artifact_dir))
    monkeypatch.setenv("PANDAT_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("FAKE_PANDAT_MODE", "success")
    monkeypatch.setenv("FAKE_PANDAT_RESULT_SOURCE", str(native_result))

    assert run_worker([]) == 0
    transport.artifact = github_artifact_zip(artifact_dir)
    browser_session["current_status"] = "completed"
    browser_session["current_conclusion"] = "success"

    downloaded, filename = fetch_current_artifact(browser_session, broker)

    assert filename == f"pandat-result-{job.job_id}.zip"
    with zipfile.ZipFile(io.BytesIO(downloaded)) as outer:
        names = outer.namelist()
        assert "metadata.json" in names
        assert "phase-diagram.png" in names
        assert "phase-fractions.csv" in names
        inner_name = f"pandat-result-{job.job_id}.zip"
        assert inner_name in names
        metadata = json.loads(outer.read("metadata.json"))
        assert metadata["job"]["job_id"] == str(job.job_id)
        assert metadata["job"]["temperature_start_c"] == 25.0
        assert metadata["job"]["temperature_end_c"] == 1500.0
        assert metadata["verification"]["point_count"] == 3
        assert metadata["verification"]["phase_names"] == ["Fcc", "Liquid"]
        with zipfile.ZipFile(io.BytesIO(outer.read(inner_name))) as inner:
            assert "metadata.json" in inner.namelist()
