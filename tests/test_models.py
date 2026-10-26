from __future__ import annotations

import math
from uuid import UUID

import pytest

from pandat_bridge.models import JobSpec, JobValidationError


def c63_mapping(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "sample_name": "C63(C9)",
        "unit": "at",
        "composition": [
            {"element": "Fe", "value": 57.93},
            {"element": "Co", "value": 9.66},
            {"element": "Ni", "value": 26.28},
            {"element": "Cr", "value": 1.10},
            {"element": "Ti", "value": 4.97},
            {"element": "B", "value": 0.05},
        ],
        "temperature_start_c": 25.0,
        "temperature_end_c": 1500.0,
        "steps": 100,
        "pressure_atm": 1.0,
    }
    data.update(overrides)
    return data


def test_accepts_c63_and_preserves_validated_conditions() -> None:
    job = JobSpec.from_mapping(c63_mapping())

    assert str(UUID(str(job.job_id))) == str(job.job_id)
    assert job.sample_name == "C63(C9)"
    assert job.sample_slug == "C63-C9"
    assert job.unit == "at"
    assert job.submitted_total == pytest.approx(99.99)
    assert sum(entry.value for entry in job.composition) == pytest.approx(100.0)
    expected = {
        "B": 0.05,
        "Co": 9.66,
        "Cr": 1.10,
        "Fe": 57.93,
        "Ni": 26.28,
        "Ti": 4.97,
    }
    assert {entry.element: entry.value for entry in job.composition} == pytest.approx(
        {element: value * 100 / 99.99 for element, value in expected.items()}
    )
    assert job.temperature_start_c == 25.0
    assert job.temperature_end_c == 1500.0
    assert job.steps == 100
    assert job.pressure_atm == 1.0


def test_accepts_weight_percent_and_normalizes_near_100_total() -> None:
    job = JobSpec.from_mapping(
        c63_mapping(
            unit="wt",
            composition=[
                {"element": "Fe", "value": 57.33},
                {"element": "Co", "value": 10.09},
                {"element": "Ni", "value": 27.34},
                {"element": "Cr", "value": 1.01},
                {"element": "Ti", "value": 4.22},
                {"element": "B", "value": 0.01},
            ],
        )
    )

    assert job.unit == "wt"
    assert job.submitted_total == pytest.approx(100.0)
    assert sum(item.value for item in job.composition) == pytest.approx(100.0)


def test_retains_submitted_total_while_normalizing_values() -> None:
    job = JobSpec.from_mapping(
        c63_mapping(
            composition=[
                {"element": "Fe", "value": 50.0},
                {"element": "Ni", "value": 49.95},
            ]
        )
    )

    assert job.submitted_total == pytest.approx(99.95)
    assert [entry.value for entry in job.composition] == pytest.approx(
        [50.02501250625313, 49.97498749374687]
    )


def test_display_name_is_kept_but_path_slug_is_sanitized() -> None:
    job = JobSpec.from_mapping(c63_mapping(sample_name="../../ C63 $ weird/名字"))

    assert job.sample_name == "../../ C63 $ weird/名字"
    assert job.sample_slug == "C63-weird"


@pytest.mark.parametrize("unit", ["atomic", "", None, 1])
def test_rejects_unknown_units(unit: object) -> None:
    with pytest.raises(JobValidationError, match="unit"):
        JobSpec.from_mapping(c63_mapping(unit=unit))


@pytest.mark.parametrize(
    ("composition", "message"),
    [
        ([{"element": "Xx", "value": 100}], "element"),
        ([{"element": "Fe", "value": 50}, {"element": "fe", "value": 50}], "duplicate"),
        ([{"element": "Fe", "value": -1}, {"element": "Ni", "value": 101}], "non-negative"),
        ([{"element": "Fe", "value": math.nan}, {"element": "Ni", "value": 100}], "finite"),
        ([{"element": "Fe", "value": math.inf}, {"element": "Ni", "value": 100}], "finite"),
        ([{"element": "Fe", "value": 90}], "99.9"),
        ([{"element": "Fe", "value": 100.2}], "100.1"),
        ([], "composition"),
    ],
)
def test_rejects_invalid_compositions(
    composition: list[dict[str, object]], message: str
) -> None:
    with pytest.raises(JobValidationError, match=message):
        JobSpec.from_mapping(c63_mapping(composition=composition))


@pytest.mark.parametrize("name", ["", "   ", "bad\nname", "x" * 81])
def test_rejects_empty_control_or_oversized_sample_names(name: str) -> None:
    with pytest.raises(JobValidationError, match="sample_name"):
        JobSpec.from_mapping(c63_mapping(sample_name=name))


@pytest.mark.parametrize(
    "overrides",
    [
        {"temperature_start_c": 25, "temperature_end_c": 25},
        {"temperature_start_c": 100, "temperature_end_c": 25},
        {"temperature_start_c": -273.16},
        {"temperature_end_c": 3000.01},
        {"temperature_start_c": math.nan},
    ],
)
def test_rejects_invalid_temperature_ranges(overrides: dict[str, object]) -> None:
    with pytest.raises(JobValidationError, match="temperature"):
        JobSpec.from_mapping(c63_mapping(**overrides))


@pytest.mark.parametrize("steps", [1, 2001, 2.5, "100"])
def test_rejects_invalid_step_counts(steps: object) -> None:
    with pytest.raises(JobValidationError, match="steps"):
        JobSpec.from_mapping(c63_mapping(steps=steps))


@pytest.mark.parametrize("pressure", [0, 0.0000009, 10000.1, math.inf, "1"])
def test_rejects_invalid_pressures(pressure: object) -> None:
    with pytest.raises(JobValidationError, match="pressure"):
        JobSpec.from_mapping(c63_mapping(pressure_atm=pressure))


def test_rejects_unknown_top_level_fields() -> None:
    with pytest.raises(JobValidationError, match="unknown fields"):
        JobSpec.from_mapping(c63_mapping(command="Remove-Item"))
