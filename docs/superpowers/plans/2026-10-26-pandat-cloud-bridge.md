# Pandat Cloud Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a separate Streamlit website that submits validated Pandat line-calculation jobs to a licensed Windows workstation through a private GitHub Actions self-hosted runner and returns audited result artifacts.

**Architecture:** Streamlit calls GitHub's workflow-dispatch API from the server using secrets. A repository-scoped Windows runner with the `pandat-licensed` label receives one job at a time, validates the same payload again, generates a PBFX from a sanitized line template, invokes `D:\bin\Pandat.exe <job.pbfx> 2`, verifies the native result, and uploads a downloadable artifact. The workstation initiates all network traffic; no local port is exposed.

**Tech Stack:** Python 3.12, Streamlit, requests, matplotlib, pytest, GitHub Actions, Windows PowerShell, Pandat 2024 batch mode

**Spec:** `docs/superpowers/specs/2026-10-26-pandat-cloud-bridge-design.md`

## Global Constraints

- This is a new independent repository and must not import from or deploy inside `cxy-tensile-cureve`.
- The Pandat executable, database, license information and GitHub token stay outside Git.
- The web tier never accepts arbitrary commands, paths, PBFX files, or scripts.
- Only `workflow_dispatch` may reach the self-hosted runner; no `push` or `pull_request` trigger is allowed.
- A single concurrency group serializes licensed Pandat work.
- User payloads are validated on both the web and runner sides and are passed through environment variables, never shell interpolation.
- Result claims are equilibrium predictions; phase fractions are not experimental guarantees.
- Default calculation conditions are 25–1500 ℃, 1 atm, 100 steps, with upload/result retention delegated to GitHub Actions artifacts for 7 days.

## Review Focus

- Malformed or oversized base64/JSON payload must fail before creating a job directory or starting a process; Task 1 adds bounded-decoding tests.
- Composition values containing NaN, infinity, negatives, duplicates, unsupported symbols, or totals outside 99.9–100.1 must be rejected identically in web and worker; Task 1 adds parameterized validation tests.
- User-controlled sample names must not affect paths, shell arguments, XML structure, or Matplotlib math parsing; Tasks 1 and 2 add sanitization and literal-render tests.
- Pandat success text paired with a stale/missing result, early exit, license failure, database element failure, or timeout must produce distinct status codes and terminate only the child PID; Task 2 adds fake-process tests.
- Runner offline, queued, in-progress, completed-without-artifact, expired artifact, API rate limit, and unauthorized token states must be distinguishable in the UI; Task 3 adds mocked GitHub API tests.

---

## File Structure

- `src/pandat_bridge/models.py`: job dataclasses, element allowlist, validation, normalization and safe identifiers.
- `src/pandat_bridge/payload.py`: bounded canonical JSON/base64 serialization shared by web and worker.
- `src/pandat_bridge/pbfx.py`: sanitized template loading and deterministic line-job PBFX generation.
- `src/pandat_bridge/runner.py`: Pandat child-process lifecycle, log classification, timeout and native result discovery.
- `src/pandat_bridge/result.py`: native result parsing, numerical checks, plots/tables/metadata and ZIP packaging.
- `src/pandat_bridge/github_api.py`: workflow dispatch, run status, runner status and artifact download client.
- `src/pandat_bridge/worker_cli.py`: runner entry point that consumes one validated payload and writes one artifact directory.
- `streamlit_app.py`: independent access-controlled web submission/status/download UI.
- `.github/workflows/pandat-calculate.yml`: dispatch-only, single-concurrency workflow for the licensed runner.
- `config/line-template.pbfx`: sanitized native line template with no real database path.
- `scripts/check_local.ps1`: read-only workstation readiness check.
- `scripts/start_runner.ps1`: validates local environment and starts an already configured GitHub runner interactively.
- `tests/`: unit, integration and Streamlit smoke tests with fake Pandat fixtures.
- `.streamlit/secrets.example.toml`, `.env.example`, `README.md`: deployment and local-runner setup without secrets.

### Task 1: Job contract and bounded payload

**Files:**
- Create: `pyproject.toml`
- Create: `src/pandat_bridge/__init__.py`
- Create: `src/pandat_bridge/models.py`
- Create: `src/pandat_bridge/payload.py`
- Test: `tests/test_models.py`
- Test: `tests/test_payload.py`

**Interfaces:**
- Consumes: raw form fields or workflow `payload_b64` string.
- Produces: `JobSpec.from_mapping(data: Mapping[str, object]) -> JobSpec`, `encode_job(job: JobSpec) -> str`, `decode_job(value: str, max_bytes: int = 16_384) -> JobSpec`, and `JobSpec.to_dict() -> dict[str, object]`.

- [ ] **Step 1: Write failing composition and range validation tests**

Cover valid C63(C9), at.% and wt.%, normalization, unknown/duplicate symbols, non-finite/negative values, totals outside 99.9–100.1, unsafe sample names, start ≥ end, temperatures outside -273.15–3000 ℃, steps outside 2–2000, and pressure outside 0.000001–10000 atm.

- [ ] **Step 2: Run the model tests and verify they fail because the package does not exist**

Run: `python -m pytest tests/test_models.py -q`
Expected: FAIL with `ModuleNotFoundError: pandat_bridge`.

- [ ] **Step 3: Implement immutable `CompositionEntry` and `JobSpec` validation**

Use an explicit periodic-table symbol allowlist, normalize accepted totals to 100, retain the submitted total, generate a filesystem-safe slug independently from the display name, and keep `job_id` as a UUID.

- [ ] **Step 4: Write failing canonical payload tests**

Assert round-trip equality, deterministic encoding, invalid base64, non-UTF-8, invalid JSON, arrays instead of objects, encoded input over 32 KiB, decoded input over 16 KiB, and unknown top-level keys.

- [ ] **Step 5: Implement bounded URL-safe base64 payload serialization**

Decode with strict validation before JSON parsing and route the mapping back through `JobSpec.from_mapping`.

- [ ] **Step 6: Run Task 1 tests**

Run: `python -m pytest tests/test_models.py tests/test_payload.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/pandat_bridge tests/test_models.py tests/test_payload.py
git commit -m "Build validated Pandat job contract"
```

### Task 2: PBFX generation, Pandat execution and result artifact

**Files:**
- Create: `config/line-template.pbfx`
- Create: `src/pandat_bridge/pbfx.py`
- Create: `src/pandat_bridge/runner.py`
- Create: `src/pandat_bridge/result.py`
- Create: `src/pandat_bridge/worker_cli.py`
- Create: `tests/fixtures/native-line.result`
- Create: `tests/fake_pandat.py`
- Test: `tests/test_pbfx.py`
- Test: `tests/test_runner.py`
- Test: `tests/test_result.py`
- Test: `tests/test_worker_cli.py`

**Interfaces:**
- Consumes: Task 1 `JobSpec`, local `PANDAT_EXE`, `PANDAT_DATABASE_PATH`, sanitized template, and isolated job directory.
- Produces: `build_pbfx(job: JobSpec, template: Path, database: Path, destination: Path) -> Path`, `run_pandat(pbfx: Path, executable: Path, timeout_s: int) -> RunOutcome`, `package_result(job: JobSpec, native_result: Path, run: RunOutcome, output_dir: Path) -> Path`, and `worker_cli.main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Copy and sanitize the validated native line template**

Replace the database path, calculation name and output paths with inert placeholders; confirm the original local template and database hashes are not embedded.

- [ ] **Step 2: Write failing deterministic PBFX tests**

Assert units, sorted selected elements, normalized values, 25/1500 ℃ endpoints, pressure, step count, escaped sample text, output table name, placeholder replacement, and rejection of malformed templates.

- [ ] **Step 3: Implement `build_pbfx` with XML APIs only**

Never construct XML by text substitution; modify the known calculation nodes and write UTF-8.

- [ ] **Step 4: Write fake-Pandat lifecycle tests**

The fake executable modes cover success, license error, unsupported element, native failure, early exit, missing result, stale result and timeout. Assert the worker never terminates unrelated PIDs.

- [ ] **Step 5: Implement `run_pandat` and log classification**

Start one child with redirected logs, track its exact PID, poll for native success/failure markers, verify result freshness, and terminate only that PID on timeout or completion.

- [ ] **Step 6: Write failing native result and artifact tests**

Assert endpoint/pressure checks, phase/composition mass balance, duplicate-temperature retention policy, literal sample labels, raw native file preservation, PNG/PDF/CSV/JSON/status outputs, and ZIP exclusion of absolute local paths.

- [ ] **Step 7: Implement result parsing, verification, plotting and packaging**

Reuse the validated native-result concepts from the earlier local Pandat audit, but keep this repository independent and retain original phase names without smoothing or merging.

- [ ] **Step 8: Write and implement worker CLI integration tests**

Pass `PANDAT_JOB_PAYLOAD` through the environment to a fake Pandat run and assert success/failure always creates a bounded artifact directory with `status.json`.

- [ ] **Step 9: Run Task 2 tests**

Run: `python -m pytest tests/test_pbfx.py tests/test_runner.py tests/test_result.py tests/test_worker_cli.py -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add config src/pandat_bridge tests
git commit -m "Run licensed Pandat jobs on Windows"
```

### Task 3: GitHub broker and independent Streamlit site

**Files:**
- Create: `src/pandat_bridge/github_api.py`
- Create: `streamlit_app.py`
- Create: `.streamlit/config.toml`
- Create: `.streamlit/secrets.example.toml`
- Test: `tests/test_github_api.py`
- Test: `tests/test_streamlit_app.py`

**Interfaces:**
- Consumes: Task 1 payload functions, server-side `github.token/owner/repo/workflow/ref`, and GitHub REST responses.
- Produces: `GitHubBroker.dispatch(job: JobSpec) -> WorkflowRun`, `get_run(run_id: int) -> RunState`, `get_runner_state(label: str) -> RunnerState`, `download_artifact(run_id: int, job_id: UUID) -> bytes`, and a Streamlit UI with submit, status and download states.

- [ ] **Step 1: Write mocked GitHub REST tests**

Cover 200/204 dispatch variants, workflow-run correlation fallback, queued/in-progress/completed states, runner online/offline/busy, unauthorized, rate limited, network timeout, absent/expired/mismatched artifact and ZIP size limits.

- [ ] **Step 2: Implement the minimal GitHub client**

Use one `requests.Session`, explicit timeouts, GitHub API version headers and bounded artifact downloads; never include the token in exceptions.

- [ ] **Step 3: Write failing Streamlit smoke tests**

Assert the title contains only Pandat bridge wording, the form is available without an access code and builds C63(C9), dispatch stores only the current job/run in session state, runner-offline guidance is visible, and completed artifacts are downloadable.

- [ ] **Step 4: Implement the standalone Streamlit application**

Use an editable element/value table, clear queue/run/result states, manual refresh plus controlled polling, and equilibrium-result caveats. Do not copy the tensile-tool selector or branding.

- [ ] **Step 5: Run Task 3 tests**

Run: `python -m pytest tests/test_github_api.py tests/test_streamlit_app.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pandat_bridge/github_api.py streamlit_app.py .streamlit tests
git commit -m "Add cloud submission and status website"
```

### Task 4: Dispatch-only workflow and workstation setup

**Files:**
- Create: `.github/workflows/pandat-calculate.yml`
- Create: `scripts/check_local.ps1`
- Create: `scripts/start_runner.ps1`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `README.md`
- Test: `tests/test_workflow_contract.py`
- Test: `tests/test_setup_contract.py`

**Interfaces:**
- Consumes: Task 2 worker CLI, workflow input `payload_b64`, and workstation environment variables.
- Produces: a dispatch-only serialized self-hosted job, a 7-day artifact, read-only readiness output and exact private-repository/runner/Streamlit setup instructions.

- [ ] **Step 1: Write failing workflow contract tests**

Parse YAML and assert the only trigger is `workflow_dispatch`, `payload_b64` is required, runner labels include `pandat-licensed`, concurrency is single and non-cancelling, permissions are read-only by default, payload enters through an environment variable, artifact retention is 7 days and artifact upload runs under `always()`.

- [ ] **Step 2: Implement the GitHub Actions workflow**

Checkout the default branch, create a venv if needed, install locked runtime requirements, call `python -m pandat_bridge.worker_cli`, and upload the job output directory even on a categorized failure.

- [ ] **Step 3: Write failing PowerShell setup contract tests**

Assert readiness checks are read-only, `start_runner.ps1` does not install or register software, required paths are literal/environment-driven, secrets are not printed, and the runner is started interactively.

- [ ] **Step 4: Implement setup scripts and secret examples**

`check_local.ps1` reports Pandat/database/template/runner availability without launching Pandat. `start_runner.ps1` validates an already configured runner and then invokes `run.cmd` in the foreground.

- [ ] **Step 5: Document private-repository deployment and permission boundaries**

Include GitHub fine-grained token permissions, Streamlit secrets setup, self-hosted runner registration with the `pandat-licensed` label, local environment configuration, start/stop behavior, offline queue behavior and a revocation procedure.

- [ ] **Step 6: Run Task 4 tests**

Run: `python -m pytest tests/test_workflow_contract.py tests/test_setup_contract.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add .github scripts .env.example .gitignore requirements*.txt README.md tests
git commit -m "Configure secure Pandat self-hosted bridge"
```

### Task 5: End-to-end fake job and local readiness verification

**Files:**
- Modify: `README.md`
- Create: `docs/verification.md`
- Test: `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: all prior task interfaces.
- Produces: reproducible fake end-to-end evidence, local read-only readiness evidence and the manual checklist for the first licensed live job.

- [ ] **Step 1: Write and run an end-to-end fake calculation test**

Submit a C63(C9) payload through the broker mock, execute the worker with fake Pandat, create the artifact ZIP, make the UI consume it, and assert the job ID and numerical metadata match end to end.

- [ ] **Step 2: Run the workstation readiness script without starting Pandat**

Run: `powershell -NoProfile -File scripts/check_local.ps1`
Expected: Pandat 2024 and the configured database/template are found; runner may be reported unconfigured until the GitHub repository exists.

- [ ] **Step 3: Run the full test and import suite**

Run: `python -m pytest -q`
Expected: PASS.

Run: `python -m compileall -q src streamlit_app.py`
Expected: exit 0.

- [ ] **Step 4: Start a local Streamlit preview and perform browser smoke QA**

Verify access gate, valid/invalid composition form states, offline-runner state, responsive layout and absence of browser console errors. Do not dispatch a real GitHub job in local QA.

- [ ] **Step 5: Record verification evidence and remaining external setup**

Document test counts, readiness paths without secrets, fake artifact contents, and the exact actions still requiring the user account: create private repo, authorize Streamlit private-repo access, create minimal token, register/start runner, configure secrets and run one licensed live job.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/verification.md tests/test_end_to_end.py
git commit -m "Verify Pandat cloud bridge end to end"
```
