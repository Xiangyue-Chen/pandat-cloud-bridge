from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from pandat_bridge.models import JobSpec
from pandat_bridge.result import ResultValidationError, package_result, parse_native_result
from pandat_bridge.runner import RunOutcome
from test_models import c63_mapping


FIXTURE = Path(__file__).parent / "fixtures" / "native-line.result"


def fixture_job(**overrides: object) -> JobSpec:
    return JobSpec.from_mapping(
        c63_mapping(
            sample_name="C63 $x^2$ / literal",
            composition=[
                {"element": "Fe", "value": 50.0},
                {"element": "Ni", "value": 50.0},
            ],
            **overrides,
        )
    )


def successful_run(tmp_path: Path) -> RunOutcome:
    stdout = tmp_path / "job.stdout.log"
    stderr = tmp_path / "job.stderr.log"
    stdout.write_text("Simulation is done with Success", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")
    return RunOutcome(
        status="success",
        error_code=None,
        message="Pandat calculation completed",
        result_path=FIXTURE,
        stdout_path=stdout,
        stderr_path=stderr,
        seconds=1.25,
        pid=1234,
    )


def test_parses_and_preserves_duplicate_temperature_boundary_points() -> None:
    parsed = parse_native_result(fixture_job(), FIXTURE)

    assert [point.temperature_c for point in parsed.points] == pytest.approx(
        [25.0, 726.85, 726.85, 1500.0]
    )
    assert parsed.phase_names == ("Bcc", "Fcc", "Liquid")
    assert parsed.points[0].fractions == {"Fcc": 0.6, "Bcc": 0.4}
    assert parsed.max_balance_error < 1e-12
    assert parsed.duplicate_temperature_count == 1
    assert parsed.melting_range_c == pytest.approx((1500.0, 1500.0))


def test_rejects_wrong_pressure_or_temperature_endpoints(tmp_path: Path) -> None:
    wrong_pressure = tmp_path / "wrong-pressure.result"
    wrong_pressure.write_text(
        FIXTURE.read_text(encoding="utf-8").replace("<P>101325</P>", "<P>100000</P>", 1),
        encoding="utf-8",
    )
    with pytest.raises(ResultValidationError, match="pressure"):
        parse_native_result(fixture_job(), wrong_pressure)

    wrong_end = tmp_path / "wrong-end.result"
    wrong_end.write_text(
        FIXTURE.read_text(encoding="utf-8").replace("<T>1773.15</T>", "<T>1700</T>"),
        encoding="utf-8",
    )
    with pytest.raises(ResultValidationError, match="endpoint"):
        parse_native_result(fixture_job(), wrong_end)


def test_rejects_phase_or_element_balance_failures(tmp_path: Path) -> None:
    bad_fraction = tmp_path / "bad-fraction.result"
    bad_fraction.write_text(
        FIXTURE.read_text(encoding="utf-8").replace('f="0.4"', 'f="0.3"', 1),
        encoding="utf-8",
    )
    with pytest.raises(ResultValidationError, match="balance"):
        parse_native_result(fixture_job(), bad_fraction)


def test_packages_auditable_relative_result_bundle(tmp_path: Path) -> None:
    job = fixture_job()
    output_dir = tmp_path / "artifact"

    archive = package_result(job, FIXTURE, successful_run(tmp_path), output_dir)

    expected = {
        "native.result",
        "phase-fractions.csv",
        "phase-regions.csv",
        "phase-diagram.png",
        "phase-diagram.pdf",
        "metadata.json",
        "status.json",
        f"pandat-result-{job.job_id}.zip",
    }
    assert {path.name for path in output_dir.iterdir()} == expected
    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["job"]["sample_name"] == "C63 $x^2$ / literal"
    assert metadata["verification"]["point_count"] == 4
    assert metadata["verification"]["duplicate_temperature_count"] == 1
    assert metadata["claim_boundary"] == "Pandat equilibrium prediction; not experimental validation."
    status = json.loads((output_dir / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "success"
    assert status["error_code"] is None
    assert archive == output_dir / f"pandat-result-{job.job_id}.zip"
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        assert names == expected - {archive.name}
        all_text = "\n".join(
            zf.read(name).decode("utf-8", errors="ignore")
            for name in names
            if name.endswith((".json", ".csv"))
        )
        assert str(tmp_path) not in all_text
        assert "C:\\Users\\Administrator" not in all_text
