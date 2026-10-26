from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import requests

from pandat_bridge.github_api import BrokerError, GitHubBroker
from pandat_bridge.models import JobSpec
from test_models import c63_mapping


@dataclass
class FakeResponse:
    status_code: int
    payload: object | None = None
    content: bytes = b""
    headers: dict[str, str] | None = None
    text: str = ""

    def json(self) -> object:
        if self.payload is None:
            raise ValueError("no json")
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class FakeSession:
    def __init__(self, *responses: FakeResponse | Exception) -> None:
        self.responses = list(responses)
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def broker(session: FakeSession) -> GitHubBroker:
    return GitHubBroker(
        token="secret-token-must-not-leak",
        owner="Xiangyue-Chen",
        repo="pandat-cloud-bridge",
        workflow="pandat-calculate.yml",
        ref="main",
        session=session,
    )


def job() -> JobSpec:
    return JobSpec.from_mapping(c63_mapping())


def test_dispatch_uses_server_side_payload_and_returned_run_id() -> None:
    session = FakeSession(
        FakeResponse(
            200,
            {
                "workflow_run_id": 321,
                "run_url": "https://api.github.com/runs/321",
                "html_url": "https://github.com/runs/321",
            },
        )
    )

    run = broker(session).dispatch(job())

    assert run.run_id == 321
    assert run.html_url == "https://github.com/runs/321"
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url.endswith("/actions/workflows/pandat-calculate.yml/dispatches")
    assert kwargs["json"]["ref"] == "main"
    assert set(kwargs["json"]["inputs"]) == {"payload_b64"}
    assert "secret-token-must-not-leak" not in repr(session.calls)


def test_dispatch_204_falls_back_to_newest_workflow_dispatch_run() -> None:
    session = FakeSession(
        FakeResponse(204),
        FakeResponse(
            200,
            {
                "workflow_runs": [
                    {
                        "id": 654,
                        "event": "workflow_dispatch",
                        "status": "queued",
                        "conclusion": None,
                        "html_url": "https://github.com/runs/654",
                        "created_at": "2026-10-26T12:00:00Z",
                    }
                ]
            },
        ),
    )

    run = broker(session).dispatch(job())

    assert run.run_id == 654
    assert session.calls[1][0] == "GET"
    assert session.calls[1][2]["params"]["event"] == "workflow_dispatch"


@pytest.mark.parametrize(
    ("payload", "status", "conclusion"),
    [
        ({"id": 1, "status": "queued", "conclusion": None, "html_url": "u"}, "queued", None),
        (
            {"id": 1, "status": "in_progress", "conclusion": None, "html_url": "u"},
            "in_progress",
            None,
        ),
        (
            {"id": 1, "status": "completed", "conclusion": "success", "html_url": "u"},
            "completed",
            "success",
        ),
    ],
)
def test_get_run_preserves_github_state(
    payload: dict[str, object], status: str, conclusion: str | None
) -> None:
    state = broker(FakeSession(FakeResponse(200, payload))).get_run(1)
    assert state.status == status
    assert state.conclusion == conclusion


def test_runner_state_matches_required_label_and_busy_flag() -> None:
    session = FakeSession(
        FakeResponse(
            200,
            {
                "total_count": 2,
                "runners": [
                    {
                        "id": 1,
                        "name": "other",
                        "os": "Windows",
                        "status": "online",
                        "busy": False,
                        "labels": [{"name": "self-hosted"}],
                    },
                    {
                        "id": 2,
                        "name": "PANDAT-WS",
                        "os": "Windows",
                        "status": "online",
                        "busy": True,
                        "labels": [{"name": "self-hosted"}, {"name": "pandat-licensed"}],
                    },
                ],
            },
        )
    )
    state = broker(session).get_runner_state("pandat-licensed")
    assert state.online is True
    assert state.busy is True
    assert state.name == "PANDAT-WS"


def test_runner_state_reports_offline_when_no_matching_online_runner() -> None:
    session = FakeSession(FakeResponse(200, {"total_count": 0, "runners": []}))
    state = broker(session).get_runner_state("pandat-licensed")
    assert state.online is False
    assert state.busy is False
    assert state.name is None


def test_downloads_only_exact_nonexpired_job_artifact() -> None:
    current = job()
    archive = b"PK\x03\x04payload"
    session = FakeSession(
        FakeResponse(
            200,
            {
                "total_count": 2,
                "artifacts": [
                    {"id": 10, "name": "other", "expired": False},
                    {"id": 11, "name": f"pandat-result-{current.job_id}", "expired": False},
                ],
            },
        ),
        FakeResponse(200, content=archive, headers={"Content-Length": str(len(archive))}),
    )

    assert broker(session).download_artifact(99, current.job_id) == archive
    assert session.calls[1][1].endswith("/actions/artifacts/11/zip")


@pytest.mark.parametrize(
    "artifacts",
    [
        [],
        [{"id": 1, "name": "pandat-result-wrong", "expired": False}],
        [{"id": 1, "name": "MATCH", "expired": True}],
    ],
)
def test_rejects_absent_mismatched_or_expired_artifacts(artifacts: list[dict[str, object]]) -> None:
    current = job()
    if artifacts and artifacts[0]["name"] == "MATCH":
        artifacts[0]["name"] = f"pandat-result-{current.job_id}"
    session = FakeSession(FakeResponse(200, {"total_count": len(artifacts), "artifacts": artifacts}))
    with pytest.raises(BrokerError, match="artifact"):
        broker(session).download_artifact(1, current.job_id)


def test_rejects_oversized_artifact_from_header_or_body() -> None:
    current = job()
    listing = FakeResponse(
        200,
        {
            "total_count": 1,
            "artifacts": [
                {"id": 11, "name": f"pandat-result-{current.job_id}", "expired": False}
            ],
        },
    )
    too_large = 100 * 1024 * 1024 + 1
    with pytest.raises(BrokerError, match="too large"):
        broker(
            FakeSession(listing, FakeResponse(200, content=b"", headers={"Content-Length": str(too_large)}))
        ).download_artifact(1, current.job_id)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (FakeResponse(401, text="bad credentials"), "authentication"),
        (FakeResponse(403, headers={"X-RateLimit-Remaining": "0"}), "rate limit"),
        (FakeResponse(429), "rate limit"),
    ],
)
def test_api_errors_are_classified_without_leaking_token(
    response: FakeResponse, message: str
) -> None:
    with pytest.raises(BrokerError, match=message) as caught:
        broker(FakeSession(response)).get_run(1)
    assert "secret-token-must-not-leak" not in str(caught.value)


def test_network_timeout_is_classified() -> None:
    with pytest.raises(BrokerError, match="timeout"):
        broker(FakeSession(requests.Timeout("contains secret-token-must-not-leak"))).get_run(1)
