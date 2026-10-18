"""Builtin connector manifests are FILES at the bundle root (the family
form — manifest.json, never code-declared). These tests pin the wall:

- every builtin ships ``builtin/<key>/manifest.json`` and it validates
  against the vendored bundled envelope at registration;
- the four documented builtins (the three real job boards + mcp) carry
  the plan-34 docs pointer, and their trees exist + validate;
- a missing or corrupt manifest file, and a broken docs promise,
  self-disable exactly like an invalid manifest did (the registration
  gate throws the same ``ValidationError``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.extensions import contract
from app.extensions.builtin import (
    AtsApiConnector,
    CsvConnector,
    JsonLdConnector,
    ManualUrlConnector,
    RssConnector,
)
from app.extensions.builtin.job_boards import (
    ArbeitnowConnector,
    JobicyConnector,
    RemotiveConnector,
)
from app.extensions.builtin.mcp import McpConnector
from app.extensions.registry import _BUILTINS, _validate_docs_binding, validate_manifest
from app.extensions.sdk import PostingConnector, manifest_path

BUILTIN_ROOT = Path(__file__).resolve().parents[1] / "app" / "extensions" / "builtin"

BUILTINS = [
    AtsApiConnector(),
    JsonLdConnector(),
    RssConnector(),
    CsvConnector(),
    ManualUrlConnector(),
    ArbeitnowConnector(),
    RemotiveConnector(),
    JobicyConnector(),
    McpConnector(),
]

DOCUMENTED = {"arbeitnow", "remotive", "jobicy", "mcp"}


def test_every_builtin_manifest_is_a_file_that_validates():
    assert len(BUILTINS) == 9
    for connector in BUILTINS:
        path = manifest_path(connector)
        assert path.is_file(), f"{connector.key}: manifest.json missing at {path}"
        manifest = validate_manifest(connector)
        assert manifest["id"] == f"career-{connector.key.replace('_', '-')}"
        assert manifest["author"] == "Neuronection"
        assert manifest["categories"], f"{connector.key}: browse categories carried"


def test_the_documented_builtins_carry_valid_docs_trees():
    pointed = 0
    for connector in BUILTINS:
        manifest = connector.manifest()
        pointer = manifest.get("docs")
        if pointer is None:
            assert connector.key not in DOCUMENTED, (
                f"{connector.key} was documented in the manifest-unification wave"
            )
            continue
        pointed += 1
        _validate_docs_binding(connector, manifest)  # raises on any broken promise
    assert pointed == len(DOCUMENTED)
    assert {c.key for c in _BUILTINS} == {c.key for c in BUILTINS}


def _stub(key: str, manifest_file: str | Path | None = None) -> PostingConnector:
    class Stub(PostingConnector):
        pass

    stub = Stub()
    stub.key = key
    stub.manifest_file = manifest_file
    return stub


def test_missing_manifest_file_disables_registration_the_same_way(tmp_path):
    (tmp_path / "orphan").mkdir()
    connector = _stub("no_such_builtin")
    with pytest.raises(ValidationError, match="manifest file unavailable"):
        validate_manifest(connector)


def test_corrupt_manifest_file_disables_registration(tmp_path):
    bad = tmp_path / "manifest.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValidationError, match="manifest file unavailable"):
        validate_manifest(_stub("corrupt", manifest_file=bad))


def test_envelope_invalid_manifest_file_disables_registration(tmp_path):
    bad = tmp_path / "manifest.json"
    bad.write_text(json.dumps({"id": "career-x", "kind": "connector"}), encoding="utf-8")
    with pytest.raises(ValidationError, match="manifest invalid"):
        validate_manifest(_stub("x", manifest_file=bad))


def test_docs_pointer_without_tree_disables_registration(tmp_path):
    manifest = json.loads((BUILTIN_ROOT / "arbeitnow" / "manifest.json").read_text())
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValidationError, match="tree is unreadable"):
        _validate_docs_binding(
            _stub("arbeitnow", manifest_file=tmp_path / "manifest.json"), manifest
        )


def test_docs_pointer_with_invalid_tree_disables_registration(tmp_path):
    manifest = json.loads((BUILTIN_ROOT / "mcp" / "manifest.json").read_text())
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "docs-tree.json").write_text(
        json.dumps({"version": 1, "categories": [{"category": "getting-started", "items": []}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="docs tree invalid"):
        _validate_docs_binding(_stub("mcp", manifest_file=tmp_path / "manifest.json"), manifest)


def test_docs_tree_files_resolve_beside_the_tree():
    for key in sorted(DOCUMENTED):
        docs_dir = BUILTIN_ROOT / key / "docs"
        tree = json.loads((docs_dir / "docs-tree.json").read_text())
        problems = contract.docs_tree_semantics(
            tree, exists=lambda ref, d=docs_dir: (d / ref).is_file()
        )
        assert problems == [], f"{key}: {problems}"
