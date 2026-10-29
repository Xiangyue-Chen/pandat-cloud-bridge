from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from pandat_bridge.catalog import (
    CatalogError,
    catalog_digest,
    load_catalog,
    parse_catalog,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "config" / "databases.json"


EXPECTED_ELEMENTS = {
    "mdtcu-2020-th": "Al B Bi C Cr Cu Fe Mn Ni P Pb S Sb Se Si Sn Ti Zn Zr",
    "panal-2020-th-mb": "Ag Al B Be Bi C Ca Ce Co Cr Cu Fe Gd Ge Hf K Li Mg Mn Na Nb Ni Pb Sb Sc Si Sn Sr Ti V W Y Zn Zr",
    "panal-2022-th-mb": "Ag Al B Ba Be Bi C Ca Ce Co Cr Cu Er Fe Gd Ge Hf K La Li Mg Mn Na Nb Ni Pb Sb Sc Si Sn Sr Ti V W Y Zn Zr",
    "panal-2023a-th-mb": "Ag Al B Ba Be Bi C Ca Ce Co Cr Cu Er Fe Gd Ge Hf K La Li Mg Mn Na Nb Ni Pb Sb Sc Si Sn Sr Ti V W Y Zn Zr",
    "panal-2024-th-mb": "Ag Al B Ba Be Bi C Ca Ce Co Cr Cu Er Fe Gd Ge Hf K La Li Mg Mn Na Nb Ni O Pb Sb Sc Si Sn Sr Ti V W Y Zn Zr",
    "panco-2020-th": "Al B C Co Cr Cu Fe Mn Mo Nb Ni Pt Re Si Ta Ti W Zr",
    "panco-2023-th-mb": "Al B C Co Cr Cu Fe Mn Mo Nb Ni Pt Re Si Ta Ti V W Zr",
    "panfe-2023-th-mb": "Al As B C Ca Ce Co Cr Cu Fe Mg Mn Mo N Nb Ni O P Pb Pr S Si Sn Ta Ti V W Y Zn Zr",
    "panhea-2022-th-mb": "Ag Al B C Co Cr Cu Fe Hf Li Mg Mn Mo Ni Si Sn Ti V Zr",
    "panhea-2023-th-mb": "Ag Al B C Co Cr Cu Fe Hf Li Mg Mn Mo Ni Si Sn Ti V Zn Zr",
    "panhea-2024-th-mb": "Ag Al B C Co Cr Cu Fe Hf Li Mg Mn Mo Ni O Si Sn Ti V Zn Zr",
    "panmg-2022-th-mb": "Ag Al Bi C Ca Ce Co Cu Dy Er Fe Gd La Li Mg Mn Nd Ni O P Pr Sb Sc Se Si Sm Sn Sr Y Zn Zr",
    "panmg-2024-th-mb": "Ag Al Bi C Ca Ce Co Cu Dy Er Fe Gd La Li Mg Mn Nd Ni O P Pr Sb Sc Se Si Sm Sn Sr Y Zn Zr",
    "panni-2020-th": "Al B C Co Cr Cu Fe Hf Ir Mn Mo N Nb Ni Pt Re Ru Si Ta Ti W Zr",
    "panni-2022-th-mb": "Al B C Co Cr Cu Fe Hf Ir Mn Mo N Nb Ni O P Pt Re Ru S Si Ta Ti V W Y Zr",
    "panni-2023-th-mb": "Al B C Co Cr Cu Fe Hf Ir Mn Mo N Nb Ni O P Pt Re Ru S Si Ta Ti V W Y Zr",
    "panni-2024-th-mb": "Al B C Co Cr Cu Fe Hf Ir Mn Mo N Nb Ni O P Pt Re Ru S Si Ta Ti V W Y Zr",
    "panrhea-2023a-th-mb": "Al B C Co Cr Cu Fe H Hf Mn Mo N Nb Ni O Si Ta Ti V W Zr",
    "panti-2023-th-mb": "Al B C Cr Cu Fe H Hf Mn Mo N Nb Ni O Si Sn Ta Ti V W Zr",
    "pantial-2021-th-mb": "Al B C Cr Mn Mo N Nb O Si Sn Ta Ti V W Zr",
    "panzr-2023-th-mb": "Cu Fe Nb Ni O Sn V Zr",
}


def test_catalog_keeps_lf_bytes_on_windows_runner() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert "config/databases.json text eol=lf" in attributes.splitlines()


def test_local_catalog_records_all_pandat_verified_databases() -> None:
    catalog = load_catalog(CATALOG_PATH)

    assert catalog.schema_version == 1
    assert len(catalog.databases) == 21
    assert catalog.default().id == "panhea-2024-th-mb"
    assert set(catalog.by_id) == set(EXPECTED_ELEMENTS)
    for database_id, expected in EXPECTED_ELEMENTS.items():
        database = catalog.by_id[database_id]
        assert database.elements == tuple(expected.split())
        assert database.enabled is True
        assert database.format == "pdb"
        assert database.file_path.is_absolute()
        assert database.file_path.suffix.lower() == ".pdb"
        assert len(database.sha256) == 64
    assert catalog.by_id["panhea-2024-th-mb"].file_path == Path(
        r"D:\PandatData\PanHEA2024_TH+MB.pdb"
    )


def test_catalog_digest_is_sha256_of_exact_bytes() -> None:
    raw = CATALOG_PATH.read_bytes()

    assert catalog_digest(raw) == hashlib.sha256(raw).hexdigest()
    assert parse_catalog(raw) == load_catalog(CATALOG_PATH)
    assert load_catalog(CATALOG_PATH).require_enabled("panhea-2024-th-mb").default


def test_catalog_rejects_duplicate_database_ids(tmp_path: Path) -> None:
    entry = {
        "id": "duplicate",
        "display_name": "Duplicate",
        "format": "pdb",
        "file_path": r"D:\PandatData\Duplicate.pdb",
        "sha256": "0" * 64,
        "elements": ["Fe", "Ni"],
        "enabled": True,
        "default": True,
    }
    path = tmp_path / "databases.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-10-28",
                "source": "test",
                "databases": [entry, {**entry, "default": False}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CatalogError, match="duplicate database id"):
        load_catalog(path)


def test_catalog_requires_exactly_one_enabled_default(tmp_path: Path) -> None:
    path = tmp_path / "databases.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-10-28",
                "source": "test",
                "databases": [
                    {
                        "id": "only",
                        "display_name": "Only",
                        "format": "pdb",
                        "file_path": r"D:\PandatData\Only.pdb",
                        "sha256": "0" * 64,
                        "elements": ["Fe", "Ni"],
                        "enabled": True,
                        "default": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CatalogError, match="exactly one enabled default"):
        load_catalog(path)
