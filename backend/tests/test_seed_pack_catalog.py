"""Plan 224 S1: catalog formats parse, the key grammar, and `replaces`."""

from __future__ import annotations

import pytest

from app.core.seed_pack.errors import SeedPackError
from app.core.seed_pack.manifest import (
    CATALOG_FORMATS,
    FORMATS,
    parse_pack,
)
from app.models.enums.catalog import RelationType
from app.seeds.relation_keys import (
    relation_seed_key,
    relation_type_from_slug,
    relation_type_slug,
)
from tests.test_seed_pack import CONNECTORS, _envelope, _pack


def _catalog_envelope(format: str, items: list, version: int = 1) -> dict:
    envelope = _envelope(format, items)
    envelope["metadata"]["format_version"] = version
    return envelope


FAMILY = {
    "seed_key": "job-family:data",
    "key": "data",
    "label": "Data",
    "parent_key": None,
    "description": "Data roles.",
}
JOB_TYPE = {
    "seed_key": "job-type:data-analyst",
    "code": "data-analyst",
    "title": "Data Analyst",
    "family_key": "data",
    "summary": "Turns data into decisions.",
    "attributes": {"experience_typical_years": [0, 3], "work_style": "analytical"},
    "skills": [{"skill_key": "sql", "required_level": 5, "importance": "important"}],
    "interests": ["science-physics"],
}
RELATION = {
    "seed_key": "job-relation:data-analyst/ml-engineer/similar-to",
    "from": "data-analyst",
    "to": "ml-engineer",
    "type": "similar_to",
    "weight": 0.6,
    "rationale": "Both work with data.",
}
PATH = {
    "seed_key": "career-path:software-developer/classic-study-route",
    "job": "software-developer",
    "title": "The classic study route",
    "description": "School, degree, junior role.",
    "steps": [{"kind": "education", "label": "Computer science degree"}],
}
SKILL = {"seed_key": "skill:sql", "key": "sql", "label": "SQL", "category": "technical"}
INTEREST = {
    "seed_key": "interest:science-physics",
    "key": "science-physics",
    "label": "Physics",
    "category": "science",
}


def _catalog_pack(**overrides: dict) -> dict[str, bytes]:
    files = {
        "items/job_families/families.json": _catalog_envelope("job_families", [FAMILY]),
        "items/job_types/jobs.json": _catalog_envelope("job_types", [JOB_TYPE], version=2),
        "items/job_relations/relations.json": _catalog_envelope("job_relations", [RELATION]),
        "items/career_paths/paths.json": _catalog_envelope("career_paths", [PATH]),
        "items/skills/skills.json": _catalog_envelope("skills", [SKILL]),
        "items/interest_tags/interests.json": _catalog_envelope("interest_tags", [INTEREST]),
    }
    files.update(overrides)
    return _pack(files, manifest={"version": "2.0.0"})


def test_all_six_catalog_formats_parse_and_keep_the_wire_aliases():
    parsed = parse_pack(_catalog_pack(), connectors=CONNECTORS)
    assert parsed.item_types == set(CATALOG_FORMATS)
    by_type = {item.item_type: item.payload for item in parsed.items}
    assert by_type["job_relations"]["from"] == "data-analyst"
    assert by_type["job_relations"]["type"] == "similar_to"
    assert by_type["career_paths"]["job"] == "software-developer"
    assert by_type["job_types"]["skills"][0]["required_level"] == 5
    assert by_type["job_types"]["attributes"]["experience_typical_years"] == [0, 3]


def test_catalog_formats_are_registered_parse_only():
    for format in CATALOG_FORMATS:
        entries = [spec for (name, _v), spec in FORMATS.items() if name == format]
        assert entries, format
        assert all(spec.catalog for spec in entries)
        assert all(spec.adapter is None for spec in entries)


def test_catalog_key_prefixes_are_enforced():
    bad = dict(FAMILY, seed_key="job-type:data")
    with pytest.raises(SeedPackError) as exc:
        parse_pack(
            _pack({"items/job_families/families.json": _catalog_envelope("job_families", [bad])}),
            connectors=CONNECTORS,
        )
    assert exc.value.code == "IDENTITY_INVALID"


def test_a_catalog_item_type_must_match_its_format():
    envelope = _catalog_envelope("job_families", [FAMILY])
    envelope["metadata"]["item_type"] = "skills"
    with pytest.raises(SeedPackError) as exc:
        parse_pack(_pack({"items/job_families/families.json": envelope}), connectors=CONNECTORS)
    assert exc.value.code == "ITEM_TYPE_MISMATCH"


def test_an_unregistered_catalog_version_is_reported_as_skipped():
    envelope = _catalog_envelope("job_types", [JOB_TYPE], version=1)
    parsed = parse_pack(
        _pack({"items/job_types/jobs.json": envelope}),
        connectors=CONNECTORS,
        allow_unknown_formats=True,
    )
    assert parsed.items == ()
    assert ("job_types", 1) in parsed.skipped_formats


def test_replaces_accepts_bare_bodies_and_the_legacy_dot_form_as_a_body():
    bare = parse_pack(
        _pack(
            {"items/job_families/families.json": _catalog_envelope("job_families", [FAMILY])},
            manifest={"replaces": ["data-old"]},
        ),
        connectors=CONNECTORS,
    )
    assert bare.manifest.replaces == ["data-old"]
    dotted = parse_pack(
        _pack(
            {"items/job_families/families.json": _catalog_envelope("job_families", [FAMILY])},
            manifest={"replaces": ["ats-preset.old-slug"]},
        ),
        connectors=CONNECTORS,
    )
    assert dotted.manifest.replaces == ["ats-preset.old-slug"]


@pytest.mark.parametrize("bad", ["Old-Job", "job:old", "old job", ""])
def test_replaces_rejects_malformed_bodies(bad):
    with pytest.raises(SeedPackError) as exc:
        parse_pack(
            _pack(
                {"items/job_families/families.json": _catalog_envelope("job_families", [FAMILY])},
                manifest={"replaces": [bad]},
            ),
            connectors=CONNECTORS,
        )
    assert exc.value.code == "IDENTITY_INVALID"


def test_relation_type_codec_round_trips_every_type():
    for member in RelationType:
        slug = relation_type_slug(member.value)
        assert "_" not in slug
        assert relation_type_from_slug(slug) == member.value
    with pytest.raises(ValueError):
        relation_type_slug("not_a_type")


def test_relation_seed_keys_parse_for_every_type():
    for member in RelationType:
        key = relation_seed_key("data-analyst", "ml-engineer", member.value)
        item = dict(RELATION, seed_key=key, type=member.value)
        parsed = parse_pack(
            _pack(
                {"items/job_relations/relations.json": _catalog_envelope("job_relations", [item])}
            ),
            connectors=CONNECTORS,
        )
        assert parsed.items[0].seed_key == key
