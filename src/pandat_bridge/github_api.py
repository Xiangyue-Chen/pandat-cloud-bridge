from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import requests

from .models import JobSpec
from .payload import encode_job


API_ROOT = "https://api.github.com"
MAX_ARTIFACT_BYTES = 100 * 1024 * 1024


class BrokerError(RuntimeError):
    """A safe, user-displayable GitHub broker failure."""


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    run_id: int
    html_url: str


@dataclass(frozen=True, slots=True)
class RunState:
    run_id: int
    status: str
    conclusion: str | None
    html_url: str


@dataclass(frozen=True, slots=True)
class RunnerState:
    online: bool
    busy: bool
    name: str | None


class GitHubBroker:
    def __init__(
        self,
        *,
        token: str,
        owner: str,
        repo: str,
        workflow: str,
        ref: str = "main",
        session: requests.Session | Any | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        if not all(isinstance(value, str) and value.strip() for value in (token, owner, repo, workflow, ref)):
            raise BrokerError("GitHub broker configuration is incomplete")
        self.owner = owner
        self.repo = repo
        self.workflow = workflow
        self.ref = ref
        self.timeout_s = timeout_s
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2026-03-10",
                "User-Agent": "pandat-cloud-bridge/0.1",
            }
        )

    @property
    def repo_api(self) -> str:
        return f"{API_ROOT}/repos/{self.owner}/{self.repo}"

    def dispatch(self, job: JobSpec) -> WorkflowRun:
        response = self._request(
            "POST",
            f"{self.repo_api}/actions/workflows/{self.workflow}/dispatches",
            json={"ref": self.ref, "inputs": {"payload_b64": encode_job(job)}},
        )
        if response.status_code == 200:
            data = self._json_object(response)
            try:
                return WorkflowRun(int(data["workflow_run_id"]), str(data["html_url"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise BrokerError("GitHub dispatch response did not include a workflow run") from exc
        if response.status_code == 204:
            listing = self._request(
                "GET",
                f"{self.repo_api}/actions/workflows/{self.workflow}/runs",
                params={"event": "workflow_dispatch", "branch": self.ref, "per_page": 10},
            )
            runs = self._json_object(listing).get("workflow_runs")
            if not isinstance(runs, list) or not runs:
                raise BrokerError("GitHub accepted the job but its workflow run was not found")
            latest = runs[0]
            if not isinstance(latest, dict):
                raise BrokerError("GitHub workflow run response is malformed")
            try:
                return WorkflowRun(int(latest["id"]), str(latest["html_url"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise BrokerError("GitHub workflow run response is malformed") from exc
        raise BrokerError(f"GitHub dispatch returned HTTP {response.status_code}")

    def get_run(self, run_id: int) -> RunState:
        response = self._request("GET", f"{self.repo_api}/actions/runs/{int(run_id)}")
        data = self._json_object(response)
        try:
            conclusion = data.get("conclusion")
            return RunState(
                run_id=int(data["id"]),
                status=str(data["status"]),
                conclusion=None if conclusion is None else str(conclusion),
                html_url=str(data["html_url"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BrokerError("GitHub workflow state response is malformed") from exc

    def get_runner_state(self, label: str = "pandat-licensed") -> RunnerState:
        response = self._request("GET", f"{self.repo_api}/actions/runners", params={"per_page": 100})
        runners = self._json_object(response).get("runners")
        if not isinstance(runners, list):
            raise BrokerError("GitHub runner response is malformed")
        for runner in runners:
            if not isinstance(runner, dict):
                continue
            labels = runner.get("labels")
            names = {
                item.get("name") for item in labels if isinstance(item, dict)
            } if isinstance(labels, list) else set()
            if label in names and runner.get("status") == "online":
                return RunnerState(True, bool(runner.get("busy")), str(runner.get("name")))
        return RunnerState(False, False, None)

    def download_artifact(self, run_id: int, job_id: UUID) -> bytes:
        response = self._request(
            "GET", f"{self.repo_api}/actions/runs/{int(run_id)}/artifacts", params={"per_page": 100}
        )
        artifacts = self._json_object(response).get("artifacts")
        if not isinstance(artifacts, list):
            raise BrokerError("GitHub artifact response is malformed")
        expected = f"pandat-result-{job_id}"
        match = next(
            (item for item in artifacts if isinstance(item, dict) and item.get("name") == expected),
            None,
        )
        if match is None:
            raise BrokerError("result artifact was not found for this job")
        if match.get("expired"):
            raise BrokerError("result artifact has expired")
        try:
            artifact_id = int(match["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BrokerError("result artifact identifier is invalid") from exc
        archive = self._request(
            "GET", f"{self.repo_api}/actions/artifacts/{artifact_id}/zip", allow_redirects=True
        )
        headers = archive.headers or {}
        try:
            announced = int(headers.get("Content-Length", "0"))
        except ValueError:
            announced = 0
        if announced > MAX_ARTIFACT_BYTES or len(archive.content) > MAX_ARTIFACT_BYTES:
            raise BrokerError("result artifact is too large")
        return bytes(archive.content)

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", self.timeout_s)
        try:
            response = self.session.request(method, url, **kwargs)
        except requests.Timeout as exc:
            raise BrokerError("GitHub API timeout") from exc
        except requests.RequestException as exc:
            raise BrokerError("GitHub API network error") from exc
        headers = response.headers or {}
        if response.status_code == 401:
            raise BrokerError("GitHub authentication failed")
        if response.status_code == 429 or (
            response.status_code == 403 and headers.get("X-RateLimit-Remaining") == "0"
        ):
            raise BrokerError("GitHub API rate limit reached")
        if response.status_code == 403:
            raise BrokerError("GitHub token does not have the required permission")
        if response.status_code >= 400:
            raise BrokerError(f"GitHub API returned HTTP {response.status_code}")
        return response

    @staticmethod
    def _json_object(response: Any) -> dict[str, Any]:
        try:
            value = response.json()
        except (ValueError, TypeError) as exc:
            raise BrokerError("GitHub API returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise BrokerError("GitHub API returned invalid JSON")
        return value
