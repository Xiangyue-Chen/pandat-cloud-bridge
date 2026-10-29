from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ELEMENT_SYMBOLS = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe "
    "Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In "
    "Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf "
    "Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm "
    "Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og".split()
)
_ROOT_KEYS = {"schema_version", "generated_at", "source", "databases"}
_ENTRY_KEYS = {
    "id",
    "display_name",
    "format",
    "file_path",
    "sha256",
    "elements",
    "enabled",
    "default",
}


class CatalogError(ValueError):
    """Raised when a local Pandat database catalog is malformed."""


@dataclass(frozen=True, slots=True)
class DatabaseEntry:
    id: str
    display_name: str
    format: str
    file_path: Path
    sha256: str
    elements: tuple[str, ...]
    enabled: bool
    default: bool

    def supports(self, elements: set[str] | tuple[str, ...] | list[str]) -> bool:
        return set(elements).issubset(self.elements)

    def public_mapping(self) -> dict[str, object]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "format": self.format,
            "elements": list(self.elements),
            "enabled": self.enabled,
            "default": self.default,
        }


@dataclass(frozen=True, slots=True)
class DatabaseCatalog:
    schema_version: int
    generated_at: date
    source: str
    databases: tuple[DatabaseEntry, ...]

    @property
    def by_id(self) -> dict[str, DatabaseEntry]:
        return {database.id: database for database in self.databases}

    def default(self) -> DatabaseEntry:
        return next(
            database
            for database in self.databases
            if database.enabled and database.default
        )

    def require_enabled(self, database_id: str) -> DatabaseEntry:
        database = self.by_id.get(database_id)
        if database is None or not database.enabled:
            raise CatalogError(f"unknown or disabled database id: {database_id}")
        return database

    def get(self, database_id: str) -> DatabaseEntry:
        return self.require_enabled(database_id)

    def public_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.isoformat(),
            "source": self.source,
            "databases": [
                database.public_mapping()
                for database in self.databases
                if database.enabled
            ],
        }


def _require_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CatalogError(f"{context} must be an object")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise CatalogError(f"{context} keys mismatch; missing={missing}, extra={extra}")


def _parse_database(value: Any, index: int) -> DatabaseEntry:
    context = f"databases[{index}]"
    item = _require_object(value, context)
    _require_exact_keys(item, _ENTRY_KEYS, context)

    database_id = item["id"]
    display_name = item["display_name"]
    database_format = item["format"]
    file_path_text = item["file_path"]
    sha256 = item["sha256"]
    elements = item["elements"]
    enabled = item["enabled"]
    default = item["default"]

    if not isinstance(database_id, str) or not _ID_PATTERN.fullmatch(database_id):
        raise CatalogError(f"{context}.id is invalid")
    if not isinstance(display_name, str) or not display_name.strip():
        raise CatalogError(f"{context}.display_name is invalid")
    if database_format not in {"pdb", "tdb"}:
        raise CatalogError(f"{context}.format is unsupported")
    if not isinstance(file_path_text, str) or not file_path_text.strip():
        raise CatalogError(f"{context}.file_path is invalid")
    file_path = Path(file_path_text)
    if not file_path.is_absolute() or file_path.suffix.lower() != f".{database_format}":
        raise CatalogError(
            f"{context}.file_path must be absolute and agree with format"
        )
    if not isinstance(sha256, str) or not _SHA256_PATTERN.fullmatch(sha256):
        raise CatalogError(f"{context}.sha256 is invalid")
    if not isinstance(elements, list) or not elements:
        raise CatalogError(f"{context}.elements must be a non-empty list")
    if any(not isinstance(element, str) or element not in _ELEMENT_SYMBOLS for element in elements):
        raise CatalogError(f"{context}.elements contains an invalid symbol")
    if elements != sorted(set(elements)):
        raise CatalogError(f"{context}.elements must be unique and sorted")
    if not isinstance(enabled, bool) or not isinstance(default, bool):
        raise CatalogError(f"{context}.enabled/default must be booleans")
    if default and not enabled:
        raise CatalogError(f"{context} cannot be default while disabled")

    return DatabaseEntry(
        id=database_id,
        display_name=display_name.strip(),
        format=database_format,
        file_path=file_path,
        sha256=sha256,
        elements=tuple(elements),
        enabled=enabled,
        default=default,
    )


def catalog_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse_catalog(raw: bytes) -> DatabaseCatalog:
    try:
        decoded = raw.decode("utf-8")
        document = json.loads(decoded)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot parse catalog: {exc}") from exc

    root = _require_object(document, "catalog")
    _require_exact_keys(root, _ROOT_KEYS, "catalog")
    if root["schema_version"] != 1:
        raise CatalogError("unsupported schema_version")
    if not isinstance(root["generated_at"], str):
        raise CatalogError("generated_at must be an ISO date")
    try:
        generated_at = date.fromisoformat(root["generated_at"])
    except ValueError as exc:
        raise CatalogError("generated_at must be an ISO date") from exc
    if not isinstance(root["source"], str) or not root["source"].strip():
        raise CatalogError("source must be a non-empty string")
    if not isinstance(root["databases"], list) or not root["databases"]:
        raise CatalogError("databases must be a non-empty list")

    databases = tuple(
        _parse_database(value, index)
        for index, value in enumerate(root["databases"])
    )
    ids = [database.id for database in databases]
    if len(ids) != len(set(ids)):
        raise CatalogError("duplicate database id")
    enabled_defaults = [
        database for database in databases if database.enabled and database.default
    ]
    if len(enabled_defaults) != 1:
        raise CatalogError("catalog must contain exactly one enabled default")

    return DatabaseCatalog(
        schema_version=1,
        generated_at=generated_at,
        source=root["source"].strip(),
        databases=databases,
    )


def load_catalog(path: Path | str) -> DatabaseCatalog:
    catalog_path = Path(path)
    try:
        raw = catalog_path.read_bytes()
    except OSError as exc:
        raise CatalogError(f"cannot read catalog: {exc}") from exc
    return parse_catalog(raw)
