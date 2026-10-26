from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Mapping
from uuid import UUID, uuid4


class JobValidationError(ValueError):
    """Raised when an untrusted job payload violates the public contract."""


ELEMENT_SYMBOLS = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe "
    "Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In "
    "Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf "
    "Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm "
    "Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og".split()
)

_ALLOWED_FIELDS = frozenset(
    {
        "schema_version",
        "job_id",
        "sample_name",
        "unit",
        "composition",
        "submitted_total",
        "temperature_start_c",
        "temperature_end_c",
        "steps",
        "pressure_atm",
    }
)


@dataclass(frozen=True, slots=True)
class CompositionEntry:
    element: str
    value: float


@dataclass(frozen=True, slots=True)
class JobSpec:
    job_id: UUID
    sample_name: str
    sample_slug: str
    unit: str
    composition: tuple[CompositionEntry, ...]
    submitted_total: float
    temperature_start_c: float
    temperature_end_c: float
    steps: int
    pressure_atm: float
    schema_version: int = 1

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> "JobSpec":
        if not isinstance(data, Mapping):
            raise JobValidationError("job must be an object")
        unknown = sorted(set(data) - _ALLOWED_FIELDS)
        if unknown:
            raise JobValidationError(f"unknown fields: {', '.join(unknown)}")

        schema_version = data.get("schema_version", 1)
        if schema_version != 1:
            raise JobValidationError("schema_version must be 1")

        raw_job_id = data.get("job_id")
        try:
            job_id = uuid4() if raw_job_id is None else UUID(str(raw_job_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise JobValidationError("job_id must be a UUID") from exc

        raw_name = data.get("sample_name")
        if not isinstance(raw_name, str):
            raise JobValidationError("sample_name must be text")
        sample_name = raw_name.strip()
        if not sample_name or len(sample_name) > 80 or any(ord(ch) < 32 for ch in sample_name):
            raise JobValidationError("sample_name must contain 1-80 printable characters")
        slug = re.sub(r"[^A-Za-z0-9]+", "-", sample_name).strip("-")[:48] or "sample"

        unit = data.get("unit")
        if unit not in {"at", "wt"}:
            raise JobValidationError("unit must be 'at' or 'wt'")

        raw_composition = data.get("composition")
        if not isinstance(raw_composition, list) or not raw_composition:
            raise JobValidationError("composition must be a non-empty list")
        seen: set[str] = set()
        entries: list[CompositionEntry] = []
        for raw_entry in raw_composition:
            if not isinstance(raw_entry, Mapping) or set(raw_entry) != {"element", "value"}:
                raise JobValidationError("each composition entry needs element and value")
            raw_element = raw_entry["element"]
            if not isinstance(raw_element, str) or not raw_element.strip():
                raise JobValidationError("element must be a chemical symbol")
            element = raw_element.strip().capitalize()
            if element not in ELEMENT_SYMBOLS:
                raise JobValidationError(f"unknown element: {raw_element}")
            if element in seen:
                raise JobValidationError(f"duplicate element: {element}")
            seen.add(element)
            raw_value = raw_entry["value"]
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise JobValidationError(f"composition value for {element} must be finite")
            value = float(raw_value)
            if not math.isfinite(value):
                raise JobValidationError(f"composition value for {element} must be finite")
            if value < 0:
                raise JobValidationError(f"composition value for {element} must be non-negative")
            if value > 0:
                entries.append(CompositionEntry(element, value))
        if not entries:
            raise JobValidationError("composition must include a positive value")
        raw_total = math.fsum(entry.value for entry in entries)
        if not 99.9 <= raw_total <= 100.1:
            raise JobValidationError("composition total must be between 99.9 and 100.1")
        normalized = tuple(
            CompositionEntry(entry.element, entry.value * 100.0 / raw_total)
            for entry in sorted(entries, key=lambda item: item.element)
        )

        supplied_total = data.get("submitted_total")
        if supplied_total is None:
            submitted_total = raw_total
        elif isinstance(supplied_total, bool) or not isinstance(supplied_total, (int, float)):
            raise JobValidationError("submitted_total must be finite")
        else:
            submitted_total = float(supplied_total)
            if not math.isfinite(submitted_total) or not 99.9 <= submitted_total <= 100.1:
                raise JobValidationError("submitted_total must be between 99.9 and 100.1")
            if not math.isclose(raw_total, 100.0, rel_tol=0, abs_tol=1e-6):
                raise JobValidationError("serialized composition must already be normalized")

        start = _finite_number(data.get("temperature_start_c"), "temperature")
        end = _finite_number(data.get("temperature_end_c"), "temperature")
        if not -273.15 <= start <= 3000 or not -273.15 <= end <= 3000 or start >= end:
            raise JobValidationError("temperature range must increase within -273.15 to 3000 C")

        steps = data.get("steps")
        if isinstance(steps, bool) or not isinstance(steps, int) or not 2 <= steps <= 2000:
            raise JobValidationError("steps must be an integer from 2 to 2000")
        pressure = _finite_number(data.get("pressure_atm"), "pressure")
        if not 0.000001 <= pressure <= 10000:
            raise JobValidationError("pressure must be between 0.000001 and 10000 atm")

        return cls(
            job_id=job_id,
            sample_name=sample_name,
            sample_slug=slug,
            unit=unit,
            composition=normalized,
            submitted_total=submitted_total,
            temperature_start_c=start,
            temperature_end_c=end,
            steps=steps,
            pressure_atm=pressure,
            schema_version=1,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "job_id": str(self.job_id),
            "sample_name": self.sample_name,
            "unit": self.unit,
            "composition": [
                {"element": entry.element, "value": entry.value}
                for entry in self.composition
            ],
            "submitted_total": self.submitted_total,
            "temperature_start_c": self.temperature_start_c,
            "temperature_end_c": self.temperature_end_c,
            "steps": self.steps,
            "pressure_atm": self.pressure_atm,
        }


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JobValidationError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise JobValidationError(f"{label} must be a finite number")
    return number
