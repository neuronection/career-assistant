"""The vendored family seed-pack manifest contract (ADR-0056).

The generic manifest schema/fixtures are family-owned (the canonical contract)
and vendored byte-identically; career's item parser is the app-side adapter for
ats_presets/endpoint_descriptors. This test pins the schema's parity with the
parser constants and proves career manifests validate against it.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from app.core.seed_pack.manifest import LICENSES, SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts" / "seed-pack.schema.json"
FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "seed_packs"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    jsonschema.validate(manifest, _schema())


def test_career_manifests_validate_against_the_family_schema():
    _validate(ROOT / "backend" / "app" / "data" / "seed_packs" / "bundled" / "manifest.json")
    for manifest in sorted(FIXTURES.glob("packs/*/*/manifest.json")):
        _validate(manifest)


def test_schema_constants_match_the_parser():
    schema = _schema()
    assert schema["$id"] == "https://neuronection.com/contracts/seed-pack.schema.json"
    assert set(schema["properties"]["license"]["enum"]) == LICENSES
    assert schema["properties"]["schema_version"]["enum"] == [SCHEMA_VERSION]
    assert schema["properties"]["priority"]["minimum"] == 0
    assert schema["properties"]["priority"]["maximum"] == 999
    assert set(schema["required"]) == {
        "id",
        "schema_version",
        "version",
        "license",
        "scope",
        "priority",
        "item_files",
    }
