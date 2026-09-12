"""— CV synth AI generation (plan 62.2): CV_SYNTH agent + mock fixture,
sync/bulk generate paths, evidence verification, translate, and the
queue run with its ready-for-review notification."""

import uuid
from datetime import date

from sqlalchemy import select

from tests.conftest import _uid

from app.ai.agents.cv_synthetizer import _mock_synth, build_user_prompt
from app.models.engagement_model import Notification, NotificationKind
from app.models.experience_model import ExperienceItem
from app.schemas.cv_synth import (
    CvSynthBatch,
    CvSynthDraft,
    CvSynthItemGenerate,
    CvSynthPayload,
)
from app.services.job_worker import JobWorker


def _refs(item: ExperienceItem) -> list[dict]:
    return [{"source_key": "experience", "item_id": str(item.id)}]


async def _make_items(db, uid: str, count: int = 1) -> list[ExperienceItem]:
    rows = []
    for number in range(count):
        item = ExperienceItem(
            user_id=uuid.UUID(uid),
            kind="internship",
            title=f"Backend Intern {number}",
            org_name="Sample Corp",
            start=date(2024, 6, 1),
            end=date(2024, 9, 1),
            description="Built QA tooling",
            status="active",
        )
        db.add(item)
        rows.append(item)
    await db.commit()
    for item in rows:
        await db.refresh(item)
    return rows


def _generate_body(items: list[ExperienceItem], **kw) -> dict:
    if len(items) == 1:
        refs = _refs(items[0])
    else:
        refs = [{"source_key": "experience", "item_id": str(item.id)} for item in items]
    return {"refs": refs, "action": "summarize", **kw}


def _generate_request(items, **kw) -> CvSynthItemGenerate:
    if len(items) == 1:
        refs = _refs(items[0])
    else:
        refs = [{"source_key": "experience", "item_id": str(item.id)} for item in items]
    return CvSynthItemGenerate(refs=refs, action="summarize", **kw)


def _evidence(entry_ref, label="X") -> dict:
    return {
        "source_key": "experience",
        "item_id": entry_ref,
        "label": label,
        "detail": "",
        "payload": {"description": "", "skills": []},
    }


async def _seed_notification_kind(db) -> None:
    kind = (
        (
            await db.execute(
                select(NotificationKind).where(NotificationKind.key == "cv_synth_ready")
            )
        )
        .scalars()
        .first()
    )
    if kind is not None:
        return
    db.add(
        NotificationKind(
            key="cv_synth_ready",
            label="Synthesized variants ready for review",
            group="career",
            severity="info",
            default_enabled=True,
            default_channels=["in_app", "desktop"],
            mutable=True,
            manage_url="/cv",
        )
    )
    await db.commit()


# ------------------------------------------------------------------ mock fixture


def test_mock_synth_covers_every_action():
    evidence = [
        {
            "source_key": "experience",
            "item_id": "abc",
            "label": "Backend Intern",
            "detail": "Sample Corp",
            "payload": {"description": "Built QA tooling.", "skills": ["Python"]},
        }
    ]
    targets = [dict(evidence[0])]
    for action in ("summarize", "detail", "restyle", "posting_fit"):
        prompt = build_user_prompt(
            action,
            evidence,
            targets,
            posting={"title": "Backend Engineer", "must_have_skills": ["python"]},
        )
        batch = CvSynthBatch.model_validate(_mock_synth(CvSynthBatch, prompt))
        assert batch.items, action
        draft = batch.items[0]
        assert [dict(ref) for ref in draft.refs] == [
            {"source_key": "experience", "item_id": "abc"}
        ]
        assert draft.payload.description, "mock draft has text"

    prompt = build_user_prompt(
        "translate",
        evidence,
        targets,
        target_language="de",
        variant_texts={"experience:abc": "Tailored text"},
    )
    batch = CvSynthBatch.model_validate(_mock_synth(CvSynthBatch, prompt))
    assert batch.items[0].payload.description.startswith("[DE] "), (
        "mock translate marks the language"
    )


# ------------------------------------------------------------------ sync generate


async def test_generate_creates_verified_drafts(client, db, auth_headers):
    item = (await _make_items(db, _uid(auth_headers)))[0]
    response = await client.post(
        "/api/v1/cv/synth/generate",
        json=_generate_body([item], tone="concise"),
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_id"] is None
    rows = body["items"]
    assert rows and rows[0]["status"] == "draft"
    assert rows[0]["source"] == "ai"
    assert rows[0]["verified"] is True
    assert rows[0]["voice"]["language"] == "en"
    assert rows[0]["voice"]["action"] == "summarize"
    assert rows[0]["payload"]["description"], "mock draft text present"

    listing = (
        await client.get(
            "/api/v1/cv/synth", params={"status": "draft"}, headers=auth_headers
        )
    ).json()
    assert len(listing) == 1, "draft sits in the library as a draft"
    assert listing[0]["id"] == rows[0]["id"]


async def test_generate_rejects_refs_outside_context(client, db, auth_headers):
    response = await client.post(
        "/api/v1/cv/synth/generate",
        json={
            "refs": [
                {
                    "source_key": "experience",
                    "item_id": "00000000-0000-0000-0000-000000000000",
                }
            ],
            "action": "summarize",
        },
        headers=auth_headers,
    )
    assert response.status_code == 400, response.text


async def test_generate_bulk_rides_queue_and_notifies(client, db, auth_headers):
    items = await _make_items(db, _uid(auth_headers), count=7)
    await _seed_notification_kind(db)
    response = await client.post(
        "/api/v1/cv/synth/generate",
        json=_generate_body(items),
        headers=auth_headers,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["job_id"] is not None and body["items"] == []

    worker = JobWorker(db)
    while await worker.run_once():
        pass
    rows = (
        await client.get(
            "/api/v1/cv/synth", params={"status": "draft"}, headers=auth_headers
        )
    ).json()
    assert len(rows) == len(items), "one draft per queued ref"

    notifications = (await db.execute(select(Notification))).scalars().all()
    assert notifications, "the ready-for-review notification was emitted"
    assert notifications[0].payload["count"] == len(items)


# ------------------------------------------------------------------ verification


async def test_regenerate_supersede_on_activation(client, db, auth_headers):
    """Regenerate → fresh draft; activating it supersedes the old one."""
    item = (await _make_items(db, _uid(auth_headers)))[0]
    first = (
        await client.post(
            "/api/v1/cv/synth/generate",
            json=_generate_body([item]),
            headers=auth_headers,
        )
    ).json()["items"][0]
    regenerated = (
        await client.post(
            f"/api/v1/cv/synth/{first['id']}/regenerate", headers=auth_headers
        )
    ).json()
    assert regenerated["items"], "a fresh draft"
    second = regenerated["items"][0]
    assert second["id"] != first["id"], "new draft row"
    assert second["status"] == "draft"
    assert second["voice"]["action"] == "summarize", "stored params rerun"

    activated = (
        await client.patch(
            f"/api/v1/cv/synth/{second['id']}",
            json={"status": "active"},
            headers=auth_headers,
        )
    ).json()
    assert activated["status"] == "active"
    rows = (await client.get("/api/v1/cv/synth", headers=auth_headers)).json()
    by_id = {r["id"]: r for r in rows}
    assert by_id[first["id"]]["status"] == "archived", (
        "approving the regenerate supersedes the stale draft"
    )
    assert by_id[second["id"]]["status"] == "active"


async def test_regenerate_manual_rejected(client, db, auth_headers):
    item = (await _make_items(db, _uid(auth_headers)))[0]
    created = await client.post(
        "/api/v1/cv/synth",
        json={
            "refs": _refs(item),
            "scope": "item",
            "payload": {"description": "manual text"},
        },
        headers=auth_headers,
    )
    row = created.json()
    rejected = await client.post(
        f"/api/v1/cv/synth/{row['id']}/regenerate", headers=auth_headers
    )
    assert rejected.status_code == 400, "manual variants have no stored params"


async def test_translate_creates_language_sibling(client, db, auth_headers):
    item = (await _make_items(db, _uid(auth_headers)))[0]
    master = (
        await client.post(
            "/api/v1/cv/synth/generate",
            json=_generate_body([item]),
            headers=auth_headers,
        )
    ).json()["items"][0]
    await client.patch(
        f"/api/v1/cv/synth/{master['id']}",
        json={"status": "active"},
        headers=auth_headers,
    )
    translated = (
        await client.post(
            "/api/v1/cv/synth/generate",
            json={
                "refs": _refs(item),
                "action": "translate",
                "translate_of": master["id"],
                "target_language": "de",
            },
            headers=auth_headers,
        )
    ).json()["items"]
    assert translated, "a draft sibling"
    row = translated[0]
    assert row["voice"]["language"] == "de"
    assert (
        row["source_state"][0]["content_hash"]
        == master["source_state"][0]["content_hash"]
    ), "the sibling tracks the same source hashes"
    assert row["status"] == "draft", "draft-then-approve applies to translations"

    cv = (
        await client.post(
            "/api/v1/cv",
            json={"title": "DE", "kind": "resume", "language": "de"},
            headers=auth_headers,
        )
    ).json()
    from app.schemas.cv_synth import CvSynthItemUpdate
    from app.services.cv_service import CvService
    from app.services.cv_synth_service import CvSynthService

    service = CvSynthService(db)
    doc = await CvService(db).get_owned(
        uuid.UUID(cv["id"]), uuid.UUID(_uid(auth_headers))
    )
    before = await service.match_for_cv(doc, refs=_refs(item))
    assert before == {}, "EN variant never matches a DE CV"
    await service.update(
        uuid.UUID(row["id"]),
        uuid.UUID(_uid(auth_headers)),
        CvSynthItemUpdate(status="active"),
    )
    match = await service.match_for_cv(doc, refs=_refs(item))
    assert list(match.values())[0].id == uuid.UUID(row["id"]), (
        "the DE variant applies to the DE CV once active"
    )
    match.pop(None, None)
    assert match is not None


async def test_out_of_allowlist_items_dropped(client, db, auth_headers):
    """The honesty gate: AI items citing other refs never persist."""
    from app.services.cv_synth_service import CvSynthService

    item = (await _make_items(db, _uid(auth_headers)))[0]
    service = CvSynthService(db)
    request = CvSynthItemGenerate(
        refs=_refs(item),
        action="summarize",
        scope="item",
        posting_id=None,
        variant_key=None,
    )
    batch = CvSynthBatch(
        items=[
            CvSynthDraft(
                refs=[
                    {
                        "source_key": "experience",
                        "item_id": "00000000-0000-0000-0000-000000000000",
                    }
                ],
                payload=CvSynthPayload(description="Invented item"),
                evidence_refs=[],
            )
        ]
    )
    rows = await service._persist_batch(
        uuid.UUID(_uid(auth_headers)),
        request,
        batch,
        refs=_refs(item),
        context={("experience", str(item.id)): {}},
        language="en",
    )
    assert rows == [], "out-of-allowlist refs are dropped, never silently trusted"


async def test_textless_batch_dropped(client, db, auth_headers):
    """An item with no text content at all never becomes a row."""
    from app.services.cv_synth_service import CvSynthService

    item = (await _make_items(db, _uid(auth_headers)))[0]
    service = CvSynthService(db)
    request = CvSynthItemGenerate(refs=_refs(item), action="summarize", scope="item")
    batch = CvSynthBatch(
        items=[
            CvSynthDraft(
                refs=[{"source_key": "experience", "item_id": str(item.id)}],
                payload=CvSynthPayload(),
                evidence_refs=[{"source_key": "experience", "item_id": str(item.id)}],
            )
        ]
    )
    rows = await service._persist_batch(
        uuid.UUID(_uid(auth_headers)),
        request,
        batch,
        refs=_refs(item),
        context={("experience", str(item.id)): {}},
        language="en",
    )
    assert rows == []
