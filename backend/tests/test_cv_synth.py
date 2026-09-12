"""— CV synth library: manual variants, computed state, matching.

Covers 62.1: creation (manual), staleness/orphan computation, activation
superseding slot siblings, variant filters, ownership, and the
deterministic match precedence (active → language → posting-scoped
beats generic → variant order).
"""

import uuid
from datetime import date

from tests.conftest import _make_posting, _uid

from app.models.experience_model import ExperienceItem


async def _make_item(db, uid: str, title: str = "Backend Intern") -> ExperienceItem:
    item = ExperienceItem(
        user_id=uuid.UUID(uid),
        kind="internship",
        title=title,
        org_name="Sample Corp",
        start=date(2024, 6, 1),
        end=date(2024, 9, 1),
        description="Built QA tooling",
        status="active",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


def _refs(item: ExperienceItem) -> list[dict]:
    return [{"source_key": "experience", "item_id": str(item.id)}]


def _variant_body(
    item: ExperienceItem,
    *,
    text: str = "Tailored bullet",
    variant_key: str = "default",
    language: str = "en",
    posting_id: str | None = None,
) -> dict:
    return {
        "refs": _refs(item),
        "scope": "item",
        "payload": {"description": text},
        "variant_key": variant_key,
        "voice": {"language": language},
        "target_posting_id": posting_id,
    }


async def _seed_variant(client, auth_headers: dict, item: ExperienceItem, **kw) -> dict:
    created = await client.post(
        "/api/v1/cv/synth",
        json=_variant_body(item, **kw),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


def _service(db):
    from app.services.cv_synth_service import CvSynthService

    return CvSynthService(db)


async def _owned_cv(client, db, auth_headers, cv_id: str):
    from app.services.cv_service import CvService

    return await CvService(db).get_owned(
        uuid.UUID(cv_id), uuid.UUID(_uid(auth_headers))
    )


def _text(match: dict) -> str:
    return next(iter(match.values())).payload["description"]


async def test_manual_create_and_list(client, db, auth_headers):
    item = await _make_item(db, _uid(auth_headers))
    await _seed_variant(client, auth_headers, item, text="Concise variant")
    rows = (await client.get("/api/v1/cv/synth", headers=auth_headers)).json()
    assert rows, rows
    row = rows[0]
    assert row["status"] == "active"
    assert row["source"] == "manual"
    assert row["verified"] is True
    assert row["stale"] is False
    assert row["source_refs"] == _refs(item)
    assert row["source_state"][0]["content_hash"], "hash captured at creation"


async def test_source_edit_marks_stale(client, db, auth_headers):
    item = await _make_item(db, _uid(auth_headers))
    await _seed_variant(client, auth_headers, item, text="v1")
    item.description = "Edited description"
    db.add(item)
    await db.commit()
    rows = (await client.get("/api/v1/cv/synth", headers=auth_headers)).json()
    assert rows[0]["stale"] is True
    assert rows[0]["orphaned"] is False


async def test_source_delete_marks_orphaned(client, db, auth_headers):
    item = await _make_item(db, _uid(auth_headers))
    await _seed_variant(client, auth_headers, item)
    await db.delete(item)
    await db.commit()
    rows = (await client.get("/api/v1/cv/synth", headers=auth_headers)).json()
    assert rows[0]["orphaned"] is True
    assert rows[0]["stale"] is False


async def test_activate_supersedes_slot_siblings(client, db, auth_headers):
    item = await _make_item(db, _uid(auth_headers))
    first = await _seed_variant(client, auth_headers, item, text="first")
    second = await _seed_variant(client, auth_headers, item, text="second")
    rows = (await client.get("/api/v1/cv/synth", headers=auth_headers)).json()
    by_id = {r["id"]: r for r in rows}
    assert by_id[first["id"]]["status"] == "archived", "one active per slot"
    assert by_id[second["id"]]["status"] == "active"


async def test_reactivate_active_is_noop(client, db, auth_headers):
    item = await _make_item(db, _uid(auth_headers))
    row = await _seed_variant(client, auth_headers, item)
    updated = (
        await client.patch(
            f"/api/v1/cv/synth/{row['id']}",
            json={"status": "active"},
            headers=auth_headers,
        )
    ).json()
    assert updated["status"] == "active"


async def test_variant_keys_are_separate_slots(client, db, auth_headers):
    item = await _make_item(db, _uid(auth_headers))
    await _seed_variant(client, auth_headers, item, text="default")
    await _seed_variant(
        client, auth_headers, item, text="concise", variant_key="concise"
    )
    rows = (await client.get("/api/v1/cv/synth", headers=auth_headers)).json()
    active = [r for r in rows if r["status"] == "active"]
    assert len(active) == 2, "different variant_key slots coexist"
    assert {r["variant_key"] for r in active} == {"default", "concise"}


async def test_list_filters(client, db, auth_headers):
    item = await _make_item(db, _uid(auth_headers))
    await _seed_variant(client, auth_headers, item, text="en")
    await _seed_variant(
        client, auth_headers, item, text="de", variant_key="concise", language="de"
    )
    en_only = (
        await client.get(
            "/api/v1/cv/synth", params={"language": "en"}, headers=auth_headers
        )
    ).json()
    assert len(en_only) == 1 and en_only[0]["voice"]["language"] == "en"
    experience_only = (
        await client.get(
            "/api/v1/cv/synth",
            params={"source_key": "experience"},
            headers=auth_headers,
        )
    ).json()
    assert len(experience_only) == 2
    stale_only = (
        await client.get(
            "/api/v1/cv/synth", params={"stale": "true"}, headers=auth_headers
        )
    ).json()
    assert stale_only == []


async def test_delete(client, db, auth_headers):
    item = await _make_item(db, _uid(auth_headers))
    row = await _seed_variant(client, auth_headers, item)
    gone = await client.delete(f"/api/v1/cv/synth/{row['id']}", headers=auth_headers)
    assert gone.status_code == 204
    rows = (await client.get("/api/v1/cv/synth", headers=auth_headers)).json()
    assert rows == []


async def test_unknown_source_rejected(client, db, auth_headers):
    bad = await client.post(
        "/api/v1/cv/synth",
        json={
            "refs": [{"source_key": "basics", "item_id": "basics"}],
            "scope": "item",
            "payload": {"description": "x"},
        },
        headers=auth_headers,
    )
    assert bad.status_code == 400, bad.status_code


async def test_empty_text_rejected(client, db, auth_headers):
    item = await _make_item(db, _uid(auth_headers))
    bad = await client.post(
        "/api/v1/cv/synth",
        json={"refs": _refs(item), "scope": "item", "payload": {}},
        headers=auth_headers,
    )
    assert bad.status_code == 400, bad.status_code


async def test_match_empty_before_any_variant(client, db, auth_headers):
    item = await _make_item(db, _uid(auth_headers))
    cv = (
        await client.post(
            "/api/v1/cv",
            json={"title": "Main", "kind": "resume"},
            headers=auth_headers,
        )
    ).json()
    doc = await _owned_cv(client, db, auth_headers, cv["id"])
    match = await _service(db).match_for_cv(doc, refs=_refs(item))
    assert match == {}


async def test_match_posting_scoped_beats_generic(client, db, auth_headers, source):
    item = await _make_item(db, _uid(auth_headers))
    await _seed_variant(client, auth_headers, item, text="generic")
    posting = await _make_posting(db, source, external_id="synth-1")
    cv = (
        await client.post(
            "/api/v1/cv",
            json={"title": "A", "kind": "resume"},
            headers=auth_headers,
        )
    ).json()
    await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={"target_posting_id": str(posting.id)},
        headers=auth_headers,
    )
    await _seed_variant(
        client, auth_headers, item, text="scoped", posting_id=str(posting.id)
    )
    doc = await _owned_cv(client, db, auth_headers, cv["id"])
    match = await _service(db).match_for_cv(doc, refs=_refs(item))
    assert _text(match) == "scoped", "posting-scoped beats generic"


async def test_match_wrong_posting_never_applies(client, db, auth_headers, source):
    item = await _make_item(db, _uid(auth_headers))
    posting = await _make_posting(db, source, external_id="synth-2")
    posting2 = await _make_posting(db, source, external_id="synth-3")
    cv = (
        await client.post(
            "/api/v1/cv",
            json={"title": "A", "kind": "resume"},
            headers=auth_headers,
        )
    ).json()
    await client.patch(
        f"/api/v1/cv/{cv['id']}",
        json={"target_posting_id": str(posting2.id)},
        headers=auth_headers,
    )
    await _seed_variant(
        client, auth_headers, item, text="scoped", posting_id=str(posting.id)
    )
    doc = await _owned_cv(client, db, auth_headers, cv["id"])
    match = await _service(db).match_for_cv(doc, refs=_refs(item))
    assert match == {}, "a scoped row never applies to another CV's posting"


async def test_match_language_filter(client, db, auth_headers):
    item = await _make_item(db, _uid(auth_headers))
    await _seed_variant(client, auth_headers, item, text="en only")
    cv = (
        await client.post(
            "/api/v1/cv",
            json={"title": "DE", "kind": "resume", "language": "de"},
            headers=auth_headers,
        )
    ).json()
    doc = await _owned_cv(client, db, auth_headers, cv["id"])
    match = await _service(db).match_for_cv(doc, refs=_refs(item))
    assert match == {}, "EN variant never applies to a DE CV"


async def test_match_default_variant_wins(client, db, auth_headers):
    item = await _make_item(db, _uid(auth_headers))
    await _seed_variant(
        client, auth_headers, item, text="concise", variant_key="concise"
    )
    await _seed_variant(client, auth_headers, item, text="default")
    cv = (
        await client.post(
            "/api/v1/cv",
            json={"title": "A", "kind": "resume"},
            headers=auth_headers,
        )
    ).json()
    doc = await _owned_cv(client, db, auth_headers, cv["id"])
    match = await _service(db).match_for_cv(doc, refs=_refs(item))
    assert _text(match) == "default", '"default" beats a newer variant'


async def test_match_generic_fallback(client, db, auth_headers):
    item = await _make_item(db, _uid(auth_headers))
    await _seed_variant(client, auth_headers, item, text="generic")
    cv = (
        await client.post(
            "/api/v1/cv",
            json={"title": "A", "kind": "resume"},
            headers=auth_headers,
        )
    ).json()
    doc = await _owned_cv(client, db, auth_headers, cv["id"])
    match = await _service(db).match_for_cv(doc, refs=_refs(item))
    assert _text(match) == "generic"


async def test_mark_used_stamps_last_used(client, db, auth_headers):
    item = await _make_item(db, _uid(auth_headers))
    row = await _seed_variant(client, auth_headers, item)
    assert row["last_used_at"] is None
    await _service(db).mark_used([uuid.UUID(row["id"])])
    rows = (await client.get("/api/v1/cv/synth", headers=auth_headers)).json()
    assert rows[0]["last_used_at"] is not None


# ------------------------------------------------------------ plan 69.3 preview


async def test_preview_reports_matches_by_refs(client, auth_headers, db):
    item = await _make_item(db, _uid(auth_headers))
    row = (
        await client.post(
            "/api/v1/cv/synth/generate",
            json={"refs": _refs(item), "action": "summarize"},
            headers=auth_headers,
        )
    ).json()["items"][0]
    await client.patch(
        f"/api/v1/cv/synth/{row['id']}",
        json={"status": "active"},
        headers=auth_headers,
    )
    preview = await client.post(
        "/api/v1/cv/synth/preview",
        json={
            "language": "en",
            "refs": [{"source_key": "experience", "item_id": str(item.id)}],
        },
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["total"] == 1
    assert body["items"][0]["synth_id"] == row["id"]
    assert body["items"][0]["item_id"] == str(item.id)
    assert body["items"][0]["stale"] is False

    pprint_lang = await client.post(
        "/api/v1/cv/synth/preview",
        json={
            "language": "de",
            "refs": [{"source_key": "experience", "item_id": str(item.id)}],
        },
        headers=auth_headers,
    )
    assert pprint_lang.json()["total"] == 0, "language mismatch never matches"


async def test_preview_resolves_context_selection(client, auth_headers, db):
    item = await _make_item(db, _uid(auth_headers))
    row = (
        await client.post(
            "/api/v1/cv/synth/generate",
            json={"refs": _refs(item), "action": "summarize"},
            headers=auth_headers,
        )
    ).json()["items"][0]
    await client.patch(
        f"/api/v1/cv/synth/{row['id']}",
        json={"status": "active"},
        headers=auth_headers,
    )
    preview = await client.post(
        "/api/v1/cv/synth/preview",
        json={
            "language": "en",
            "context": {"mode": "all", "include": [], "exclude": []},
        },
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["total"] == 1
    assert body["items"][0]["item_id"] == str(item.id)


async def test_preview_is_owner_scoped(client, auth_headers, db):
    item = await _make_item(db, _uid(auth_headers))
    await client.post(
        "/api/v1/cv/synth/generate",
        json={"refs": _refs(item), "action": "summarize"},
        headers=auth_headers,
    )
    other = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "other@example.com",
            "password": "supersecret1",
            "full_name": "Other Student",
        },
    )
    other_headers = {"Authorization": "Bearer " + other.json()["access_token"]}
    preview = await client.post(
        "/api/v1/cv/synth/preview",
        json={
            "language": "en",
            "context": {"mode": "all", "include": [], "exclude": []},
        },
        headers=other_headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["total"] == 0, "another user's rows never apply"
