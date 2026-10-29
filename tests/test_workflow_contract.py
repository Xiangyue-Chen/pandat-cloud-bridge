from __future__ import annotations

from pathlib import Path

import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "pandat-calculate.yml"


def load_workflow() -> dict[str, object]:
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_workflow_is_manual_only_and_requires_bounded_payload() -> None:
    workflow = load_workflow()
    assert set(workflow["on"]) == {"workflow_dispatch"}
    payload = workflow["on"]["workflow_dispatch"]["inputs"]["payload_b64"]
    assert payload["required"] == "true"
    assert payload["type"] == "string"


def test_workflow_uses_only_the_licensed_serial_windows_runner() -> None:
    workflow = load_workflow()
    assert workflow["concurrency"] == {
        "group": "pandat-local-singleton",
        "cancel-in-progress": "false",
    }
    job = workflow["jobs"]["calculate"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert job["runs-on"] == ["self-hosted", "Windows", "X64", "pandat-licensed"]
    assert workflow["permissions"] == {"contents": "read"}
    checkout = next(step for step in job["steps"] if step.get("uses") == "actions/checkout@v4")
    assert checkout["with"] == {"ref": "main"}


def test_payload_reaches_worker_only_through_environment() -> None:
    workflow = load_workflow()
    job = workflow["jobs"]["calculate"]
    assert job["env"]["PANDAT_JOB_PAYLOAD"] == "${{ inputs.payload_b64 }}"
    worker = next(step for step in job["steps"] if step.get("name") == "Run licensed Pandat worker")
    assert worker["run"] == "python -m pandat_bridge.worker_cli"
    assert "payload_b64" not in worker["run"]
    assert job["env"]["PYTHONPATH"] == "${{ github.workspace }}\\src"
    assert job["env"]["PANDAT_DATABASE_CATALOG"] == (
        "${{ github.workspace }}\\config\\databases.json"
    )
    assert "PANDAT_DATABASE_PATH" not in job["env"]


def test_workflow_uses_the_windows_powershell_available_on_the_runner() -> None:
    steps = load_workflow()["jobs"]["calculate"]["steps"]
    script_steps = [step for step in steps if "run" in step]

    assert script_steps
    assert {step["shell"] for step in script_steps} == {"powershell"}
    metadata = next(step for step in script_steps if step.get("id") == "meta")
    assert "Out-File -FilePath $env:GITHUB_OUTPUT -Encoding utf8 -Append" in metadata["run"]


def test_workflow_restores_catalog_blob_bytes_in_reused_windows_checkout() -> None:
    steps = load_workflow()["jobs"]["calculate"]["steps"]
    restore = next(step for step in steps if step.get("name") == "Restore catalog blob bytes")

    assert restore["shell"] == "powershell"
    assert "Remove-Item -LiteralPath $env:PANDAT_DATABASE_CATALOG -Force" in restore["run"]
    assert "git -c core.autocrlf=false checkout -- config/databases.json" in restore["run"]


def test_result_artifact_uploads_on_failure_and_expires_after_seven_days() -> None:
    workflow = load_workflow()
    steps = workflow["jobs"]["calculate"]["steps"]
    upload = next(step for step in steps if step.get("uses") == "actions/upload-artifact@v4")
    assert upload["if"] == "${{ always() }}"
    assert upload["with"]["name"] == "pandat-result-${{ steps.meta.outputs.job_id }}"
    assert upload["with"]["retention-days"] == "7"
    assert upload["with"]["if-no-files-found"] == "error"

