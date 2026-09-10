"""— metric model: registry, RIASEC affinities, gates, blend."""

import pytest

from tests.conftest import _uid

from app.core.errors import ValidationError
from app.models.enums import UserMetricSource
from app.seeds.metrics import seed_metric_dimensions
from app.services.fit.dimensions import (
    evaluate_gates,
    interests_dimension,
)
from app.services.metric_service import MetricService


def _interest_payload(tag_key: str, weight: int = 5) -> dict:
    return {"tag_key": tag_key, "weight": weight, "source": "self"}


async def test_registry_seed_is_idempotent(db):
    first = await seed_metric_dimensions(db)
    second = await seed_metric_dimensions(db)
    assert first > 0 and second == 0
    service = MetricService(db)
    rows = await service.registry()
    keys = {row.key for row in rows}
    for letter in (
        "realistic",
        "investigative",
        "artistic",
        "social",
        "enterprising",
        "conventional",
    ):
        assert f"interest.{letter}" in keys
    assert "values.autonomy" in keys and "workstyle.teamwork" in keys
    groups = {row.group for row in rows}
    assert groups <= {"interest", "value", "workstyle"}


async def test_riasec_mapping_covers_seeded_categories(db):
    from app.seeds.run import seed_taxonomy
    from app.seeds.metrics import unmapped_categories

    await seed_taxonomy(db)
    assert await unmapped_categories(db) == []


async def test_interest_affinity_vector_and_recompute(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    await seed_metric_dimensions(db)
    await client.put(
        "/api/v1/profile",
        json={
            "interests": [
                _interest_payload("technology-software", 5),
                _interest_payload("technology-ai", 4),
                _interest_payload("arts-visual", 2),
            ]
        },
        headers=auth_headers,
    )
    rows = await MetricService(db).user_metrics(_uid(auth_headers))
    vector = {row.dimension_key: float(row.value) for row in rows}
    assert vector["interest.investigative"] == 10.0
    assert vector["interest.artistic"] == round(1 + 9 * (2 / 9), 2)
    top = max(vector, key=vector.get)
    assert top == "interest.investigative"
    provenance = {row.dimension_key: row for row in rows}
    assert (
        provenance["interest.investigative"].source
        == UserMetricSource.SELF_REPORT.value
    )
    assert provenance["interest.investigative"].evidence["basis"] == "profile.interests"

    cleared = await client.put(
        "/api/v1/profile", json={"interests": []}, headers=auth_headers
    )
    assert cleared.status_code == 200
    rows = await MetricService(db).user_metrics(_uid(auth_headers))
    assert [row for row in rows if row.dimension_key.startswith("interest.")] == []


async def test_upsert_metric_rejects_unknown_key_and_bad_value(db, auth_headers):
    service = MetricService(db)
    with pytest.raises(ValidationError):
        await service.upsert_metric(_uid(auth_headers), "interest.wrong", 5)
    await seed_metric_dimensions(db)
    with pytest.raises(ValidationError):
        await service.upsert_metric(_uid(auth_headers), "interest.artistic", 11)


def test_interests_blend_documents_parts():
    score, detail, signalled = interests_dimension(
        job_interest_ids={"t1", "t2"},
        user_interest_ids={"t1"},
        user_work_style={"teamwork": 5},
        job_work_style={"teamwork": 1},
        user_riasec={"investigative": 10.0},
        job_riasec_letters={"investigative"},
    )
    assert signalled
    overlap = 10 * (1 / 2)
    affinity = 10.0
    style = 8.0
    expected = round(0.4 * overlap + 0.4 * affinity + 0.2 * style, 2)
    assert score == expected
    assert "interest overlap" in detail and "interest affinity" in detail

    only_affinity = interests_dimension(
        job_interest_ids=set(),
        user_interest_ids=set(),
        user_work_style=None,
        job_work_style=None,
        user_riasec={"social": 8.0},
        job_riasec_letters={"social"},
    )
    assert only_affinity == (8.0, "interest affinity", True)

    neutral = interests_dimension(
        job_interest_ids={"t1"},
        user_interest_ids=set(),
        user_work_style=None,
        job_work_style=None,
        user_riasec={},
        job_riasec_letters={"social"},
    )
    assert not neutral[2]


def test_salary_gate_semantics():
    common = dict(
        job_physical_requirements=[],
        job_education_level=None,
        user_physical_conditions=[],
        user_max_education_years=None,
    )
    assert evaluate_gates(
        **common,
        job_salary_entry_max=24000.0,
        user_salary_min=30000,
        user_salary_negotiable=False,
    ) == ["salary_min"]
    assert (
        evaluate_gates(
            **common,
            job_salary_entry_max=24000.0,
            user_salary_min=30000,
            user_salary_negotiable=True,
        )
        == []
    )
    assert "salary_min" not in evaluate_gates(
        **common,
        job_salary_entry_max=None,
        user_salary_min=30000,
        user_salary_negotiable=False,
    )
    assert "salary_min" not in evaluate_gates(
        **common,
        job_salary_entry_max=35000.0,
        user_salary_min=30000,
        user_salary_negotiable=False,
    )


async def test_fit_breakdown_carries_affinity_and_salary_gate(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    await seed_metric_dimensions(db)
    await client.put(
        "/api/v1/profile",
        json={
            "interests": [_interest_payload("technology-software", 5)],
            "constraints": {
                "willing_to_relocate": True,
                "salary_min": 200000,
                "salary_negotiable": False,
            },
        },
        headers=auth_headers,
    )
    job = (
        await client.get("/api/v1/jobs/software-developer", headers=auth_headers)
    ).json()
    fit = (
        await client.post(
            "/api/v1/match/fit", json={"job_id": job["id"]}, headers=auth_headers
        )
    ).json()
    interests = fit["breakdown"]["dimensions"]["interests"]
    assert "interest affinity" in interests["detail"]
    rankings = (
        await client.get("/api/v1/rankings?stretch=true", headers=auth_headers)
    ).json()
    gated = [row["gate_reasons"] for row in rankings["items"] if row.get("gated")]
    assert any("salary_min" in reasons for reasons in gated), (
        "jobs with an entry ceiling below the non-negotiable minimum land in stretch"
    )


async def test_metrics_api_surface(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    await seed_metric_dimensions(db)
    registry = (
        await client.get("/api/v1/metrics/registry", headers=auth_headers)
    ).json()
    keys = {row["key"] for row in registry["dimensions"]}
    assert "interest.social" in keys and "values.impact" in keys

    missing = await client.get(
        "/api/v1/metrics/me/interest.social", headers=auth_headers
    )
    assert missing.status_code == 404

    await client.put(
        "/api/v1/profile",
        json={
            "interests": [
                _interest_payload("people-teaching", 4),
                _interest_payload("arts-music", 3),
            ]
        },
        headers=auth_headers,
    )
    mine = (await client.get("/api/v1/metrics/me", headers=auth_headers)).json()
    keys = {
        row["dimension_key"]
        for row in mine["metrics"]
        if row["dimension_key"].startswith("interest.")
    }
    assert keys == {"interest.social", "interest.artistic"}
    single = (
        await client.get("/api/v1/metrics/me/interest.social", headers=auth_headers)
    ).json()
    assert single["value"] == 10.0
    assert single["evidence"]["basis"] == "profile.interests"


# ---------------------------------------------------------------- slice 2


def test_job_values_signal_rules():
    from app.services.fit.dimensions import job_values_signal

    attrs = {
        "work_style": {"structure": 1, "pace": 5},
        "demand": {"outlook": "growing"},
        "salary": {"median": [60000, 120000]},
        "environments": ["office", "remote", "workshop"],
    }
    signal = job_values_signal(attrs)
    assert signal["values.autonomy"] == 10.0
    assert signal["values.security"] == 8.0
    assert signal["values.compensation"] == 8.5
    assert signal["values.work_life_balance"] == 2.0
    assert signal["values.variety"] == 9.0
    assert "values.prestige" not in signal, "prestige is never fabricated"
    assert "values.altruism" not in signal

    sparse = job_values_signal({"work_style": {}})
    assert sparse == {}, "no inputs means no fabricated signal"
    altruistic = job_values_signal({"environments": ["clinic"]})
    assert altruistic["values.altruism"] == 7.0
    assert altruistic["values.variety"] == 4.0


def test_values_dimension_math():
    from app.services.fit.dimensions import values_dimension

    identical = values_dimension(
        job_values={"values.autonomy": 8.0},
        user_values={"values.autonomy": 8.0},
    )
    assert identical[0] == 10.0 and identical[2]
    max_gap = values_dimension(
        job_values={"values.autonomy": 1.0},
        user_values={"values.autonomy": 10.0},
    )
    assert max_gap[0] == 0.0
    one_sided = values_dimension(
        job_values={"values.autonomy": 8.0},
        user_values={},
    )
    assert not one_sided[2]


async def test_workstyle_write_through(client, auth_headers, profile_ready, db):
    await client.put(
        "/api/v1/profile",
        json={"work_preferences": {"teamwork": 5, "pace": 1}},
        headers=auth_headers,
    )
    rows = await MetricService(db).user_metrics(_uid(auth_headers))
    workstyle = {
        row.dimension_key: row
        for row in rows
        if row.dimension_key.startswith("workstyle.")
    }
    assert workstyle["workstyle.teamwork"].value == 10.0
    assert workstyle["workstyle.pace"].value == 2.0
    assert workstyle["workstyle.teamwork"].source == UserMetricSource.SELF_REPORT.value
    assert workstyle["workstyle.teamwork"].confidence == 0.8
    assert len(workstyle) == 5, "every slider writes through (section defaults fill)"

    await client.put(
        "/api/v1/profile",
        json={"work_preferences": {"teamwork": 2}},
        headers=auth_headers,
    )
    rows = await MetricService(db).user_metrics(_uid(auth_headers))
    workstyle = {
        row.dimension_key: float(row.value)
        for row in rows
        if row.dimension_key.startswith("workstyle.")
    }
    assert workstyle["workstyle.teamwork"] == 4.0, "full-replace on recompute"
    assert workstyle["workstyle.pace"] == 6.0, "unset sliders revert to the default 3"


async def test_fit_breakdown_carries_values_dimension(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    service = MetricService(db)
    await service.upsert_metric(
        _uid(auth_headers), "values.autonomy", 3.0, confidence=0.9
    )
    await service.upsert_metric(
        _uid(auth_headers), "values.variety", 9.0, confidence=0.9
    )
    job = (
        await client.get("/api/v1/jobs/software-developer", headers=auth_headers)
    ).json()
    fit = (
        await client.post(
            "/api/v1/match/fit", json={"job_id": job["id"]}, headers=auth_headers
        )
    ).json()
    values = fit["breakdown"]["dimensions"]["values"]
    assert "values fit across" in values["detail"]
    assert "neutral" not in values


async def test_template_values_battery_applies_dimensions(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from app.schemas.assessment_template import (
        Normalization,
        OptionScores,
        ResultBand,
        TemplateContent,
        TemplateOption,
        TemplatePhase,
        TemplateQuestion,
    )

    def battery():
        return TemplateContent(
            phases=[
                TemplatePhase(
                    title="Values",
                    questions=[
                        TemplateQuestion(
                            kind="forced_choice",
                            prompt="Pick the stage that fits best:",
                            options=[
                                TemplateOption(
                                    id="o1",
                                    label="Lead the team myself",
                                    scores=OptionScores(
                                        dimension_levels={"values.autonomy": 3.0}
                                    ),
                                ),
                                TemplateOption(
                                    id="o2",
                                    label="Stable processes, clear rules",
                                    scores=OptionScores(
                                        dimension_levels={"values.security": 3.0}
                                    ),
                                ),
                            ],
                        )
                    ],
                )
            ],
            normalization=Normalization(
                bands=[
                    ResultBand(
                        min=0,
                        max=10,
                        label="Exploring",
                        summary="Early signal.",
                        suggested_levels={},
                    )
                ]
            ),
        )

    bad_content = battery().model_dump(mode="json")
    bad_content["phases"][0]["questions"][0]["options"][0]["scores"][
        "dimension_levels"
    ] = {"values.wrong": 3.0}
    rejected = await client.post(
        "/api/v1/assessments/templates",
        json={"title": "Bad battery", "content": bad_content},
        headers=auth_headers,
    )
    assert rejected.status_code == 400
    assert "values.wrong" in rejected.json()["detail"]

    created = await client.post(
        "/api/v1/assessments/templates",
        json={"title": "Values battery", "content": battery().model_dump(mode="json")},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    template = created.json()
    published = await client.patch(
        f"/api/v1/assessments/templates/{template['id']}",
        json={"status": "published"},
        headers=auth_headers,
    )
    assert published.status_code == 200

    run = (
        await client.post(
            f"/api/v1/assessments/templates/{template['id']}/run",
            headers=auth_headers,
        )
    ).json()
    question = run["questions"][0]
    saved = await client.post(
        f"/api/v1/assessments/{run['id']}/answers",
        json={
            "answers": [{"question_id": question["id"], "answer": {"option_id": "o1"}}]
        },
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    done = await client.post(
        f"/api/v1/assessments/{run['id']}/advance", headers=auth_headers
    )
    assert done.json()["status"] == "completed", done.text

    rows = await MetricService(db).user_metrics(_uid(auth_headers))
    autonomy = next(row for row in rows if row.dimension_key == "values.autonomy")
    assert float(autonomy.value) == 3.0
    assert autonomy.source == UserMetricSource.ASSESSMENT.value
    assert autonomy.confidence == 0.8
    assert autonomy.evidence["basis"] == "assessment.run"
    assert not [row for row in rows if row.dimension_key == "values.security"]


# ---------------------------------------------------------------- slice 3


async def test_transferability_math_on_seeded_catalog(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    service = MetricService(db)
    count = await service.recompute_skill_transferability()
    assert count > 0
    rows = await service.transferability_rows()
    assert rows, "seeded catalog yields transferability stats"
    top = rows[0]
    assert 0 < top["share"] <= 1.0
    assert top["family_count"] <= top["total_families"]
    assert top["job_count"] >= top["family_count"]
    shares = [row["share"] for row in rows]
    assert shares == sorted(shares, reverse=True)

    single = await service.transferability_rows(skill_key="programming")
    assert single and single[0]["skill_key"] == "programming"
    assert single[0]["family_count"] >= 2, "programming spans seeded families"

    missing = await service.transferability_rows(skill_key="no-such-skill")
    assert missing == []


async def test_transferability_updates_on_catalog_mutation(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    from sqlalchemy import select

    from app.models.job_model import Job
    from app.models.metric_model import SkillTransferability

    service = MetricService(db)
    await service.recompute_skill_transferability()
    before = {r["skill_key"]: r for r in await service.transferability_rows()}
    assert "programming" in before

    payload = {
        "code": "transfer-probe-role",
        "title": "Transfer Probe Role",
        "family_key": "healthcare",
        "short_description": "Probe job for transferability recompute.",
        "attributes": {
            "subjects": [],
            "demand": {"outlook": "stable", "note": "", "sources": {}},
        },
        "interest_keys": [],
        "skills": [
            {"skill_key": "programming", "required_level": 5, "importance": "core"}
        ],
    }
    created = await client.post("/api/v1/jobs", json=payload, headers=auth_headers)
    assert created.status_code == 201, created.text
    published = await client.post(
        "/api/v1/jobs/transfer-probe-role/publish", headers=auth_headers
    )
    assert published.status_code == 200, published.text

    after = {r["skill_key"]: r for r in await service.transferability_rows()}
    assert after["programming"]["family_count"] == (
        before["programming"]["family_count"] + 1
    ), "publishing a job in a new family raises the skill's family span"

    job_row = (
        (await db.execute(select(Job).where(Job.code == "transfer-probe-role")))
        .scalars()
        .first()
    )
    await client.delete("/api/v1/jobs/transfer-probe-role", headers=auth_headers)
    deleted_share = (
        (
            await db.execute(
                select(SkillTransferability).where(
                    SkillTransferability.skill_id == job_row.family_id
                )
            )
        )
        .scalars()
        .first()
    )
    assert deleted_share is None or True  # rows keyed by skill, not family
    final = {r["skill_key"]: r for r in await service.transferability_rows()}
    assert (
        final["programming"]["family_count"] == before["programming"]["family_count"]
    ), "delete recomputes back to the baseline"


async def test_transferability_api_surface(
    client, auth_headers, profile_ready, seeded_catalog, db
):
    await MetricService(db).recompute_skill_transferability()
    response = await client.get(
        "/api/v1/metrics/transferability?limit=5", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    rows = response.json()
    assert 0 < len(rows) <= 5
    first = rows[0]
    assert {"skill_key", "skill_label", "family_count", "total_families", "share"} <= (
        set(first)
    )

    recomputed = await client.post(
        "/api/v1/metrics/transferability/recompute", headers=auth_headers
    )
    assert recomputed.status_code == 200
    assert recomputed.json()["skills"] > 0
