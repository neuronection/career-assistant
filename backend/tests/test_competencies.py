"""Plan 212 S3.5 — evidence-derived NACE competencies."""

import uuid
from datetime import date

from app.models.experience_model import (
    ExperienceAchievement,
    ExperienceItem,
    ExperienceSkill,
)
from app.models.profile_entities_model import Certification
from app.models.taxonomy_model import Skill
from app.models.user_model import UserSkill
from app.services.cv.cv_suggestion_service import bullet_reviews
from app.services.profile.competency_service import (
    COMPETENCIES,
    competency_keys_for_text,
)
from tests.conftest import _uid, register_user


async def _seed_evidence(db, user_id: uuid.UUID) -> None:
    skill = Skill(key="teamwork-test", label="Teamwork", category="soft")
    db.add(skill)
    await db.flush()
    item = ExperienceItem(
        user_id=user_id,
        kind="volunteer",
        title="Community volunteer",
        org_name="Neighbourhood project",
        start=date(2024, 1, 1),
        description="Led a team of five volunteers and presented results to stakeholders.",
        status="active",
    )
    db.add(item)
    await db.flush()
    db.add(
        ExperienceSkill(
            experience_id=item.id,
            skill_id=skill.id,
            role_in_item="primary",
        )
    )
    db.add(
        ExperienceAchievement(
            experience_id=item.id,
            text="Delivered the project on time with six volunteers.",
        )
    )
    db.add(
        Certification(
            user_id=user_id,
            name="Project management certificate",
            issuer="Sample Institute",
            status="active",
        )
    )
    db.add(UserSkill(user_id=user_id, skill_id=skill.id, level=8))
    await db.commit()


async def test_competencies_return_evidence_or_an_honest_empty_state(
    client, auth_headers, db, profile_ready, seeded_catalog
):
    await _seed_evidence(db, uuid.UUID(_uid(auth_headers)))
    response = await client.get("/api/v1/profile/competencies", headers=auth_headers)
    assert response.status_code == 200, response.text
    rows = {row["key"]: row for row in response.json()["competencies"]}
    assert set(rows) == set(COMPETENCIES)
    assert rows["leadership"]["evidence"]
    assert rows["teamwork"]["evidence"]
    assert rows["communication"]["evidence"]
    assert rows["career_management"]["evidence"]
    assert rows["intercultural"]["evidence"] == []
    for row in rows.values():
        assert len(row["evidence"]) <= 4
        assert all("label" in item and "kind" in item for item in row["evidence"])
        assert "score" not in row and "level" not in row


async def test_competencies_are_scoped_to_the_owner(
    client, auth_headers, db, profile_ready, seeded_catalog
):
    other = await register_user(client, "competency-other@example.com")
    await _seed_evidence(db, uuid.UUID(_uid(other)))
    response = await client.get("/api/v1/profile/competencies", headers=auth_headers)
    assert all(row["evidence"] == [] for row in response.json()["competencies"])


def test_competency_matching_avoids_substring_false_positives():
    assert "intercultural" not in competency_keys_for_text("Python programming language")
    assert "career_management" not in competency_keys_for_text("Machine learning")
    assert "leadership" not in competency_keys_for_text("Reconciled the ledger")
    assert "digital_technology" not in competency_keys_for_text(
        "Handled customer queries at the front desk."
    )
    assert "teamwork" in competency_keys_for_text("Cross-functional team")
    assert "intercultural" in competency_keys_for_text("Cross-cultural project")


async def test_certification_issuer_does_not_create_competencies(
    client, auth_headers, db, profile_ready, seeded_catalog
):
    db.add(
        Certification(
            user_id=uuid.UUID(_uid(auth_headers)),
            name="First aid",
            issuer="International SOS",
            status="active",
        )
    )
    await db.commit()
    response = await client.get("/api/v1/profile/competencies", headers=auth_headers)
    rows = {row["key"]: row for row in response.json()["competencies"]}
    assert all(item["label"] != "First aid" for item in rows["intercultural"]["evidence"])


async def test_linked_and_claimed_skill_is_not_duplicated(
    client, auth_headers, db, profile_ready, seeded_catalog
):
    await _seed_evidence(db, uuid.UUID(_uid(auth_headers)))
    response = await client.get("/api/v1/profile/competencies", headers=auth_headers)
    teamwork = next(row for row in response.json()["competencies"] if row["key"] == "teamwork")
    skill_rows = [row for row in teamwork["evidence"] if row["kind"] == "skill"]
    assert len(skill_rows) == 1


def test_bullet_reviews_expose_competency_keys():
    review = bullet_reviews(
        ["Led a cross-functional team and presented the results to stakeholders."]
    )[0]
    assert "leadership" in review.competency_keys
    assert "teamwork" in review.competency_keys
    assert "communication" in review.competency_keys
