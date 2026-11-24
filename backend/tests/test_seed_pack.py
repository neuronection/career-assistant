"""Plan 218: seed-pack parser, digest, caps and archive guards."""

from __future__ import annotations

import io
import json
import stat
import zipfile
from pathlib import Path

import pytest
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ValidationError
from app.core.seed_pack.archive import build_pack_archive, extract_pack_archive
from app.core.seed_pack.errors import SeedPackError
from app.core.seed_pack.export import canonical_export, read_pack_dir
from app.core.seed_pack.manifest import (
    MAX_PRESETS_PER_FILE,
    parse_pack,
    parse_repo_index,
    sha256_hex,
)

FIXTURES = Path(__file__).parent / "fixtures" / "seed_packs"


class _RecruiteeConfig(BaseModel):
    company: str = Field(min_length=1, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


class _FakeConnector:
    def __init__(self, key: str, domains: tuple[str, ...], model: type[BaseModel] | None = None):
        self.key = key
        self.domains = domains
        self.model = model

    def validate_config(self, config: dict) -> dict:
        if self.model is None:
            return {}
        try:
            return self.model.model_validate(config).model_dump(mode="json")
        except PydanticValidationError as exc:
            raise ValidationError(str(exc)) from exc

    def manifest(self) -> dict:
        return {"domains": list(self.domains)}


CONNECTORS = {
    "recruitee": _FakeConnector("recruitee", ("*.recruitee.com",), _RecruiteeConfig),
    "ats_api": _FakeConnector("ats_api", ("boards-api.greenhouse.io", "api.lever.co"), None),
}


def _preset(**over):
    item = {
        "seed_key": "ats-preset:acme",
        "slug": "acme",
        "name": "Acme",
        "connector_key": "recruitee",
        "platform": "Recruitee",
        "category": "ats",
        "country": "GR",
        "config": {"company": "acme"},
    }
    item.update(over)
    return item


def _endpoint(**over):
    item = {
        "seed_key": "endpoint:acme",
        "label": "Acme jobs",
        "connector_key": "ats_api",
        "server": "https://boards-api.greenhouse.io",
        "method": "GET",
        "path": "/v1/boards/{org}/jobs",
        "auth": "none",
        "params": [{"name": "org", "required": True}],
    }
    item.update(over)
    return item


def _envelope(format: str, items: list, *, item_type: str | None = None) -> dict:
    return {
        "metadata": {
            "item_type": item_type or format,
            "format": format,
            "format_version": 1,
            "dataset_vintage": "2026-11-24",
            "license": "CC-BY-4.0",
        },
        "items": items,
    }


def _pack(files: dict[str, dict], *, manifest: dict | None = None) -> dict[str, bytes]:
    manifest_files = []
    raw: dict[str, bytes] = {}
    for path, envelope in files.items():
        data = json.dumps(envelope, sort_keys=True).encode()
        raw[path] = data
        manifest_files.append({"path": path, "sha256": sha256_hex(data)})
    header = {
        "id": "test-pack",
        "schema_version": "1.0",
        "version": "1.0.0",
        "license": "CC-BY-4.0",
        "scope": "system",
        "priority": 100,
        "item_files": manifest_files,
    }
    header.update(manifest or {})
    raw["manifest.json"] = json.dumps(header, sort_keys=True).encode()
    return raw


def _presets_file(items: list) -> dict[str, dict]:
    return {"items/ats_presets/acme.json": _envelope("ats_presets", items)}


def test_published_packs_reproduce_their_index_digests():
    index = parse_repo_index((FIXTURES / "seed-repo.json").read_bytes())
    for indexed in index.packs:
        parsed = parse_pack(read_pack_dir(FIXTURES / indexed.path))
        assert parsed.manifest.id == indexed.id
        assert parsed.manifest.version == indexed.version
        assert parsed.digest == indexed.digest
        assert parsed.item_types == set(indexed.itemTypes)


def test_seed_key_grammar_and_prefix():
    for key in ("ats-preset:acme:extra", "ats-preset:", "endpoint:acme", "Ats-Preset:acme"):
        with pytest.raises(SeedPackError) as exc:
            parse_pack(_pack(_presets_file([_preset(seed_key=key)])), connectors=CONNECTORS)
        assert exc.value.code == "IDENTITY_INVALID"


def test_duplicate_seed_keys_are_refused():
    files = _pack(_presets_file([_preset(), _preset(slug="acme-two")]))
    with pytest.raises(SeedPackError) as exc:
        parse_pack(files, connectors=CONNECTORS)
    assert exc.value.code == "SEED_KEY_DUPLICATE"


def test_unknown_connector_is_refused():
    files = _pack(_presets_file([_preset(connector_key="nope")]))
    with pytest.raises(SeedPackError) as exc:
        parse_pack(files, connectors=CONNECTORS)
    assert exc.value.code == "CONNECTOR_UNKNOWN"


def test_connector_config_is_validated():
    files = _pack(_presets_file([_preset(config={"company": "Not A Slug"})]))
    with pytest.raises(SeedPackError) as exc:
        parse_pack(files, connectors=CONNECTORS)
    assert exc.value.code == "CONFIG_INVALID"


def test_license_mismatch_is_refused():
    files = _pack(_presets_file([_preset()]), manifest={"license": "MIT"})
    with pytest.raises(SeedPackError) as exc:
        parse_pack(files, connectors=CONNECTORS)
    assert exc.value.code == "LICENSE_NOT_ALLOWED"


def test_scope_and_priority_are_coherent():
    files = _pack(_presets_file([_preset()]), manifest={"scope": "tenant"})
    with pytest.raises(SeedPackError) as exc:
        parse_pack(files, connectors=CONNECTORS)
    assert exc.value.code == "SCOPE_UNSUPPORTED"

    with pytest.raises(SeedPackError) as exc:
        parse_pack(_pack(_presets_file([_preset()])), connectors=CONNECTORS, source_priority=0)
    assert exc.value.code == "PRIORITY_MISMATCH"


def test_locale_rules():
    with pytest.raises(SeedPackError) as exc:
        parse_pack(
            _pack(_presets_file([_preset(category="remote", worldwide=True, countries=["GR"])])),
            connectors=CONNECTORS,
        )
    assert exc.value.code == "IDENTITY_INVALID"

    with pytest.raises(SeedPackError) as exc:
        parse_pack(_pack(_presets_file([_preset(country=None)])), connectors=CONNECTORS)
    assert exc.value.code == "IDENTITY_INVALID"


def test_item_digest_mismatch_is_refused():
    files = _pack(_presets_file([_preset()]))
    files["items/ats_presets/acme.json"] = files["items/ats_presets/acme.json"] + b" "
    with pytest.raises(SeedPackError) as exc:
        parse_pack(files, connectors=CONNECTORS)
    assert exc.value.code == "DIGEST_MISMATCH"


def test_item_caps_are_enforced():
    items = [
        _preset(
            seed_key=f"ats-preset:acme-{index}",
            slug=f"acme-{index}",
            config={"company": "acme"},
        )
        for index in range(MAX_PRESETS_PER_FILE + 1)
    ]
    with pytest.raises(SeedPackError) as exc:
        parse_pack(_pack(_presets_file(items)), connectors=CONNECTORS)
    assert exc.value.code == "CAP_EXCEEDED"


def test_endpoint_must_sit_inside_the_connector_domains():
    files = _pack(
        {"items/endpoint_descriptors/acme.json": _envelope("endpoint_descriptors", [_endpoint()])}
    )
    assert parse_pack(files, connectors=CONNECTORS).items[0].seed_key == "endpoint:acme"

    files = _pack(
        {
            "items/endpoint_descriptors/acme.json": _envelope(
                "endpoint_descriptors", [_endpoint(server="https://evil.example.com")]
            )
        }
    )
    with pytest.raises(SeedPackError) as exc:
        parse_pack(files, connectors=CONNECTORS)
    assert exc.value.code == "ENDPOINT_DOMAIN_DENIED"


def test_unknown_formats_are_refused_or_stored():
    files = _pack(
        {"items/job_types/types.json": _envelope("job_types", [{"seed_key": "job-type:x"}])}
    )
    with pytest.raises(SeedPackError) as exc:
        parse_pack(files, connectors=CONNECTORS)
    assert exc.value.code == "FORMAT_UNSUPPORTED"

    parsed = parse_pack(files, connectors=CONNECTORS, allow_unknown_formats=True)
    assert parsed.items == ()
    assert parsed.digest.startswith("sha256:")


def test_canonical_export_is_byte_stable():
    source = read_pack_dir(FIXTURES / "packs/neuronection/greece-ats")
    first, parsed, digest = canonical_export(source)
    second, reparsed, second_digest = canonical_export(first)
    assert first == second
    assert digest == second_digest == parsed.digest == reparsed.digest
    assert parsed.manifest.id == "neuronection-greece-ats"


def test_archive_roundtrip_and_determinism():
    files = _pack(_presets_file([_preset()]))
    first = build_pack_archive(files)
    assert build_pack_archive(files) == first
    assert extract_pack_archive(first) == files


def _zip(entries: list[tuple[str, bytes, int]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            archive.writestr(info, data)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "name",
    ["../evil.json", "/manifest.json", "items/../../evil.json", "items\\evil.json"],
)
def test_archive_path_traversal_is_refused(name):
    with pytest.raises(SeedPackError) as exc:
        extract_pack_archive(_zip([(name, b"{}", 0o644)]))
    assert exc.value.code in {"ARCHIVE_PATH_TRAVERSAL", "ARCHIVE_UNSUPPORTED_ENTRY"}


def test_archive_unsupported_and_symlink_entries_are_refused():
    with pytest.raises(SeedPackError) as exc:
        extract_pack_archive(_zip([("manifest.json", b"{}", 0o644), ("README.md", b"x", 0o644)]))
    assert exc.value.code == "ARCHIVE_UNSUPPORTED_ENTRY"

    with pytest.raises(SeedPackError) as exc:
        extract_pack_archive(
            _zip([("manifest.json", b"{}", 0o644), ("items/x.json", b"{}", stat.S_IFLNK | 0o777)])
        )
    assert exc.value.code == "ARCHIVE_UNSUPPORTED_ENTRY"


def test_archive_entry_cap_is_refused():
    entries = [("manifest.json", b"{}", 0o644)]
    entries += [(f"items/{index}.json", b"{}", 0o644) for index in range(513)]
    with pytest.raises(SeedPackError) as exc:
        extract_pack_archive(_zip(entries))
    assert exc.value.code == "ARCHIVE_TOO_LARGE"


def test_archive_requires_the_manifest():
    with pytest.raises(SeedPackError) as exc:
        extract_pack_archive(_zip([("items/x.json", b"{}", 0o644)]))
    assert exc.value.code == "ARCHIVE_UNSUPPORTED_ENTRY"
