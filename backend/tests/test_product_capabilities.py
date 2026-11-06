"""The product capability showcase wall (plan 43): ``docs/capabilities.json``
validates against the vendored product-capabilities contract and passes the
host semantics the schema cannot express — unique capability ids, the
project slug matches this repo, and only shipped capabilities claim
metrics/proofs (the schema's own status $comment, pinned repo-side).

Mirrors ``test_extension_docs_tree.py``: the validator is the vendored
``app/extensions.contract`` module (stdlib-only, byte-identical from the
dev repo), and the schema copy at
``contracts/product-capabilities.schema.json`` is vendored canonical-first
and never edited in-repo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.extensions import contract

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"
CAPABILITIES = REPO_ROOT / "docs" / "capabilities.json"

CAPABILITIES_SCHEMA = json.loads(
    (CONTRACTS_DIR / "product-capabilities.schema.json").read_text(encoding="utf-8")
)

PROJECT_SLUG = "career"

MUST_MOVE_WITH_FEATURES = (
    "docs/capabilities.json must be updated in the same change as a shipped "
    "feature (family contract: contracts/product-capabilities.schema.json)"
)


def capabilities_semantics(
    doc: dict[str, Any],
    *,
    expected_project: str = PROJECT_SLUG,
) -> list[str]:
    """The cross-key rules JSON Schema cannot express (the host-side twin
    of dev's wall, mirroring the invalid fixtures' semantics channel):
    the project slug matches this repo and capability ids are unique,
    and non-shipped capabilities claim no metrics or proofs."""
    problems: list[str] = []
    if doc.get("project") != expected_project:
        problems.append(
            f"$.project: {doc.get('project')!r} does not match this repo ({expected_project!r})"
        )
    ids = [cap.get("id") for cap in doc.get("capabilities") or []]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        problems.append(f"$.capabilities: duplicate capability ids {dupes}")
    for cap in doc.get("capabilities") or []:
        if not isinstance(cap, dict):
            continue
        if cap.get("status") != "shipped" and (cap.get("proofs") or cap.get("metric")):
            problems.append(
                f"$.capabilities[{cap.get('id')!r}]: status {cap.get('status')!r} "
                "claims metrics/proofs — only shipped capabilities may"
            )
        visual = cap.get("visual")
        if isinstance(visual, str) and (
            visual.startswith("/") or "\\" in visual or ".." in visual.split("/")
        ):
            problems.append(
                f"$.capabilities[{cap.get('id')!r}]: visual {visual!r} "
                "escapes the manifest directory"
            )
    return problems


# ---------------------------------------------------- career's real document


def test_capabilities_document_exists_and_parses() -> None:
    assert CAPABILITIES.is_file(), MUST_MOVE_WITH_FEATURES
    json.loads(CAPABILITIES.read_text(encoding="utf-8"))


def test_capabilities_validate_against_the_vendored_contract() -> None:
    doc = json.loads(CAPABILITIES.read_text(encoding="utf-8"))
    err = contract.validate(CAPABILITIES_SCHEMA, doc, CAPABILITIES_SCHEMA)
    assert err is None, f"{MUST_MOVE_WITH_FEATURES}: {err}"


def test_capabilities_pass_the_host_semantics() -> None:
    doc = json.loads(CAPABILITIES.read_text(encoding="utf-8"))
    problems = capabilities_semantics(doc)
    assert not problems, f"{MUST_MOVE_WITH_FEATURES}: {problems}"


def test_capability_visuals_resolve_beside_the_manifest() -> None:
    """A `visual` capture is a real file beside ``docs/capabilities.json``
    (the hub vendors it by this path)."""
    doc = json.loads(CAPABILITIES.read_text(encoding="utf-8"))
    missing = [
        cap["visual"]
        for cap in doc.get("capabilities") or []
        if isinstance(cap, dict)
        and cap.get("visual")
        and not (CAPABILITIES.parent / cap["visual"]).is_file()
    ]
    assert not missing, f"{MUST_MOVE_WITH_FEATURES}: visual capture(s) missing: {missing}"


# -------------------------------------------- the contract's own fixture suite


def test_contract_fixtures_stay_honest() -> None:
    """The vendored fixture wall (mirror of dev wall 14 / the sibling
    suites): every valid case passes schema + semantics, every invalid
    case is rejected by schema or semantics."""
    fixtures = json.loads(
        (CONTRACTS_DIR / "product-capabilities.fixtures.json").read_text(encoding="utf-8")
    )
    for case in fixtures["valid"]:
        assert contract.validate(CAPABILITIES_SCHEMA, case["doc"], CAPABILITIES_SCHEMA) is None, (
            f"fixture {case['name']!r} must stay valid against the contract"
        )
        assert not capabilities_semantics(
            case["doc"], expected_project=case["doc"].get("project", "")
        ), f"fixture {case['name']!r} must stay semantically clean"
    for case in fixtures["invalid"]:
        rejected = contract.validate(
            CAPABILITIES_SCHEMA, case["doc"], CAPABILITIES_SCHEMA
        ) is not None or bool(
            capabilities_semantics(
                case["doc"],
                expected_project=case.get("expectProject", case["doc"].get("project", "")),
            )
        )
        assert rejected, f"fixture {case['name']!r} must stay invalid against the contract"


def test_semantics_reject_a_visual_escaping_the_manifest() -> None:
    """The schema pattern is the first wall; the semantics must reject the
    escape independently of it (the fixture wall short-circuits on the
    schema channel and never reaches this branch)."""
    problems = capabilities_semantics(
        _doc(capabilities=[_capability(visual="../backend/secret.png")])
    )
    assert any("escapes the manifest directory" in problem for problem in problems), problems


# ------------------------------------- the semantics helper's own self-checks


def _capability(**overrides: Any) -> dict[str, Any]:
    capability: dict[str, Any] = {
        "id": "explore-careers",
        "verb": "Discover careers you didn't know exist",
        "summary": "A structured job catalog you can browse by field, skill and lifestyle.",
        "category": "discover",
        "status": "shipped",
        "order": 10,
    }
    capability.update(overrides)
    return capability


def _doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "version": 1,
        "project": "career",
        "capabilities": [_capability()],
    }
    doc.update(overrides)
    return doc


SEMANTIC_CASES = [
    (
        "duplicate-capability-id",
        _doc(capabilities=[_capability(), _capability(order=20)]),
        {},
        "duplicate capability ids",
    ),
    (
        "project-mismatch-with-repo",
        _doc(project="study"),
        {},
        "does not match this repo",
    ),
    (
        "proofs-on-planned",
        _doc(capabilities=[_capability(status="planned", proofs=["Some verifiable fact here"])]),
        {},
        "only shipped capabilities may",
    ),
]


@pytest.mark.parametrize(
    ("name", "doc", "kwargs", "expected"),
    SEMANTIC_CASES,
    ids=[case[0] for case in SEMANTIC_CASES],
)
def test_semantics_channel_catches_the_unstructureable(
    name: str, doc: dict[str, Any], kwargs: dict[str, Any], expected: str
) -> None:
    """Each case passes the schema (the structural gate is green) and must
    still be rejected by the semantics — the checks JSON Schema cannot
    express, exactly the split the contract's invalid fixtures encode."""
    assert contract.validate(CAPABILITIES_SCHEMA, doc, CAPABILITIES_SCHEMA) is None, (
        f"{name}: expected the schema channel to accept this case"
    )
    problems = capabilities_semantics(doc, **kwargs)
    assert any(expected in problem for problem in problems), (
        f"{name}: semantics accepted the case, expected {expected!r}"
    )


def test_semantics_accept_a_clean_minimal_document() -> None:
    problems = capabilities_semantics(_doc())
    assert problems == []
