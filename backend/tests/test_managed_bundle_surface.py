"""Plan 131 — managed-bundle config surface: a source minted from an
imported bundle exposes the bundle manifest's configSchema (shape only,
never values) so the form is the bundle's own settings form."""

import json

from app.api.v1.admin import _source_view
from app.models.posting_model import JobSource

BUNDLE_MANIFEST = {
    "apiVersion": "extension/v1",
    "kind": "connector",
    "id": "test-bundle",
    "version": "1.0.0",
    "description": "test bundle",
    "author": "t",
    "license": "MIT",
    "repository": "https://example.invalid/test-bundle",
    "capabilities": ["sync"],
    "configSchema": {
        "type": "object",
        "properties": {
            "keywords": {"type": "string", "title": "Keywords"},
            "max_pages": {"type": "number", "title": "Pages"},
        },
        "required": ["keywords"],
    },
    "entry": "server.py",
    "mcp": {"transport": "stdio"},
}


def _mint_managed_bundle(tmp_path, monkeypatch) -> str:
    from app.core.config import settings

    content = tmp_path / "extensions" / ("a" * 64)
    content.mkdir(parents=True)
    (content / "server.py").write_text("print('hi')\n")
    (content / "manifest.json").write_text(json.dumps(BUNDLE_MANIFEST))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    return f"python {content / 'server.py'}"


async def test_managed_source_view_exposes_bundle_schema(
    db, synthetic_connector, tmp_path, monkeypatch
):
    command = _mint_managed_bundle(tmp_path, monkeypatch)
    src = JobSource(
        key="mng",
        connector_key="synthetic",
        config={"transport": "stdio", "command": command},
        enabled=True,
    )
    db.add(src)
    await db.commit()
    await db.refresh(src)

    view = await _source_view(db, src)
    assert view["managed"] is True
    schema = view["tool_config_schema"]
    assert schema["required"] == ["keywords"]
    assert set(schema["properties"]) == {"keywords", "max_pages"}


async def test_plain_command_is_not_managed(db, synthetic_connector, tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    src = JobSource(
        key="plain",
        connector_key="synthetic",
        config={"transport": "stdio", "command": "python /tmp/elsewhere/server.py"},
        enabled=True,
    )
    db.add(src)
    await db.commit()
    await db.refresh(src)

    view = await _source_view(db, src)
    assert view["managed"] is False
    assert view["tool_config_schema"] is None


async def test_managed_values_roundtrip_through_options(
    db, synthetic_connector, tmp_path, monkeypatch
):
    command = _mint_managed_bundle(tmp_path, monkeypatch)
    src = JobSource(
        key="mng-rt",
        connector_key="mcp",
        config={
            "transport": "stdio",
            "command": command,
            "tool": "fetch_postings",
            "options": json.dumps({"keywords": "ai engineer", "max_pages": 2}),
        },
        enabled=True,
    )
    db.add(src)
    await db.commit()
    await db.refresh(src)

    view = await _source_view(db, src)
    assert view["managed"] is True
    assert json.loads(view["config"]["options"]) == {"keywords": "ai engineer", "max_pages": 2}


def test_digest_tree_ignores_runtime_byproducts(tmp_path):
    """The first managed spawn creates __pycache__ — derived files must
    never contribute to the digest or the run poisons its own pin."""
    from app.extensions.lifecycle import digest_tree

    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "server.py").write_text("print('hi')\n")
    (tmp_path / "manifest.json").write_text("{}")
    before = digest_tree(tmp_path)
    cache = tmp_path / "sub" / "__pycache__"
    cache.mkdir()
    (cache / "server.cpython-312.pyc").write_bytes(b"\x00\x01")
    (tmp_path / "sub" / "server.pyc").write_bytes(b"\x00")
    assert digest_tree(tmp_path) == before
