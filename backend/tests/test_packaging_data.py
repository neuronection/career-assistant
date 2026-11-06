"""The packaged bundle carries every builtin extension data file.

The registry validates each builtin ``manifest.json`` at registration and
fails closed, so a frozen build that omits them cannot start. PyInstaller
does not collect sibling data files, so the spec adds them through
``packaging/bundle_data.py``; this test pins that projection.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGING = REPO_ROOT / "packaging"
BUILTIN = REPO_ROOT / "backend" / "app" / "extensions" / "builtin"
SPEC = PACKAGING / "career-assistant.spec"


def _bundle_data():
    spec = importlib.util.spec_from_file_location(
        "career_packaging_bundle_data", PACKAGING / "bundle_data.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_builtin_manifest_and_doc_tree_is_packaged():
    entries = _bundle_data().builtin_data_entries(REPO_ROOT)
    included = {Path(source).resolve() for source, _ in entries}
    expected = {
        path.resolve()
        for path in BUILTIN.rglob("*")
        if path.is_file() and path.suffix in {".json", ".md"} and "__pycache__" not in path.parts
    }
    missing = sorted(str(path.relative_to(REPO_ROOT)) for path in expected - included)
    assert not missing, f"builtin data files missing from the frozen bundle: {missing}"


def test_bundle_entries_land_under_the_extension_package():
    entries = _bundle_data().builtin_data_entries(REPO_ROOT)
    assert entries
    for source, destination in entries:
        assert destination == "app/extensions/builtin" or destination.startswith(
            "app/extensions/builtin/"
        ), (source, destination)
        assert "__pycache__" not in source
        assert not source.endswith(".pyc")


def test_the_spec_uses_the_shared_projection():
    text = SPEC.read_text(encoding="utf-8")
    assert "from bundle_data import builtin_data_entries" in text
    assert "builtin_data_entries(Path(ROOT))" in text
