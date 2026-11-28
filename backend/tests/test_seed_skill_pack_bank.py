"""Plan 225 S4: the skill-pack bank — draft apply, explicit publish, revoke."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.ai.packs import resolve_pack
from app.core.errors import ValidationError
from app.core.seed_pack.archive import build_pack_archive
from app.core.seed_pack.errors import BANK_TRUST_DENIED, SeedPackError
from app.core.seed_pack.manifest import compute_files_digest
from app.models.identity_model import AuditEvent
from app.models.seed_model import SeedSource, SeedSourceVersion
from app.models.skill_pack_model import AISkillPack
from app.services.seeds.banks import (
    REFERENCE_BANK_SUBPATH,
    skill_pack_content_hash,
)
from app.services.seeds.provider_service import ProviderService
from app.services.seeds.service import ProviderSyncService
from tests.conftest import mint_session_headers
from tests.test_seed_apply import _service, _source, _store, _version
from tests.test_seed_pack import _envelope, _pack

ADMIN = "/api/v1/admin/providers"

PACK_V1 = {
    "seed_key": "skill-pack:interview-prep-style/v1",
    "key": "interview-prep-style",
    "version": 1,
    "title": "Interview coaching style guide",
    "task": "interview_turn",
    "instructions": "v1: quote the candidate's phrasing when it works.",
}
PACK_V2 = {
    "seed_key": "skill-pack:interview-prep-style/v2",
    "key": "interview-prep-style",
    "version": 2,
    "title": "Interview coaching style guide",
    "task": "interview_turn",
    "instructions": "v2: name the missing STAR element before any rewrite.",
}
SECOND_PACK = {
    "seed_key": "skill-pack:cover-letter-voice/v1",
    "key": "cover-letter-voice",
    "version": 1,
    "title": "Cover letter voice",
    "task": "cv_cover_letter",
    "instructions": "Open with the role's core problem.",
}


def _skill_pack_pack(items: list | None, *, version: str = "1.0.0") -> dict[str, bytes]:
    return _pack(
        {"items/skill_packs/packs.json": _envelope("skill_packs", items or [])},
        manifest={"version": version, "replaces": []},
    )


async def _operator_source(db):
    source = await _source(db)
    source.trust_tier = "operator"
    await db.commit()
    await db.refresh(source)
    return source


async def _apply(db, store, source, version):
    applied = await _service(db, store).apply(source, version)
    assert applied.status == "applied", applied.error
    return applied


async def _row(db, seed_key: str) -> AISkillPack:
    row = await db.scalar(select(AISkillPack).where(AISkillPack.seed_key == seed_key))
    assert row is not None
    return row


async def test_a_skill_pack_pack_parses_plans_applies_as_draft_and_noops(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    version = await _version(db, store, source, _skill_pack_pack([PACK_V1]))

    plan = await _service(db, store).build_plan(source, version)
    assert plan.status == "ok"
    [item] = [row for row in plan.items if row.entity_type == "skill_pack"]
    assert item.action == "create"
    assert item.preview is not None
    assert item.preview["instructions"] == PACK_V1["instructions"]
    assert item.preview["content_hash"] == skill_pack_content_hash(PACK_V1)

    applied = await _service(db, store).apply(source, version)
    assert applied.status == "applied", applied.error
    row = await _row(db, PACK_V1["seed_key"])
    assert row.status == "draft"
    assert row.author_key == "bank"
    assert row.author_user_id is None
    assert row.task == "interview_turn"
    assert row.instructions == PACK_V1["instructions"]
    assert row.content_hash == skill_pack_content_hash(PACK_V1)

    assert await resolve_pack(db, "interview_turn") is None

    again = await _service(db, store).apply(source, version)
    assert again.status == "noop"
    row = await _row(db, PACK_V1["seed_key"])
    assert row.status == "draft"


async def test_publish_makes_the_draft_visible_with_an_audit_row(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    version = await _version(db, store, source, _skill_pack_pack([PACK_V1]))
    await _apply(db, store, source, version)

    result = await ProviderService(db, packs=store).publish_skill_pack(
        source.id, PACK_V1["seed_key"], actor="admin-1"
    )
    assert result["status"] == "published"
    assert result["key"] == "interview-prep-style"
    assert result["version"] == 1
    assert result["content_hash"] == skill_pack_content_hash(PACK_V1)

    row = await _row(db, PACK_V1["seed_key"])
    assert row.status == "published"
    pack = await resolve_pack(db, "interview_turn")
    assert pack is not None and pack.version == 1

    event = await db.scalar(
        select(AuditEvent).where(AuditEvent.action == "provider.item.published")
    )
    assert event is not None
    assert event.actor == "admin-1"
    assert "skill-pack:interview-prep-style" in event.resource
    assert "version:1" in event.resource
    assert row.content_hash in event.resource


async def test_publishing_a_new_version_retires_the_same_key_predecessor(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    first = await _version(db, store, source, _skill_pack_pack([PACK_V1]))
    await _apply(db, store, source, first)
    service = ProviderService(db, packs=store)
    await service.publish_skill_pack(source.id, PACK_V1["seed_key"], actor="admin-1")

    second = await _version(db, store, source, _skill_pack_pack([PACK_V2], version="2.0.0"))
    plan = await _service(db, store).build_plan(source, second)
    assert not [
        item for item in plan.items if item.entity_type == "skill_pack" and item.action == "retire"
    ]
    assert not [
        warning for warning in plan.warnings if warning.get("seed_key") == PACK_V1["seed_key"]
    ]
    await _apply(db, store, source, second)

    predecessor = await _row(db, PACK_V1["seed_key"])
    draft = await _row(db, PACK_V2["seed_key"])
    assert predecessor.status == "published"
    assert draft.status == "draft"
    fallback = await resolve_pack(db, "interview_turn")
    assert fallback is not None and fallback.version == 1

    await service.publish_skill_pack(source.id, PACK_V2["seed_key"], actor="admin-1")
    predecessor = await _row(db, PACK_V1["seed_key"])
    published = await _row(db, PACK_V2["seed_key"])
    assert predecessor.status == "retired"
    assert published.status == "published"
    pack = await resolve_pack(db, "interview_turn")
    assert pack is not None and pack.version == 2


async def test_retiring_the_last_published_version_is_refused(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    version = await _version(db, store, source, _skill_pack_pack([PACK_V1]))
    await _apply(db, store, source, version)
    service = ProviderService(db, packs=store)
    await service.publish_skill_pack(source.id, PACK_V1["seed_key"], actor="admin-1")

    with pytest.raises(ValidationError) as refused:
        await service.retire_bank_item(source.id, PACK_V1["seed_key"], actor="admin-1")
    assert "last published" in str(refused.value)

    row = await _row(db, PACK_V1["seed_key"])
    assert row.status == "published"


async def test_removing_a_skill_pack_key_warns_and_never_retires(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    first = await _version(db, store, source, _skill_pack_pack([PACK_V1, SECOND_PACK]))
    await _apply(db, store, source, first)
    assert (await _row(db, PACK_V1["seed_key"])).status == "draft"

    removed = await _version(db, store, source, _skill_pack_pack([], version="2.0.0"))
    plan = await _service(db, store).build_plan(source, removed)
    warnings = [
        warning
        for warning in plan.warnings
        if warning["code"] == "SKILL_PACK_REMOVAL" and warning["seed_key"] == PACK_V1["seed_key"]
    ]
    assert warnings
    assert not [
        item for item in plan.items if item.entity_type == "skill_pack" and item.action == "retire"
    ]

    applied = await _service(db, store).apply(source, removed)
    assert applied.status in ("applied", "noop"), applied.error
    assert (await _row(db, PACK_V1["seed_key"])).status == "draft"
    assert (await _row(db, SECOND_PACK["seed_key"])).status == "draft"


async def test_revoke_restores_the_previous_published_version(db, tmp_path):
    store = _store(tmp_path)
    source = await _operator_source(db)
    first = await _version(db, store, source, _skill_pack_pack([PACK_V1]))
    await _apply(db, store, source, first)
    service = ProviderService(db, packs=store)
    await service.publish_skill_pack(source.id, PACK_V1["seed_key"], actor="admin-1")

    second = await _version(db, store, source, _skill_pack_pack([PACK_V2], version="2.0.0"))
    await _apply(db, store, source, second)
    await service.publish_skill_pack(source.id, PACK_V2["seed_key"], actor="admin-1")
    assert (await _row(db, PACK_V1["seed_key"])).status == "retired"

    result = await _service(db, store).revoke(source, second)
    assert result.status in ("applied", "noop"), result.error

    restored = await _row(db, PACK_V1["seed_key"])
    revoked = await _row(db, PACK_V2["seed_key"])
    assert restored.status == "published"
    assert revoked.status == "retired"
    pack = await resolve_pack(db, "interview_turn")
    assert pack is not None and pack.version == 1


async def test_one_click_official_install_leaves_skill_packs_draft(db, tmp_path, monkeypatch):
    store = _store(tmp_path)
    files = _skill_pack_pack([PACK_V1])
    source = SeedSource(
        name="Reference banks",
        kind="git",
        uri="https://example.test/seeds.git",
        subpath=REFERENCE_BANK_SUBPATH,
        trust_tier="official",
        priority=100,
        enabled=False,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    async def fake_sync(self, source, *, trigger="manual", actor=None):
        digest = compute_files_digest(files)
        store.put(source.id, digest, build_pack_archive(files))
        version = SeedSourceVersion(
            source_id=source.id,
            digest=digest,
            manifest=json.loads(files["manifest.json"]),
            pack_version="1.0.0",
            schema_version="1.0",
            status="pending",
        )
        self.db.add(version)
        await self.db.commit()
        await self.db.refresh(version)
        return {"status": "ok", "version_id": str(version.id)}

    monkeypatch.setattr(ProviderSyncService, "sync", fake_sync)

    result = await ProviderService(db, packs=store).install_official(source.id)
    assert result["status"] == "applied", result

    row = await _row(db, PACK_V1["seed_key"])
    assert row.status == "draft"
    assert await resolve_pack(db, "interview_turn") is None


async def test_a_skill_pack_pack_requires_operator_or_official_trust(db, tmp_path):
    store = _store(tmp_path)
    source = await _source(db)
    version = await _version(db, store, source, _skill_pack_pack([PACK_V1]))

    with pytest.raises(SeedPackError) as refused:
        await _service(db, store).build_plan(source, version)
    assert refused.value.code == BANK_TRUST_DENIED


async def test_publish_and_retire_routes_are_body_keyed_and_admin_only(
    client, auth_headers, db, tmp_path
):
    store = _store(tmp_path)
    source = await _operator_source(db)
    version = await _version(db, store, source, _skill_pack_pack([PACK_V1]))
    await _apply(db, store, source, version)
    path = f"{ADMIN}/{source.id}"

    published = await client.post(
        f"{path}/publish", headers=auth_headers, json={"seed_key": PACK_V1["seed_key"]}
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    refused = await client.post(
        f"{path}/retire", headers=auth_headers, json={"seed_key": PACK_V1["seed_key"]}
    )
    assert refused.status_code == 400, refused.text
    assert "last published" in refused.json()["detail"]

    limited = mint_session_headers(email="limited@example.com", is_admin=False)
    forbidden = await client.post(
        f"{path}/publish", headers=limited, json={"seed_key": PACK_V1["seed_key"]}
    )
    assert forbidden.status_code == 403
