from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .models import JobSpec


class PbfxError(ValueError):
    """Raised when a native Pandat batch file cannot be created safely."""


def build_pbfx(job: JobSpec, template: Path, database: Path, destination: Path) -> Path:
    template = Path(template)
    database = Path(database)
    destination = Path(destination)
    if not template.is_file():
        raise PbfxError(f"template not found: {template}")
    if not database.is_file():
        raise PbfxError(f"database not found: {database}")
    try:
        tree = ET.parse(template)
    except (ET.ParseError, OSError) as exc:
        raise PbfxError(f"template is not valid XML: {exc}") from exc
    root = tree.getroot()
    calc = _required(root, "calculation")
    if calc.get("type") != "line":
        raise PbfxError("template calculation must have type='line'")
    calc.set("name", f"{job.sample_slug}-{str(job.job_id)[:8]}")
    _required(calc, "databases/database").set("file_name", str(database.resolve()))
    _required(calc, "units/unit[@name='n']").set("value", "x%" if job.unit == "at" else "w%")

    components = _required(calc, "system/components")
    components.clear()
    for entry in job.composition:
        ET.SubElement(components, "component", name=entry.element, status="Selected")

    points = _required(calc, "system/points")
    points.clear()
    for temperature in (job.temperature_start_c, job.temperature_end_c):
        state = ET.SubElement(ET.SubElement(points, "point"), "statespace")
        ET.SubElement(state, "T", value=_number(temperature))
        ET.SubElement(state, "P", value=_number(job.pressure_atm))
        for entry in job.composition:
            ET.SubElement(
                state,
                "n",
                component=entry.element,
                value=f"{entry.value:.12f}".rstrip("0").rstrip("."),
            )

    _required(calc, "system/condition/steps").set("value", str(job.steps))
    _required(calc, "output/tables/table").set("name", "job.dat")
    ET.indent(tree, space="  ")
    destination.parent.mkdir(parents=True, exist_ok=True)
    tree.write(destination, encoding="utf-8", xml_declaration=False)
    return destination


def _required(parent: ET.Element, path: str) -> ET.Element:
    node = parent.find(path)
    if node is None:
        raise PbfxError(f"template required node missing: {path}")
    return node


def _number(value: float) -> str:
    return f"{value:.12g}"
