from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from pandat_bridge.runner import RunnerError, run_pandat


FAKE = Path(__file__).with_name("fake_pandat.py")


def make_pbfx(tmp_path: Path) -> Path:
    path = tmp_path / "job.pbfx"
    path.write_text("<pbfx />", encoding="utf-8")
    return path


def test_detects_success_and_fresh_native_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_PANDAT_MODE", "success")

    outcome = run_pandat(make_pbfx(tmp_path), FAKE, timeout_s=2)

    assert outcome.status == "success"
    assert outcome.error_code is None
    assert outcome.result_path == tmp_path / "job.result"
    assert outcome.result_path.read_text(encoding="utf-8") == "<result />"
    assert "Simulation is done with Success" in outcome.stdout_path.read_text(encoding="utf-8")
    assert outcome.seconds < 2


@pytest.mark.parametrize(
    ("mode", "status", "code", "message"),
    [
        ("license", "failed", "license_unavailable", "license"),
        ("unsupported", "failed", "unsupported_element", "Ta"),
        ("failure", "failed", "pandat_failure", "failure"),
        ("early_exit", "failed", "early_exit", "exit"),
        ("missing", "failed", "missing_result", "missing"),
        ("stale", "failed", "stale_result", "stale"),
        ("timeout", "failed", "timeout", "timeout"),
    ],
)
def test_classifies_native_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    status: str,
    code: str,
    message: str,
) -> None:
    monkeypatch.setenv("FAKE_PANDAT_MODE", mode)

    outcome = run_pandat(make_pbfx(tmp_path), FAKE, timeout_s=0.35)

    assert outcome.status == status
    assert outcome.error_code == code
    assert message.lower() in outcome.message.lower()


def test_timeout_terminates_only_the_started_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    monkeypatch.setenv("FAKE_PANDAT_MODE", "timeout")
    try:
        outcome = run_pandat(make_pbfx(tmp_path), FAKE, timeout_s=0.25)
        assert outcome.error_code == "timeout"
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_rejects_missing_inputs_before_launch(tmp_path: Path) -> None:
    pbfx = make_pbfx(tmp_path)

    with pytest.raises(RunnerError, match="executable"):
        run_pandat(pbfx, tmp_path / "missing.exe", timeout_s=1)
    with pytest.raises(RunnerError, match="PBFX"):
        run_pandat(tmp_path / "missing.pbfx", FAKE, timeout_s=1)
    with pytest.raises(RunnerError, match="timeout"):
        run_pandat(pbfx, FAKE, timeout_s=0)
