"""Plan 212 S1.4b — eligibility gates (visa, language) and overrides.

Unknown never excludes; a per-user override drops the gate without
invalidating the cached fit. The API persists the override on the user's
`posting_interactions` row.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.models.posting_model import PostingInteraction
from app.models.profile_entities_model import EducationItem
from app.models.user_model import Profile
from app.services.postings.posting_fit_service import get_posting_fit
from app.services.profile.grades import grade_ordinal
from tests.conftest import _make_posting, _uid


async def _set_profile(db, user_id, *, work_auth=None, languages=None):
    profile = (
        (await db.execute(select(Profile).where(Profile.user_id == user_id))).scalars().first()
    )
    profile.basics = {**(profile.basics or {}), "work_authorization": work_auth}
    profile.academics = {**(profile.academics or {}), "languages": languages or []}
    flag_modified(profile, "basics")
    flag_modified(profile, "academics")
    await db.commit()


async def _posting(db, source, external_id, *, work_auth=None, languages=None):
    posting = await _make_posting(db, source, external_id=external_id)
    posting.work_authorization = work_auth
    posting.extract = {
        "language_requirements": [
            {
                "code": code,
                "level": level,
                "evidence_quote": f"{code} at {level}",
                "confidence": 0.9,
            }
            for code, level in (languages or [])
        ]
    }
    posting.extract_version = 6
    await db.commit()
    await db.refresh(posting)
    return posting


async def _fit(db, user_id, posting):
    return await get_posting_fit(db, user_id, posting)


async def test_visa_gate_requires_sponsorship_and_a_no_sponsor_signal(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    user_id = _uid(auth_headers)
    await _set_profile(db, user_id, work_auth="needs_sponsorship")

    none = await _posting(db, source, "elig-visa-none", work_auth="none")
    assert (await _fit(db, user_id, none))["gates"] == ["visa"]

    citizens = await _posting(db, source, "elig-visa-citizens", work_auth="citizens_only")
    assert (await _fit(db, user_id, citizens))["gates"] == ["visa"]

    unknown = await _posting(db, source, "elig-visa-unknown", work_auth=None)
    assert (await _fit(db, user_id, unknown))["gates"] == []

    case_by_case = await _posting(db, source, "elig-visa-case", work_auth="case_by_case")
    assert (await _fit(db, user_id, case_by_case))["gates"] == []


async def test_visa_gate_unknown_user_never_excludes(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    user_id = _uid(auth_headers)
    await _set_profile(db, user_id, work_auth=None)
    posting = await _posting(db, source, "elig-user-unknown", work_auth="none")
    assert (await _fit(db, user_id, posting))["gates"] == []


async def test_visa_override_clears_the_gate(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    user_id = _uid(auth_headers)
    await _set_profile(db, user_id, work_auth="needs_sponsorship")
    posting = await _posting(db, source, "elig-visa-override", work_auth="none")
    db.add(
        PostingInteraction(
            user_id=user_id,
            posting_id=posting.id,
            gate_overrides={"visa": True},
        )
    )
    await db.commit()
    assert (await _fit(db, user_id, posting))["gates"] == []


async def test_language_gate_uses_the_required_level(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    user_id = _uid(auth_headers)
    await _set_profile(db, user_id, languages=[{"code": "de", "level": "basic"}])

    advanced = await _posting(db, source, "elig-lang-advanced", languages=[("de", "advanced")])
    assert (await _fit(db, user_id, advanced))["gates"] == ["language"]

    basic = await _posting(db, source, "elig-lang-basic", languages=[("de", "basic")])
    assert (await _fit(db, user_id, basic))["gates"] == []

    await _set_profile(db, user_id, languages=[{"code": "de", "level": "native"}])
    native = await _posting(db, source, "elig-lang-native", languages=[("de", "advanced")])
    assert (await _fit(db, user_id, native))["gates"] == []


async def test_language_override_clears_the_gate(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    user_id = _uid(auth_headers)
    await _set_profile(db, user_id, languages=[])
    posting = await _posting(db, source, "elig-lang-override", languages=[("de", "advanced")])
    db.add(
        PostingInteraction(
            user_id=user_id,
            posting_id=posting.id,
            gate_overrides={"language": True},
        )
    )
    await db.commit()
    assert (await _fit(db, user_id, posting))["gates"] == []


async def test_gate_override_api_persists_and_clears(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    user_id = _uid(auth_headers)
    await _set_profile(db, user_id, work_auth="needs_sponsorship")
    posting = await _posting(db, source, "elig-api", work_auth="none")
    assert (await _fit(db, user_id, posting))["gates"] == ["visa"]

    response = await client.post(
        f"/api/v1/postings/{posting.ref}/gate-override",
        json={"gate": "visa", "allow": True},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["gate_overrides"] == {"visa": True}
    assert (await _fit(db, user_id, posting))["gates"] == []

    response = await client.post(
        f"/api/v1/postings/{posting.ref}/gate-override",
        json={"gate": "visa", "allow": False},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["gate_overrides"] == {}
    assert (await _fit(db, user_id, posting))["gates"] == ["visa"]


async def test_gate_override_api_requires_auth(db, client, source):
    posting = await _make_posting(db, source, external_id=f"elig-auth-{uuid.uuid4().hex[:6]}")
    response = await client.post(
        f"/api/v1/postings/{posting.ref}/gate-override",
        json={"gate": "visa", "allow": True},
    )
    assert response.status_code == 401


def test_grade_ordinal_is_scale_scoped():
    assert grade_ordinal("uk_honours", 2.1) == Decimal("75.00")
    assert grade_ordinal("gpa_4", 3.7) == Decimal("92.50")
    assert grade_ordinal("gpa_10", 7.5) == Decimal("75.00")
    assert grade_ordinal("de_note", 1.7) == Decimal("82.50")
    assert grade_ordinal("percentage", 75) == Decimal("75.00")
    assert grade_ordinal("other", 75) is None
    assert grade_ordinal("gpa_4", 5.0) is None


async def test_grade_gate_uses_the_same_scale_and_honors_override(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    user_id = _uid(auth_headers)
    db.add(
        EducationItem(
            user_id=user_id,
            institution="Example University",
            program="BSc",
            level="bachelor",
            grade_scale="uk_honours",
            grade_value=Decimal("2.2"),
            grade_ordinal=Decimal("65.00"),
            status="active",
            source="self_report",
        )
    )
    await db.commit()

    posting = await _posting(db, source, "elig-grade")
    posting.extract = {
        "grade_requirement": {
            "scale": "uk_honours",
            "value": 2.1,
            "evidence_quote": "minimum 2:1",
            "confidence": 0.9,
        }
    }
    posting.extract_version = 6
    await db.commit()
    assert (await _fit(db, user_id, posting))["gates"] == ["grade"]

    db.add(
        PostingInteraction(
            user_id=user_id,
            posting_id=posting.id,
            gate_overrides={"grade": True},
        )
    )
    await db.commit()
    assert (await _fit(db, user_id, posting))["gates"] == []

    unknown = await _posting(db, source, "elig-grade-unknown")
    unknown.extract = {
        "grade_requirement": {
            "scale": "de_note",
            "value": 1.7,
            "evidence_quote": "Note 1,7",
            "confidence": 0.9,
        }
    }
    unknown.extract_version = 6
    await db.commit()
    assert (await _fit(db, user_id, unknown))["gates"] == []


def test_language_codes_map_iso_639_2_and_reject_unknown_tokens():
    from app.services.postings.language_codes import is_language_code, normalize_language_code

    assert normalize_language_code("English") == "en"
    assert normalize_language_code("eng") == "en"
    assert normalize_language_code("ger") == "de"
    assert normalize_language_code("en") == "en"
    assert normalize_language_code("xxx") is None
    assert is_language_code("en") is True
    assert is_language_code("eng") is False


async def test_unmapped_language_token_never_gates(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    user_id = _uid(auth_headers)
    await _set_profile(db, user_id, languages=[])
    posting = await _posting(db, source, "elig-lang-unmapped", languages=[("xxx", "advanced")])
    assert (await _fit(db, user_id, posting))["gates"] == []


async def test_override_applies_in_the_batch_seam(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    from app.services.postings.posting_fit_service import get_posting_fits_batch

    user_id = _uid(auth_headers)
    await _set_profile(db, user_id, work_auth="needs_sponsorship")
    posting = await _posting(db, source, "elig-batch", work_auth="none")
    db.add(
        PostingInteraction(
            user_id=user_id,
            posting_id=posting.id,
            gate_overrides={"visa": True},
        )
    )
    await db.commit()
    batch = await get_posting_fits_batch(db, user_id, [posting])
    assert batch[posting.id]["gates"] == []


async def test_duplicate_profile_language_keeps_the_highest_level(
    db, client, auth_headers, profile_ready, seeded_catalog, source, kinds
):
    user_id = _uid(auth_headers)
    await _set_profile(
        db,
        user_id,
        languages=[
            {"code": "de", "level": "basic"},
            {"code": "German", "level": "native"},
        ],
    )
    posting = await _posting(db, source, "elig-lang-dupe", languages=[("de", "advanced")])
    assert (await _fit(db, user_id, posting))["gates"] == []
