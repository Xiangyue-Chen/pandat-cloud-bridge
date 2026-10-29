from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pandat_bridge.models import JobSpec
from pandat_bridge.pbfx import PbfxError, build_pbfx
from test_models import c63_mapping


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "config" / "line-template.pbfx"


def test_builds_deterministic_native_line_pbfx(tmp_path: Path) -> None:
    job = JobSpec.from_mapping(c63_mapping(sample_name="C63 & <C9>"))
    database = tmp_path / "数据库 & PanHEA.pdb"
    database.write_bytes(b"database-placeholder")

    output = build_pbfx(job, TEMPLATE, database, tmp_path / "job.pbfx")
    root = ET.parse(output).getroot()
    calc = root.find("calculation")
    assert calc is not None
    assert calc.get("name") == f"C63-C9-{str(job.job_id)[:8]}"
    assert calc.get("type") == "line"
    assert calc.find("databases/database").get("file_name") == str(database.resolve())
    assert calc.find("units/unit[@name='n']").get("value") == "x%"
    assert [node.get("name") for node in calc.findall("system/components/component")] == [
        "B",
        "Co",
        "Cr",
        "Fe",
        "Ni",
        "Ti",
    ]
    points = calc.findall("system/points/point/statespace")
    assert [float(point.find("T").get("value")) for point in points] == [25.0, 1500.0]
    assert [float(point.find("P").get("value")) for point in points] == [1.0, 1.0]
    assert [node.get("component") for node in points[0].findall("n")] == [
        "B",
        "Co",
        "Cr",
        "Fe",
        "Ni",
        "Ti",
    ]
    assert sum(float(node.get("value")) for node in points[0].findall("n")) == pytest.approx(100.0)
    assert calc.find("system/condition/steps").get("value") == "100"
    assert calc.find("output/tables/table").get("name") == "job.dat"
    text = output.read_text(encoding="utf-8")
    assert "__LOCAL_DATABASE__" not in text
    assert "C63 & <C9>" not in text
    assert "C:\\Users\\Administrator" not in TEMPLATE.read_text(encoding="utf-8")


def test_uses_weight_percent_and_custom_conditions(tmp_path: Path) -> None:
    job = JobSpec.from_mapping(
        c63_mapping(
            unit="wt",
            temperature_start_c=100,
            temperature_end_c=1200,
            steps=333,
            pressure_atm=0.5,
        )
    )
    database = tmp_path / "db.pdb"
    database.write_bytes(b"db")

    root = ET.parse(build_pbfx(job, TEMPLATE, database, tmp_path / "job.pbfx")).getroot()
    calc = root.find("calculation")
    assert calc.find("units/unit[@name='n']").get("value") == "w%"
    states = calc.findall("system/points/point/statespace")
    assert [state.find("T").get("value") for state in states] == ["100", "1200"]
    assert [state.find("P").get("value") for state in states] == ["0.5", "0.5"]
    assert calc.find("system/condition/steps").get("value") == "333"


def test_rejects_missing_database_or_template(tmp_path: Path) -> None:
    job = JobSpec.from_mapping(c63_mapping())
    database = tmp_path / "missing.pdb"

    with pytest.raises(PbfxError, match="database"):
        build_pbfx(job, TEMPLATE, database, tmp_path / "job.pbfx")
    with pytest.raises(PbfxError, match="template"):
        build_pbfx(job, tmp_path / "missing.pbfx", tmp_path / "db.pdb", tmp_path / "job.pbfx")


def test_rejects_template_missing_required_nodes(tmp_path: Path) -> None:
    job = JobSpec.from_mapping(c63_mapping())
    database = tmp_path / "db.pdb"
    database.write_bytes(b"db")
    malformed = tmp_path / "bad.pbfx"
    malformed.write_text("<pbfx><calculation type='line'/></pbfx>", encoding="utf-8")

    with pytest.raises(PbfxError, match="required node"):
        build_pbfx(job, malformed, database, tmp_path / "job.pbfx")


def test_pbfx_uses_registered_format(tmp_path: Path) -> None:
    job = JobSpec.from_mapping(c63_mapping())
    database = tmp_path / "database.tdb"
    database.write_text("tdb", encoding="utf-8")

    output = build_pbfx(
        job,
        TEMPLATE,
        database,
        tmp_path / "job.pbfx",
        database_format="tdb",
    )

    node = ET.parse(output).getroot().find("calculation/databases/database")
    assert node is not None
    assert node.get("type") == "tdb"
