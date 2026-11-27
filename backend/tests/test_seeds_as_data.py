"""Identical-seed test (plan 123.5): the JSON files ARE the seeds.

The pydantic-validated loader in ``app/seeds/data.py`` must reproduce
exactly the committed JSON payload — validation may reject, never rewrite.
Tampered payloads must fail loudly at load.

The job catalog and its taxonomy are a versioned seed pack (plan 224), not
bundled files; this test covers the four remaining reference banks.
"""

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from app.seeds import assessment, cv_templates, metrics, skill_packs
from app.seeds.data import (
    SEEDS_DIR,
    MetricDimension,
    load_seed,
    seed_list,
)

#: module constant <-> (seed file, key) pairs — the bundled seed surface.
PAIRS = [
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


def test_loading_is_deterministic():
    first = seed_list(MetricDimension, "metrics", "DIMENSIONS")
    second = seed_list(MetricDimension, "metrics", "DIMENSIONS")
    assert first == second


def test_tampered_seed_fails_validation():
    payload = load_seed("metrics")
    del payload["DIMENSIONS"][0]["label"]  # required field — never valid
    with pytest.raises(ValidationError):
        TypeAdapter(list[MetricDimension]).validate_python(payload["DIMENSIONS"])


def test_unknown_seed_keys_are_rejected():
    payload = load_seed("metrics")
    payload["DIMENSIONS"][0]["mystery"] = True
    with pytest.raises(ValidationError):
        TypeAdapter(list[MetricDimension]).validate_python(payload["DIMENSIONS"])


def test_every_seed_file_is_registered():
    """No orphan JSON: every file in app/data/seeds is loaded by a module."""
    expected = {
        "assessment.json",
        "cv_templates.json",
        "metrics.json",
        "skill_packs.json",
    }
    assert {p.name for p in SEEDS_DIR.glob("*.json")} == expected
