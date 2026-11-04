"""Plan 121.4 — catalog label overlays: review-first read-time resolution.

The fallback chain is the wall: only an APPROVED overlay renders; drafts and
rejected rows never do, and a missing overlay leaves the base label intact.
"""

import uuid

from app.models.enums import LabelStatus


async def _enable_mock_translate(db):
    from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
    from app.models.enums import AITaskType

    provider = AIProvider(
        name="mock-translate-overlays",
        scope="system",
        provider_type="mock",
        api_base="http://mock.invalid",
    )
    db.add(provider)
    await db.flush()
    model = AIModel(provider_id=provider.id, name="mock", model_name="mock-translate")
    db.add(model)
    await db.flush()
    db.add(
        AITaskAssignment(
            task_type=AITaskType.TRANSLATE.value,
            scope="system",
            provider_id=provider.id,
            model_id=model.id,
        )
    )
    await db.commit()


async def test_overlay_fallback_chain(client, auth_headers, db, seeded_catalog):
    await _enable_mock_translate(db)
    await client.put("/api/v1/me/locale", json={"locale": "de"}, headers=auth_headers)

    drafted = await client.post(
        "/api/v1/admin/i18n/overlays/draft",
        json={"locale": "de", "entity_kinds": ["job"], "limit": 50},
        headers=auth_headers,
    )
    assert drafted.status_code == 200
    assert drafted.json()["drafted"]["job"] > 0

    rows = (
        await client.get(
            "/api/v1/admin/i18n/overlays?locale=de&status=draft&limit=200",
            headers=auth_headers,
        )
    ).json()
    assert rows
    title_row = next(row for row in rows if row["entity_kind"] == "job" and row["field"] == "label")

    listing = (await client.get("/api/v1/jobs?page_size=100", headers=auth_headers)).json()["items"]
    target = next(job for job in listing if job["id"] == title_row["entity_id"])
    assert title_row["base_value"] == target["title"]
    assert title_row["value"] == f"[de] {target['title']}"
    assert target["title"] == title_row["base_value"], "drafts never render"

    approved = await client.post(
        f"/api/v1/admin/i18n/overlays/{title_row['id']}/approve", headers=auth_headers
    )
    assert approved.status_code == 200

    refreshed = (await client.get("/api/v1/jobs?page_size=100", headers=auth_headers)).json()[
        "items"
    ]
    localized = next(job for job in refreshed if job["id"] == target["id"])
    assert localized["title"] == f"[de] {target['title']}"

    other = next(row for row in rows if row["id"] != title_row["id"])
    rejected = await client.post(
        f"/api/v1/admin/i18n/overlays/{other['id']}/reject", headers=auth_headers
    )
    assert rejected.status_code == 200
    refreshed = (await client.get("/api/v1/jobs?page_size=100", headers=auth_headers)).json()[
        "items"
    ]
    other_job = next(job for job in refreshed if job["id"] == other["entity_id"])
    field = "title" if other["field"] == "label" else "short_description"
    assert other_job[field] == other["base_value"]


async def test_overlay_edit_then_approve(client, auth_headers, db, seeded_catalog):
    await _enable_mock_translate(db)
    await client.put("/api/v1/me/locale", json={"locale": "de"}, headers=auth_headers)
    await client.post(
        "/api/v1/admin/i18n/overlays/draft",
        json={"locale": "de", "entity_kinds": ["family"], "limit": 5},
        headers=auth_headers,
    )
    rows = (
        await client.get("/api/v1/admin/i18n/overlays?locale=de&status=draft", headers=auth_headers)
    ).json()
    family_rows = [row for row in rows if row["entity_kind"] == "family"]
    assert family_rows
    row = family_rows[0]
    edited = await client.patch(
        f"/api/v1/admin/i18n/overlays/{row['id']}",
        json={"value": "Handgeprüfte Familie"},
        headers=auth_headers,
    )
    assert edited.status_code == 200
    await client.post(f"/api/v1/admin/i18n/overlays/{row['id']}/approve", headers=auth_headers)
    tree = (await client.get("/api/v1/jobs/tree", headers=auth_headers)).json()

    def labels(nodes):
        for node in nodes:
            yield node["label"]
            yield from labels(node.get("children") or [])

    assert "Handgeprüfte Familie" in list(labels(tree))


async def test_apply_ignores_drafts_and_maps_fields(db):
    from app.models.enums import LabelEntityKind
    from app.services.catalog.label_overlay_service import LabelOverlayService
    from app.services.locale_service import normalize_locale

    entity_id = uuid.uuid4()
    service = LabelOverlayService(db)
    await service.ensure_draft(
        entity_kind=LabelEntityKind.JOB,
        entity_id=entity_id,
        locale="de",
        field="label",
        value="Entwurf",
    )
    await db.commit()
    rows = await service.apply(
        LabelEntityKind.JOB,
        [{"id": entity_id, "title": "Base title", "short_description": "Base summary"}],
        "de",
    )
    assert rows[0]["title"] == "Base title"
    assert rows[0]["short_description"] == "Base summary"

    await service.ensure_draft(
        entity_kind=LabelEntityKind.JOB,
        entity_id=entity_id,
        locale="de",
        field="label",
        value="Geprüft",
    )
    await db.commit()
    queued = await service.queue(locale="de")
    await service.set_status(queued[0].id, LabelStatus.APPROVED)

    approved = await service.apply(
        LabelEntityKind.JOB,
        [{"id": entity_id, "title": "Base title", "short_description": "Base summary"}],
        "de",
    )
    assert approved[0]["title"] == "Geprüft"
    assert approved[0]["short_description"] == "Base summary"

    assert normalize_locale("de-AT") == "de"
    assert normalize_locale("fr") is None
    assert normalize_locale("DE") == "de"
