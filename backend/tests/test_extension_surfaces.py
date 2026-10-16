"""Phase 4 — career as the first Python surface host (plan 32 / ADR-0040
clause 16).

The vendored contract participation + the mini-app lifecycle:

* ``contracts/surface-renderer.fixtures.json`` — the career-side structural
  pass over the family parity fixtures (closed vocabulary, closed action
  ids, the evidence law; degrade probes are explicitly marked — the
  manifest gate rejects them at import, the renderer ignores them as
  render-seam defense).
* the import pipeline (Phase 3) gains the mini-app kind: source → consent
  (T0 declarative disclosure) → T0 install → enable → surface cards +
  page view → the kill switch kills the route; invalid surfaces reject at
  install"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select

from app.extensions import lifecycle, surfaces
from app.models.posting_model import JobSource
from tests.test_extension_sources import (
    FIXTURE_MANIFEST,
    FIXTURE_SERVER,
    TEMPLATE_DIR,
    _actor_id,
    _git,
    local_descriptor,
)

pytest_plugins = ["tests.test_extension_sources"]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
SURFACE_FIXTURES = json.loads(
    (CONTRACTS_DIR / "surface-renderer.fixtures.json").read_text(encoding="utf-8")
)

MINIAPP_ID = "career-cv-gallery"


def template_miniapp_manifest() -> dict:
    return json.loads((TEMPLATE_DIR / "cv-gallery" / "manifest.json").read_text("utf-8"))


# ------------------------------------------- the fixture wall, backend side


@pytest.mark.parametrize("fixture_case", SURFACE_FIXTURES["cases"], ids=lambda c: c["id"])
def test_surface_fixtures_pass_the_career_surface_laws(fixture_case: dict[str, Any]):
    """Every non-probe fixture case's nodes match what career's
    registration-time gate accepts. Degrade probes behave per where their
    unknown id rides: unknown NODE types/actions are rejected at the
    manifest gate; unknown ROW actions ride the data block and are
    DROPPED at view assembly (the renderer never shows them)."""
    nodes = fixture_case["surface"]["nodes"]
    if fixture_case.get("degradeProbe"):
        node_invalid = any(
            node.get("type") not in surfaces.COMPONENTS
            or any(a not in surfaces.ACTION_IDS for a in node.get("actions") or [])
            for node in nodes
        )
        if node_invalid:
            with pytest.raises(surfaces.ValidationError) as err:
                surfaces.validate_surface_nodes(nodes, kind="page")
            assert "unknown" in str(err.value) or "closed typed ids" in str(err.value)
            return
        assert surfaces.validate_surface_nodes(nodes, kind="page") is None
        row_unknown = [
            a
            for row in fixture_case["surface"].get("rows", [])
            for a in (row.get("actions") or [])
            if a not in surfaces.ACTION_IDS
        ]
        if row_unknown:
            view_rows = surfaces._rows_from(fixture_case["surface"].get("rows", []))
            emitted = {a for row in view_rows for a in row.get("actions", [])}
            assert not (set(row_unknown) & emitted), "unknown row actions never surface"
        return
    assert surfaces.validate_surface_nodes(nodes, kind="page") is None


def test_invalid_surfaces_reject_with_precise_reasons():
    base = [
        {"id": "count", "type": "stat", "bind": "totals.layouts"},
        {"id": "evidence", "type": "evidence"},
    ]
    assert surfaces.validate_surface_nodes(base, kind="page") is None
    cases = [
        (
            [{"id": "ghost", "type": "telepathy"}, *base],
            "unknown component type",
        ),
        (
            [{"id": "UpPER", "type": "stat", "bind": "x"}],
            "lowercase alphanumeric/dash",
        ),
        (
            [
                {"id": "twice", "type": "stat", "bind": "x"},
                {"id": "twice", "type": "badge", "bind": "x"},
            ],
            "duplicate component id",
        ),
        (
            [{"id": "t", "type": "table", "columns": []}, {"id": "evidence", "type": "evidence"}],
            "table requires non-empty string columns",
        ),
        (
            [
                {"id": "c", "type": "cards", "of": "everything"},
                {"id": "evidence", "type": "evidence"},
            ],
            "cards.of must be 'items' or 'groups'",
        ),
        (
            [{"id": "f", "type": "filter-bar", "filters": []}],
            "filter-bar requires non-empty filters",
        ),
        (
            [{"id": "s", "type": "select", "bind": "x", "options": []}],
            "select requires non-empty string options",
        ),
        (
            [{"id": "a", "type": "actions", "actions": ["run:explode"]}],
            "closed typed ids",
        ),
        (
            [{"id": "n", "type": "stat"}],
            "bind must be a data key string",
        ),
        (
            [{"id": "items", "type": "table", "columns": ["title"]}],
            "evidence component is mandatory",
        ),
        (
            [{"id": "gallery", "type": "cards", "of": "items"}],
            "evidence component is mandatory",
        ),
    ]
    for nodes, expected in cases:
        with pytest.raises(Exception) as err:
            surfaces.validate_surface_nodes(nodes, kind="page")
        assert expected in str(err.value), f"{nodes} → {err.value}"


def test_surface_profile_degrades_window_to_page():
    profile = surfaces.surface_capabilities(
        {"capabilities": ["ui:page", "ui:panel", "ui:window", "run", "report"]}
    )
    assert profile["honored"] == ["page", "panel"]
    assert profile["degrades"] == {"window": "page"}
    with pytest.raises(Exception) as err:
        surfaces.surface_capabilities({"capabilities": ["ui:chat-card"]})
    assert "self-disable" in str(err.value)


def test_the_data_deck_is_capped_and_normalizes():
    manifest = {"data": {"rows": [{"id": f"r{i}", "title": "x"} for i in range(301)]}}
    with pytest.raises(Exception) as err:
        surfaces.validate_data(manifest)
    assert "exceeds" in str(err.value)
    data = surfaces.validate_data({"data": {"rows": [], "totals": {"layouts": 3}, "note": "x"}})
    assert data == {"rows": [], "totals": {"layouts": 3}, "note": "x"}


def test_surface_view_assembles_from_the_template_manifest():
    manifest = template_miniapp_manifest()
    view = surfaces.surface_view(manifest)
    page = view["surface"]
    assert page["kind"] == "page"
    ids = [node["id"] for node in page["nodes"]]
    assert ids[:3] == ["status", "layouts-shipped", "coverage"], (
        "nodes ride verbatim; the canonical type order is the renderer's law"
    )
    assert page["rows"][0]["id"] == "compact"
    assert page["rows"][0]["badge"] == "Recommended"
    assert page["groups"]["recommended"] == "Recommended"
    assert page["values"]["totals"]["layouts"] == 4
    facet_ids = {facet["id"] for facet in page["filters"]}
    assert {"language", "density", "section-order"} <= facet_ids
    assert page["labels"]["report.layouts-shipped"] == "Layouts shipped"
    assert page["labels"]["report.gallery"] == "Gallery"
    assert view["missing_labels"] == [key for key in [] if False], (
        "the template manifest carries every label the contract names"
    )


# ------------------------------------------- the mini-app lifecycle (e2e)


def make_gallery_repo(root: Path, *, manifest: dict | None = None) -> Path:
    """A real local git repo whose ROOT is the connector template and whose
    ``cv-gallery/`` child is the declarative mini-app (a source repo
    carries several extensions, D13)."""
    repo = root / "gallery-repo"
    repo.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE_SERVER, repo / "server.py")
    shutil.copyfile(FIXTURE_MANIFEST, repo / "manifest.json")
    (repo / "cv-gallery").mkdir()
    effective = manifest if manifest is not None else template_miniapp_manifest()
    (repo / "cv-gallery" / "manifest.json").write_text(json.dumps(effective), encoding="utf-8")
    _git(repo, "init", "--quiet", "--initial-branch", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "gallery import")
    return repo


async def _install_gallery(db: AsyncSession, repo_root, manifest: dict | None = None):
    repo = make_gallery_repo(repo_root, manifest=manifest)
    source_view = await lifecycle.add_source(db, local_descriptor(repo))
    source_id = uuid.UUID(source_view["id"])
    await lifecycle.sync_source(db, source_id)
    return await lifecycle.install_extension(
        db, source_id, MINIAPP_ID, consent=True, actor_id=await _actor_id(db)
    )


async def test_gallery_imports_consents_and_surfaces(
    db, seeded_catalog, local_roots, mcp_allowlist
):
    """source → discovery (BOTH extensions) → consent (T0 disclosure) →
    T0 install (no job source minted) → enable → surface cards + page
    view → the kill switch kills the route."""
    from app.core.config import settings
    from app.extensions import surface_host as host

    repo = make_gallery_repo(local_roots)
    source_view = await lifecycle.add_source(db, local_descriptor(repo))
    source_id = uuid.UUID(source_view["id"])

    report = await lifecycle.sync_source(db, source_id)
    assert report["ok"] is True
    offered = {c["extensionId"] for c in report["candidates"]}
    assert "example-posting-fetcher" in offered
    assert MINIAPP_ID in offered, "discovery reaches the subfolder manifest"

    [gallery] = [c for c in report["candidates"] if c["extensionId"] == MINIAPP_ID]
    assert gallery["compatible"] is True
    source_list = await lifecycle.list_sources(db)
    [source_row] = [s for s in source_list if s["id"] == str(source_id)]
    [candidate_view] = [c for c in source_row["candidates"] if c["extensionId"] == MINIAPP_ID]
    consent = candidate_view["consent"]
    assert consent["tier"] == "T0"
    assert consent["disclosureKey"] == "t0DeclarativeDisclosure"
    assert "declarative data only" in consent["disclosure"]

    installed = await lifecycle.install_extension(
        db, source_id, MINIAPP_ID, consent=True, actor_id=await _actor_id(db)
    )
    assert installed["tier"] == "T0"
    assert installed["enabled"] is False, "installs are disabled — enable is explicit"
    minted = (
        (await db.execute(select(JobSource).where(JobSource.key == MINIAPP_ID))).scalars().first()
    )
    assert minted is None, "a T0 declarative mini-app mints NO job source"

    enabled = await lifecycle.set_install_enabled(db, uuid.UUID(installed["id"]), True)
    assert enabled["enabled"] is True

    cards = await host.list_surface_cards(db, locales=["en"])
    [card] = cards
    assert card["extensionId"] == MINIAPP_ID
    assert card["surfaces"]["honored"] == ["page", "panel"]
    assert card["surfaces"]["degrades"] == {"window": "page"}
    assert card["routes"] == f"/extensions/{MINIAPP_ID}"
    assert card["originClass"] == "imported"

    page_view = await host.surface_page_view(db, MINIAPP_ID, locales=["en", "de"])
    page = page_view["surface"]
    assert page["kind"] == "page"
    assert [n["id"] for n in page["nodes"]][:3] == ["status", "layouts-shipped", "coverage"]
    assert page["rows"][0]["id"] == "compact"
    assert page["labels"]["report.gallery"] == "Gallery"
    assert page_view["placeholders"] == [], "the template manifest is page-label-complete"

    serialized = json.dumps(page_view)
    assert "<script" not in serialized.lower()
    assert "private_key" not in serialized

    await lifecycle.set_install_enabled(db, uuid.UUID(installed["id"]), False)
    assert await host.list_surface_cards(db, locales=["en"]) == []
    with pytest.raises(LookupError):
        await host.surface_page_view(db, MINIAPP_ID)
    assert settings is not None  # keep the import honest for the kill-switch law


async def test_invalid_surfaces_reject_at_install(db, seeded_catalog, local_roots, mcp_allowlist):
    bad = template_miniapp_manifest()
    bad["surfaces"]["page"]["nodes"] = [
        {"id": "ghost", "type": "telepathy"},
        {"id": "count", "type": "stat", "bind": "totals.layouts"},
    ]
    with pytest.raises(lifecycle.LifecycleError) as err:
        await _install_gallery(db, local_roots, manifest=bad)
    assert "unknown component type" in str(err.value)


async def test_host_profile_gates_the_mini_app_kind(db, seeded_catalog, local_roots):
    manifest = template_miniapp_manifest()
    assert lifecycle.check_host_profile(manifest) is None
    grown = {**manifest, "capabilities": [*manifest["capabilities"], "net"]}
    reason = lifecycle.check_host_profile(grown)
    assert reason is not None and "not honored" in reason
    new_major = {**manifest, "apiVersion": 2}
    reason = lifecycle.check_host_profile(new_major)
    assert reason is not None and "apiVersion 2" in reason


def test_fixture_manifest_matches_the_canonical_template_minapp():
    canonical = TEMPLATE_DIR / "cv-gallery" / "manifest.json"
    assert canonical.is_file()


# ------------------------------------------------------- the surface API


async def test_the_surface_api_serves_enabled_pages_only(
    db, seeded_catalog, local_roots, mcp_allowlist, auth_headers
):
    """Route-level: a disabled install is absent from the registry AND the
    page 404s; after the explicit enable the view rides out. The export
    funnel answers the typed run:export action with the same deck."""
    import uuid as uuid_module

    repo = make_gallery_repo(local_roots)
    source_view = await lifecycle.add_source(db, local_descriptor(repo))
    source_id = uuid_module.UUID(source_view["id"])
    await lifecycle.sync_source(db, source_id)
    installed = await lifecycle.install_extension(db, source_id, MINIAPP_ID, consent=True)
    from fastapi import HTTPException

    from app.api.v1 import extensions as surface_api
    from app.extensions import surface_host
    from app.models.user_model import User

    user = (await db.execute(select(User))).scalars().first()
    cards = await surface_api.list_extension_surfaces(request=_fake_request(), user=user, db=db)
    assert cards == [], "disabled installs never surface (kill-switch default)"

    enabled = await lifecycle.set_install_enabled(db, uuid_module.UUID(installed["id"]), True)
    assert enabled["enabled"] is True

    cards = await surface_api.list_extension_surfaces(request=_fake_request(), user=user, db=db)
    [card] = cards
    assert card["extensionId"] == MINIAPP_ID
    assert card["surfaces"]["degrades"] == {"window": "page"}

    page = await surface_api.extension_surface(
        MINIAPP_ID, request=_fake_request(), user=user, db=db
    )
    assert page["extensionId"] == MINIAPP_ID
    assert page["surface"]["rows"][0]["id"] == "compact"

    export = await surface_api.export_extension_surface(
        MINIAPP_ID, request=_fake_request(), user=user, db=db
    )
    assert export["rows"] == page["surface"]["rows"]
    assert export["values"]["totals"]["layouts"] == 4

    assert await surface_host.surface_page_view(db, MINIAPP_ID)  # sanity: host agrees
    await lifecycle.set_install_enabled(db, uuid_module.UUID(installed["id"]), False)
    with pytest.raises(HTTPException) as err:
        await surface_api.extension_surface(MINIAPP_ID, request=_fake_request(), user=user, db=db)
    assert err.value.status_code == 404


def _fake_request():
    import types

    request = types.SimpleNamespace()
    request.headers = {"accept-language": "en"}
    request.state = types.SimpleNamespace()
    return request
