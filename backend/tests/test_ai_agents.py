from app.ai.agents.job_generator import generate_jobs
from app.ai.agents.match_scorer import score_match
from app.ai.agents.profile_analyst import analyze_profile
from app.ai.agents.relation_suggester import suggest_relations
from app.ai.agents.university_parser import parse_universities
from app.ai.provider import StructuredAIError, ainvoke_structured
from app.ai.schemas import ChatReply, ProfileInsight
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType
from app.seeds.run import seed_taxonomy
from sqlalchemy import select


async def test_profile_analyst_returns_structured_insight(db, seeded_catalog):
    from app.models.taxonomy_model import InterestTag

    i, s = await seed_taxonomy(db)
    from app.models.user_model import Profile, User, UserInterest
    from app.core.security import hash_password

    user = User(email="a@example.com", password_hash=hash_password("password123"))
    db.add(user)
    await db.flush()
    profile = Profile(user_id=user.id)
    db.add(profile)
    await db.flush()
    tag = (
        (
            await db.execute(
                select(InterestTag).where(InterestTag.key == "technology-software")
            )
        )
        .scalars()
        .first()
    )
    db.add(UserInterest(user_id=user.id, interest_tag_id=tag.id, weight=5))
    await db.commit()

    insight = await analyze_profile(db, user.id, profile)
    assert isinstance(insight, ProfileInsight)
    assert insight.summary
    assert "technology-software" not in insight.suggested_interest_keys


async def test_job_generator_valid_and_deduped(
    db, client, auth_headers, seeded_catalog
):
    from app.seeds.run import seed_taxonomy
    from app.models.taxonomy_model import InterestTag, Skill
    from app.models.job_model import JobFamily, Job

    await seed_taxonomy(db)
    families = (await db.execute(select(JobFamily))).scalars().all()
    interests = (await db.execute(select(InterestTag.key))).scalars().all()
    skills = (await db.execute(select(Skill.key))).scalars().all()
    existing = (await db.execute(select(Job.code))).scalars().all()

    drafts = await generate_jobs(
        db,
        None,
        mode="general",
        count=3,
        family_keys=[f.key for f in families],
        interest_keys=list(interests),
        skill_keys=list(skills),
        existing_codes=list(existing),
    )
    assert len(drafts.drafts) == 3
    family_keys = {f.key for f in families}
    for draft in drafts.drafts:
        assert draft.family_key in family_keys
        assert draft.code not in existing
    for rel in drafts.relation_suggestions:
        codes = {d.code for d in drafts.drafts}
        assert rel.from_code in codes and rel.to_code in codes


async def test_match_scorer_bounds_and_prereqs(
    db, client, auth_headers, seeded_catalog
):
    from app.core.security import hash_password
    from app.models.user_model import Profile, User, UserInterest
    from app.models.taxonomy_model import InterestTag
    from app.services.job_service import JobService

    user = User(email="scorer@example.com", password_hash=hash_password("password123"))
    db.add(user)
    await db.flush()
    profile = Profile(user_id=user.id)
    db.add(profile)
    await db.flush()
    tag = (
        (
            await db.execute(
                select(InterestTag).where(InterestTag.key == "technology-software")
            )
        )
        .scalars()
        .first()
    )
    db.add(UserInterest(user_id=user.id, interest_tag_id=tag.id, weight=5))
    await db.commit()

    job = await JobService(db).require_job("software-developer")
    result = await score_match(
        db,
        user.id,
        {"interests": [{"tag_key": tag.key, "weight": 5, "source": "self"}]},
        JobService.job_snapshot(job),
    )
    assert 0 <= result.score <= 10
    assert 0 <= result.confidence <= 1
    statuses = {p.status.value for p in result.prerequisites}
    assert statuses <= {"met", "unmet", "unknown"}


async def test_relation_suggester_valid_codes(db, client, auth_headers, seeded_catalog):
    from app.services.job_service import JobService

    service = JobService(db)
    jobs, _ = await service.list_jobs(family_key="technology", page_size=5)
    snapshots = [service.job_snapshot(j) for j in jobs]
    suggestions = await suggest_relations(db, None, snapshots, max_suggestions=5)
    codes = {j["code"] for j in snapshots}
    for s in suggestions:
        assert s.from_code in codes and s.to_code in codes


async def test_university_parser_extracts_structure(db, client, auth_headers):
    text = (
        "UNIVERSITY OF THE MOCK TEXT\n"
        "School of Computing — baseline 2024: 81.5 points, top 98, quota 120\n"
        "baseline 2025: 84 points\n"
    )
    extraction = await parse_universities(db, None, text)
    assert extraction.universities
    uni = extraction.universities[0]
    assert uni.departments
    assert uni.departments[0].admissions
    assert uni.departments[0].admissions[0].baseline_score is not None


async def test_ai_generations_audited(db, client, auth_headers, seeded_catalog):
    from app.core.security import hash_password
    from app.models.user_model import Profile, User
    from app.services.job_service import JobService

    user = User(email="audit@example.com", password_hash=hash_password("password123"))
    db.add(user)
    await db.flush()
    profile = Profile(user_id=user.id)
    db.add(profile)
    await db.commit()

    job = await JobService(db).require_job("nurse")
    await score_match(db, user.id, {}, JobService.job_snapshot(job))
    rows = (
        (
            await db.execute(
                select(AIGeneration).where(
                    AIGeneration.task_type == AITaskType.MATCH_SCORE.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows
    assert rows[0].status == "ok"
    assert rows[0].output is not None


async def test_mock_generic_fallback_schema(db, client, auth_headers):
    result = await ainvoke_structured(
        db, AITaskType.ASSIST, ChatReply, system="s", user="CONTEXT_JSON: {}"
    )
    assert isinstance(result, ChatReply)
    assert result.answer


async def test_structured_error_recorded(db, client, auth_headers, monkeypatch):
    from app.ai import provider as provider_module
    from app.ai.agents.chatbot import _mock_chat_reply

    def bad_builder(schema, user):
        return {"this_is": "not the right shape at all"}

    provider_module.register_mock_fixture(AITaskType.CHAT, bad_builder)
    try:
        await ainvoke_structured(db, AITaskType.CHAT, ChatReply, system="s", user="x")
        assert False, "expected StructuredAIError"
    except StructuredAIError:
        pass
    finally:
        provider_module.register_mock_fixture(AITaskType.CHAT, _mock_chat_reply)
    rows = (
        (await db.execute(select(AIGeneration).where(AIGeneration.status == "error")))
        .scalars()
        .all()
    )
    assert rows
