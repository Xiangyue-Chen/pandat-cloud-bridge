from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from streamlit.testing.v1 import AppTest

from pandat_bridge.github_api import RunnerState, WorkflowRun
from streamlit_app import (
    PAGE_TITLE,
    build_job_from_rows,
    fetch_current_artifact,
    runner_status_text,
    submit_job,
    verify_access_code,
)


ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_entrypoint_imports_without_test_path_bootstrap() -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, "-c", "import streamlit_app"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"


class FakeBroker:
    def __init__(self) -> None:
        self.dispatched = []

    def dispatch(self, job):
        self.dispatched.append(job)
        return WorkflowRun(987, "https://github.com/Xiangyue-Chen/pandat-cloud-bridge/actions/runs/987")

    def download_artifact(self, run_id: int, job_id: UUID) -> bytes:
        assert run_id == 987
        assert isinstance(job_id, UUID)
        return b"PK\x03\x04artifact"


def test_page_is_standalone_pandat_bridge_and_access_gated() -> None:
    app = AppTest.from_file(str(APP))
    app.run()

    assert "Pandat" in PAGE_TITLE
    assert "拉伸" not in PAGE_TITLE
    assert app.title[0].value == PAGE_TITLE
    assert any("访问码" in item.label for item in app.text_input)
    assert all(button.label != "提交计算" for button in app.button)


def test_access_code_uses_sha256_and_rejects_wrong_value() -> None:
    expected = hashlib.sha256("correct horse".encode("utf-8")).hexdigest()
    assert verify_access_code("correct horse", expected) is True
    assert verify_access_code("wrong", expected) is False
    assert verify_access_code("", expected) is False


def test_form_rows_build_valid_c63_job() -> None:
    rows = [
        {"元素": "Fe", "含量": 57.93},
        {"元素": "Co", "含量": 9.66},
        {"元素": "Ni", "含量": 26.28},
        {"元素": "Cr", "含量": 1.10},
        {"元素": "Ti", "含量": 4.98},
        {"元素": "B", "含量": 0.05},
        {"元素": "", "含量": None},
    ]

    job = build_job_from_rows(
        sample_name="C63(C9)",
        unit="at",
        rows=rows,
        temperature_start_c=25,
        temperature_end_c=1500,
        steps=100,
        pressure_atm=1,
    )

    assert job.sample_name == "C63(C9)"
    assert job.unit == "at"
    assert [entry.element for entry in job.composition] == ["B", "Co", "Cr", "Fe", "Ni", "Ti"]


def test_submit_stores_only_current_job_and_run_identifiers() -> None:
    session: dict[str, object] = {
        "authenticated": True,
        "old_result": b"old",
        "unrelated": "remove",
    }
    broker = FakeBroker()
    job = build_job_from_rows(
        "C63(C9)",
        "at",
        [{"元素": "Fe", "含量": 50}, {"元素": "Ni", "含量": 50}],
        25,
        1500,
        100,
        1,
    )

    run = submit_job(session, broker, job)

    assert run.run_id == 987
    assert broker.dispatched == [job]
    assert session == {
        "authenticated": True,
        "current_job_id": str(job.job_id),
        "current_run_id": 987,
        "current_run_url": run.html_url,
        "current_status": "queued",
        "current_conclusion": None,
    }


def test_runner_offline_message_is_actionable() -> None:
    assert "离线" in runner_status_text(RunnerState(False, False, None))
    assert "排队" in runner_status_text(RunnerState(False, False, None))
    assert "计算中" in runner_status_text(RunnerState(True, True, "PANDAT-WS"))
    assert "在线" in runner_status_text(RunnerState(True, False, "PANDAT-WS"))


def test_completed_artifact_is_bound_to_current_job_and_run() -> None:
    job = build_job_from_rows(
        "C63(C9)",
        "at",
        [{"元素": "Fe", "含量": 50}, {"元素": "Ni", "含量": 50}],
        25,
        1500,
        100,
        1,
    )
    session: dict[str, object] = {
        "current_job_id": str(job.job_id),
        "current_run_id": 987,
        "current_status": "completed",
        "current_conclusion": "success",
    }

    data, filename = fetch_current_artifact(session, FakeBroker())

    assert data == b"PK\x03\x04artifact"
    assert filename == f"pandat-result-{job.job_id}.zip"
