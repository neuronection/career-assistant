"""Plan 225 S3: metric registry cache, RIASEC totality, and the no-pack contract."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.models.metric_model import MetricCategoryAnchor, MetricDimension, UserMetricProfile
from app.services.catalog.metric_registry import metric_registry
from tests.conftest import _uid


def _dimension(key: str, group: str) -> MetricDimension:
    return MetricDimension(
        key=key,
        label=key,
        group=group,
        description="",
        sources=[],
        consumers=[],
    )


async def test_metric_registry_caches_until_invalidated(db):
    db.add(_dimension("values.autonomy", "value"))
    db.add(MetricCategoryAnchor(category="synthetic-science", letter="investigative"))
    await db.commit()

    snapshot = await metric_registry.snapshot(db)
    assert snapshot.available
    assert snapshot.letter_for("synthetic-science") == "investigative"
    assert snapshot.letter_for(None) is None
    assert snapshot.letter_for("unmapped") is None
    assert "values.autonomy" in snapshot.dimension_keys

    db.add(_dimension("interest.social", "interest"))
    await db.commit()
    cached = await metric_registry.snapshot(db)
    assert "interest.social" not in cached.dimension_keys, "the snapshot is cached"

    metric_registry.invalidate()
    fresh = await metric_registry.snapshot(db)
    assert "interest.social" in fresh.dimension_keys


async def test_retired_rows_leave_the_registry(db):
    dimension = _dimension("values.autonomy", "value")
    anchor = MetricCategoryAnchor(category="synthetic-science", letter="investigative")
    db.add_all([dimension, anchor])
    await db.commit()

    assert (await metric_registry.snapshot(db)).available
    dimension.status = "retired"
    anchor.status = "retired"
    await db.commit()
    metric_registry.invalidate()

    empty = await metric_registry.snapshot(db)
    assert empty.available is False
    assert empty.dimension_keys == frozenset()
    assert empty.letter_for("synthetic-science") is None


async def test_riasec_vocabulary_is_total_both_directions(db):
    from app.seeds.bank_stamp import stamp_bank_identities
    from app.seeds.metrics import RIASEC_LETTERS, seed_metric_dimensions

    await seed_metric_dimensions(db)
    await stamp_bank_identities(db)
    await db.commit()

    snapshot = await metric_registry.snapshot(db)
    assert snapshot.available
    assert snapshot.anchors
    anchored_letters = set(snapshot.anchors.values())
    assert anchored_letters <= set(RIASEC_LETTERS), "every anchor letter is a Holland code"
    assert {f"interest.{letter}" for letter in RIASEC_LETTERS} <= snapshot.dimension_keys, (
        "every Holland code has an interest dimension"
    )


async def test_profile_save_succeeds_without_the_metric_bank(
    client, auth_headers, fixture_taxonomy, db
):
    saved = await client.put(
        "/api/v1/profile",
        json={
            "interests": [
                {"tag_key": "technology-software", "weight": 5, "source": "self"},
            ],
            "work_preferences": {"teamwork": 5, "pace": 2},
        },
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text

    rows = (
        (
            await db.execute(
                select(UserMetricProfile).where(
                    UserMetricProfile.user_id == UUID(_uid(auth_headers))
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == [], "no metric bank means no metric profile inserts"

    direct = await client.post(
        "/api/v1/metrics/me/interest-affinity/recompute", headers=auth_headers
    )
    assert direct.status_code == 409, direct.text
    detail = direct.json()["detail"]
    assert "METRIC_BANK_NOT_LOADED" in detail
    assert "neuronection-reference-banks" in detail


async def _answers_for(questions: list[dict]) -> list[dict]:
    answers = []
    for question in questions:
        kind = question["kind"]
        if kind == "scenario_mcq":
            choice = {"option_id": question["options"][0]["id"]}
        elif kind == "time_allocation":
            choice = {"weights": {question["options"][0]["id"]: 100}}
        elif kind == "ranking":
            choice = {"order": [option["id"] for option in question["options"]]}
        else:
            choice = {"value": 7}
        answers.append({"question_id": question["id"], "answer": choice})
    return answers


async def test_assessment_completion_succeeds_without_the_metric_bank(
    client, auth_headers, seeded_catalog, db
):
    created = await client.post(
        "/api/v1/assessments",
        json={"kind": "custom", "context": {"phase_order": [2]}},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["questions"]

    saved = await client.post(
        f"/api/v1/assessments/{run['id']}/answers",
        json={"answers": await _answers_for(run["questions"])},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    done = await client.post(f"/api/v1/assessments/{run['id']}/advance", headers=auth_headers)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"

    rows = (
        (
            await db.execute(
                select(UserMetricProfile).where(
                    UserMetricProfile.user_id == UUID(_uid(auth_headers))
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == [], "a completed assessment skips metric writes with no bank"
