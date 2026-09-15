"""Session digest cache (plan 81): signatures, store, isolation."""

from sqlalchemy import select

from app.models.chat_model import ChatSession
from app.services import chat_digest_cache
from app.services.experience_service import ExperienceService
from app.services.profile_service import ProfileService

from tests.test_chat_profile_ops import _auth_user


def _sig_after(before: str | None, after: str | None) -> bool:
    return before != after


async def test_signature_tracks_experience_writes(db, auth_headers):
    user = await _auth_user(db)
    base = await chat_digest_cache.digest_signatures(
        db, user.id, ["my_experience", "my_skills", "my_education", "my_profile_digest"]
    )
    item = await ExperienceService(db).create_item(
        user.id, {"title": "P1", "kind": "project", "open_ended": True}
    )
    after_create = await chat_digest_cache.digest_signatures(
        db, user.id, ["my_experience"]
    )

    # Stroked base vs post-create: base was already captured
    # post-create for the other tables; assert create bumped experience.
    assert _sig_after(base["my_experience"], after_create["my_experience"])
    skills_after = await chat_digest_cache.digest_signatures(db, user.id, ["my_skills"])
    assert base["my_skills"] == skills_after["my_skills"]

    await ExperienceService(db).update_item(user.id, item.id, {"title": "P1b"})
    after_update = await chat_digest_cache.digest_signatures(
        db, user.id, ["my_experience"]
    )
    assert _sig_after(after_create["my_experience"], after_update["my_experience"])

    await ExperienceService(db).delete_item(user.id, item.id)
    after_delete = await chat_digest_cache.digest_signatures(
        db, user.id, ["my_experience"]
    )
    assert _sig_after(after_update["my_experience"], after_delete["my_experience"])
    assert after_delete["my_experience"] == base["my_experience"]


async def test_education_sig_tracks_certifications(db, auth_headers):
    user = await _auth_user(db)
    base_sig = (
        await chat_digest_cache.digest_signatures(db, user.id, ["my_education"])
    )["my_education"]
    from app.services.profile_entities_service import ProfileEntitiesService
    from app.schemas.profile_entities import CertificationIn

    service = ProfileEntitiesService(db)
    cert = await service.create_certification(
        user.id, CertificationIn(name="AWS CCP", issuer="Amazon")
    )
    after = await chat_digest_cache.digest_signatures(db, user.id, ["my_education"])
    assert _sig_after(base_sig, after["my_education"])
    await service.delete_certification(cert.id, user.id)
    back = await chat_digest_cache.digest_signatures(db, user.id, ["my_education"])
    assert back["my_education"] == base_sig


async def test_profile_section_edit_bumps_profile_sig(db, auth_headers):
    user = await _auth_user(db)
    base_sig = (
        await chat_digest_cache.digest_signatures(db, user.id, ["my_profile_digest"])
    )["my_profile_digest"]
    from app.schemas.profile import BasicSection, ProfileSectionUpdate

    await ProfileService(db).update(
        user.id,
        ProfileSectionUpdate(basics=BasicSection(full_name="Test User", city="Berlin")),
    )
    after = await chat_digest_cache.digest_signatures(
        db, user.id, ["my_profile_digest"]
    )
    assert _sig_after(base_sig, after["my_profile_digest"])


async def test_save_load_roundtrip_and_isolation(db, auth_headers):
    user = await _auth_user(db)
    session = ChatSession(
        user_id=user.id, title="t", context={"surface": "chat", "cv_id": "x"}
    )
    db.add(session)
    await db.commit()

    changed = chat_digest_cache.save(
        session,
        {"my_experience": chat_digest_cache.fresh_entry({"items": []}, "sig-a")},
    )
    assert changed
    await db.commit()

    loaded = chat_digest_cache.load(
        (await db.execute(select(ChatSession))).scalars().one()
    )
    assert loaded["my_experience"]["payload"] == {"items": []}
    assert loaded["my_experience"]["sig"] == "sig-a"
    assert "T" in loaded["my_experience"]["fetched_at"]

    # Echo outlets strip the reserved key, never the session bindings.
    echo = chat_digest_cache.context_without_cache(session.context)
    assert "profile_digests" not in echo
    assert echo["surface"] == "chat" and echo["cv_id"] == "x"
    assert chat_digest_cache.context_without_cache(None) is None
    assert chat_digest_cache.context_without_cache({"cv_id": "y"}) == {"cv_id": "y"}

    # Empty payload saves are no-ops and never grow unknown keys.
    session.context["future_key"] = 1
    assert chat_digest_cache.save(session, {}) is False
