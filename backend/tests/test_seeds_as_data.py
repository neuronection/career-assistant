"""Identical-seed test (plan 123.5): the JSON files ARE the seeds.

The pydantic-validated loader in ``app/seeds/data.py`` must reproduce
exactly the committed JSON payload — validation may reject, never
rewrite. Tampered payloads must fail loudly at load.
"""

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from app.seeds import assessment, catalog, cv_templates, metrics, skill_packs, taxonomy
from app.seeds.data import (
    SEEDS_DIR,
    InterestTag,
    Job,
    Relation,
    load_seed,
    seed_list,
)

#: module constant <-> (seed file, key) pairs — the full seed surface.
PAIRS = [
    (taxonomy, "INTEREST_TAGS", "taxonomy"),
    (taxonomy, "SKILL_TAGS", "taxonomy"),
    (catalog, "FAMILIES", "catalog"),
    (catalog, "JOBS", "catalog"),
    (catalog, "RELATIONS", "catalog"),
    (catalog, "PATHS", "catalog"),
    (assessment, "BANK_QUESTIONS", "assessment"),
    (cv_templates, "BANK_TEMPLATES", "cv_templates"),
    (metrics, "DIMENSIONS", "metrics"),
    (skill_packs, "BANK_PACKS", "skill_packs"),
]


def _jsonable(value):
    """Normalize in-memory values (tuples) to their JSON shape."""
    return json.loads(json.dumps(value, default=list if isinstance(value, tuple) else str))


@pytest.mark.parametrize("module, key, name", PAIRS)
def test_seed_json_is_identical_to_the_module_constant(module, key, name):
    payload = load_seed(name)[key]
    assert _jsonable(getattr(module, key)) == payload


def test_experience_years_round_trips_tuples():
    payload = load_seed("catalog")["EXPERIENCE_YEARS"]
    assert {k: list(v) for k, v in catalog.EXPERIENCE_YEARS.items()} == payload


def test_loading_is_deterministic():
    first = seed_list(Job, "catalog", "JOBS")
    second = seed_list(Job, "catalog", "JOBS")
    assert first == second


def test_tampered_seed_fails_validation():
    payload = load_seed("catalog")
    del payload["JOBS"][0]["title"]  # required field — never valid
    with pytest.raises(ValidationError):
        TypeAdapter(list[Job]).validate_python(payload["JOBS"])


def test_unknown_seed_keys_are_rejected():
    payload = load_seed("taxonomy")
    payload["INTEREST_TAGS"][0]["mystery"] = True
    with pytest.raises(ValidationError):
        TypeAdapter(list[InterestTag]).validate_python(payload["INTEREST_TAGS"])


def test_every_seed_file_is_registered():
    """No orphan JSON: every file in app/data/seeds is loaded by a module."""
    expected = {
        "taxonomy.json",
        "catalog.json",
        "assessment.json",
        "cv_templates.json",
        "metrics.json",
        "skill_packs.json",
    }
    assert {p.name for p in SEEDS_DIR.glob("*.json")} == expected


def test_relation_aliases_round_trip():
    rows = seed_list(Relation, "catalog", "RELATIONS")
    assert {"from", "to"} <= set(rows[0])
