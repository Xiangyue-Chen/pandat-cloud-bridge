from __future__ import annotations

import csv
import json
import math
import shutil
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .catalog import DatabaseEntry
from .models import JobSpec
from .runner import RunOutcome


TOLERANCE = 5e-6
MAX_NATIVE_RESULT_BYTES = 100 * 1024 * 1024


class ResultValidationError(ValueError):
    """Raised when a native Pandat result fails structural or numerical checks."""


@dataclass(frozen=True, slots=True)
class ResultPoint:
    temperature_c: float
    pressure_pa: float
    gibbs_j_mol: float | None
    bulk: dict[str, float]
    fractions: dict[str, float]
    compositions: dict[str, dict[str, float]]
    balance_error: float


@dataclass(frozen=True, slots=True)
class ParsedResult:
    points: tuple[ResultPoint, ...]
    phase_names: tuple[str, ...]
    max_balance_error: float
    duplicate_temperature_count: int
    melting_range_c: tuple[float, float] | None


def parse_native_result(job: JobSpec, path: Path) -> ParsedResult:
    path = Path(path)
    if not path.is_file():
        raise ResultValidationError(f"native result not found: {path.name}")
    if path.stat().st_size > MAX_NATIVE_RESULT_BYTES:
        raise ResultValidationError("native result exceeds 100 MiB")
    raw = path.read_bytes()
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        try:
            root = ET.fromstring(raw.decode("gb18030"))
        except (UnicodeDecodeError, ET.ParseError) as exc:
            raise ResultValidationError("native result is not valid Pandat XML") from exc
    section = root.find("section")
    if section is None:
        raise ResultValidationError("native result section is missing")
    weights = {
        node.get("name", ""): _float_attr(node, "weight")
        for node in section.findall("components/component")
    }
    expected = _expected_bulk(job, weights)
    points: list[ResultPoint] = []
    all_phases: set[str] = set()
    for point_index, node in enumerate(section.findall("line/point")):
        state = node.find("statespace")
        if state is None:
            raise ResultValidationError(f"point {point_index} statespace is missing")
        temperature_node = state.find("T")
        pressure_node = state.find("P")
        if temperature_node is None or pressure_node is None:
            raise ResultValidationError(f"point {point_index} temperature or pressure is missing")
        temperature_c = _float_text(temperature_node) - 273.15
        pressure_pa = _float_text(pressure_node)
        expected_pa = job.pressure_atm * 101325.0
        if abs(pressure_pa - expected_pa) > max(0.1, expected_pa * 1e-6):
            raise ResultValidationError(f"point {point_index} pressure does not match the job")
        bulk = {child.get("name", ""): _float_attr(child, "x") for child in state.findall("component")}
        fractions: dict[str, float] = {}
        compositions: dict[str, dict[str, float]] = {}
        for phase_node in node.findall("phasepoint"):
            if phase_node.get("in_equilibrium") != "true":
                continue
            phase_meta = phase_node.find("phase")
            prop = phase_node.find("property")
            phase_state = phase_node.find("statespace")
            if phase_meta is None or prop is None or phase_state is None:
                raise ResultValidationError(f"point {point_index} phase data is incomplete")
            name = phase_meta.get("name", "")
            if not name:
                raise ResultValidationError(f"point {point_index} has an unnamed phase")
            nth = int(phase_meta.get("nth", "0"))
            if nth > 0:
                name = f"{name}#{nth + 1}"
            if name in fractions:
                raise ResultValidationError(f"point {point_index} repeats phase {name}")
            fractions[name] = _float_attr(prop, "f")
            compositions[name] = {
                child.get("name", ""): _float_attr(child, "x")
                for child in phase_state.findall("component")
            }
            all_phases.add(name)
        if not fractions:
            raise ResultValidationError(f"point {point_index} has no equilibrium phases")
        errors = [abs(math.fsum(fractions.values()) - 1.0), abs(math.fsum(bulk.values()) - 1.0)]
        errors.extend(abs(math.fsum(values.values()) - 1.0) for values in compositions.values())
        for element, target in bulk.items():
            reconstructed = math.fsum(
                fractions[phase] * compositions[phase].get(element, 0.0) for phase in fractions
            )
            errors.append(abs(reconstructed - target))
        for element, target in expected.items():
            errors.append(abs(bulk.get(element, 0.0) - target))
        values = list(fractions.values()) + list(bulk.values()) + [
            value for phase in compositions.values() for value in phase.values()
        ]
        if any(not math.isfinite(value) or value < -1e-10 or value > 1 + TOLERANCE for value in values):
            raise ResultValidationError(f"point {point_index} contains an out-of-range value")
        balance_error = max(errors)
        if balance_error >= TOLERANCE:
            raise ResultValidationError(
                f"point {point_index} balance error {balance_error:.3g} exceeds {TOLERANCE:g}"
            )
        prop = node.find("property")
        gibbs = _float_attr(prop, "G") if prop is not None and prop.get("G") is not None else None
        points.append(
            ResultPoint(
                temperature_c=round(temperature_c, 9),
                pressure_pa=pressure_pa,
                gibbs_j_mol=gibbs,
                bulk=bulk,
                fractions=fractions,
                compositions=compositions,
                balance_error=balance_error,
            )
        )
    if not points:
        raise ResultValidationError("native result has no line points")
    temperatures = [point.temperature_c for point in points]
    if abs(min(temperatures) - job.temperature_start_c) > 0.02 or abs(
        max(temperatures) - job.temperature_end_c
    ) > 0.02:
        raise ResultValidationError("native result temperature endpoints do not match the job")
    duplicates = len(temperatures) - len(set(temperatures))
    liquid_temperatures = [
        point.temperature_c for point in points if point.fractions.get("Liquid", 0.0) > 1e-8
    ]
    melting = (
        (min(liquid_temperatures), max(liquid_temperatures)) if liquid_temperatures else None
    )
    return ParsedResult(
        points=tuple(points),
        phase_names=tuple(sorted(all_phases)),
        max_balance_error=max(point.balance_error for point in points),
        duplicate_temperature_count=duplicates,
        melting_range_c=melting,
    )


def package_result(
    job: JobSpec,
    native_result: Path,
    run: RunOutcome,
    output_dir: Path,
    *,
    database: DatabaseEntry | None = None,
    catalog_digest: str | None = None,
) -> Path:
    parsed = parse_native_result(job, native_result)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(native_result, output_dir / "native.result")
    _write_phase_fractions(output_dir / "phase-fractions.csv", parsed)
    _write_phase_regions(output_dir / "phase-regions.csv", parsed)
    _write_plot(job, parsed, output_dir / "phase-diagram.png", output_dir / "phase-diagram.pdf")
    metadata = {
        "schema_version": 1,
        "job": job.to_dict(),
        "verification": {
            "point_count": len(parsed.points),
            "phase_names": list(parsed.phase_names),
            "max_balance_error": parsed.max_balance_error,
            "duplicate_temperature_count": parsed.duplicate_temperature_count,
            "melting_range_c": list(parsed.melting_range_c) if parsed.melting_range_c else None,
        },
        "claim_boundary": "Pandat equilibrium prediction; not experimental validation.",
    }
    if database is not None:
        if catalog_digest is None:
            raise ResultValidationError("catalog digest is required for database metadata")
        metadata["database"] = {
            "id": database.id,
            "display_name": database.display_name,
            "format": database.format,
            "catalog_digest": catalog_digest,
        }
    _write_json(output_dir / "metadata.json", metadata)
    _write_json(
        output_dir / "status.json",
        {
            "status": run.status,
            "error_code": run.error_code,
            "message": run.message,
            "seconds": run.seconds,
            "stdout": run.stdout_path.name,
            "stderr": run.stderr_path.name,
        },
    )
    archive = output_dir / f"pandat-result-{job.job_id}.zip"
    files = [path for path in output_dir.iterdir() if path.is_file() and path != archive]
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(files, key=lambda item: item.name):
            bundle.write(path, arcname=path.name)
    return archive


def _expected_bulk(job: JobSpec, weights: dict[str, float]) -> dict[str, float]:
    submitted = {entry.element: entry.value for entry in job.composition}
    if job.unit == "wt":
        missing = sorted(set(submitted) - set(weights))
        if missing:
            raise ResultValidationError(f"native result lacks component weights: {', '.join(missing)}")
        submitted = {element: value / weights[element] for element, value in submitted.items()}
    total = math.fsum(submitted.values())
    return {element: value / total for element, value in submitted.items()}


def _write_phase_fractions(path: Path, parsed: ParsedResult) -> None:
    fields = ["point_index", "temperature_c", "pressure_pa", "gibbs_j_mol", *parsed.phase_names]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index, point in enumerate(parsed.points):
            writer.writerow(
                {
                    "point_index": index,
                    "temperature_c": point.temperature_c,
                    "pressure_pa": point.pressure_pa,
                    "gibbs_j_mol": point.gibbs_j_mol,
                    **{phase: point.fractions.get(phase, 0.0) for phase in parsed.phase_names},
                }
            )


def _write_phase_regions(path: Path, parsed: ParsedResult) -> None:
    regions: list[dict[str, object]] = []
    for point in parsed.points:
        phases = " + ".join(sorted(name for name, value in point.fractions.items() if value > 1e-8))
        if not regions or regions[-1]["phases"] != phases:
            regions.append({"start_c": point.temperature_c, "end_c": point.temperature_c, "phases": phases})
        else:
            regions[-1]["end_c"] = point.temperature_c
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["start_c", "end_c", "phases"])
        writer.writeheader()
        writer.writerows(regions)


def _write_plot(job: JobSpec, parsed: ParsedResult, png: Path, pdf: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 5.6), constrained_layout=True)
    try:
        temperatures = [point.temperature_c for point in parsed.points]
        colors = plt.get_cmap("tab10")
        for index, phase in enumerate(parsed.phase_names):
            ax.plot(
                temperatures,
                [100.0 * point.fractions.get(phase, 0.0) for point in parsed.points],
                label=phase,
                color=colors(index % 10),
                linewidth=1.8,
            )
        ax.set_title(job.sample_name, loc="left", fontweight="bold", parse_math=False)
        ax.set_xlabel("Temperature (°C)")
        ax.set_ylabel("Equilibrium phase fraction (%)")
        ax.set_xlim(job.temperature_start_c, job.temperature_end_c)
        ax.set_ylim(0, 103)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color="#d9d9d9", linewidth=0.6, alpha=0.6)
        ax.legend(frameon=False, ncol=min(4, max(1, len(parsed.phase_names))), fontsize=8)
        fig.savefig(png, dpi=220, facecolor="white")
        fig.savefig(pdf, facecolor="white")
    finally:
        plt.close(fig)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _float_attr(node: ET.Element, name: str) -> float:
    try:
        value = float(node.get(name, ""))
    except (TypeError, ValueError) as exc:
        raise ResultValidationError(f"invalid numeric attribute {name}") from exc
    if not math.isfinite(value):
        raise ResultValidationError(f"non-finite numeric attribute {name}")
    return value


def _float_text(node: ET.Element) -> float:
    try:
        value = float(node.text or "")
    except (TypeError, ValueError) as exc:
        raise ResultValidationError(f"invalid numeric value for {node.tag}") from exc
    if not math.isfinite(value):
        raise ResultValidationError(f"non-finite numeric value for {node.tag}")
    return value
