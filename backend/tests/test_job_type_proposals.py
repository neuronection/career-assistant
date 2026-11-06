"""Plan 202 S2 — catalog-first candidate assembly and the proposal task."""

import json
import uuid

from sqlalchemy import select

from app.ai.agents.job_type_proposer import (
    JOB_TYPE_POLICY,
    JobTypeDecision,
    JobTypeProposalOut,
    build_user_prompt,
    propose_job_type,
)
from app.core.errors import AINotConfiguredError
from app.extensions.sdk import RawPosting
from app.models.ai_model import AIGeneration
from app.models.job_model import Job, JobFamily
from app.models.posting_model import PostingChange
from app.models.taxonomy_model import Skill
from app.services.postings.job_proposal_service import store_job_type_proposal
from app.services.postings.job_type_candidates import (
    JOB_TYPE_CANDIDATE_CAP,
    JobTypeCandidate,
    job_type_candidates,
)
from app.services.postings.postings_service import upsert_posting

RICH = "We need sql, programming and problem-solving. Salary: 40000-60000 EUR per year."


async def _world(db) -> JobFamily:
    for key in ("sql", "programming", "problem-solving"):
        db.add(Skill(key=key, label=key.upper(), category="test"))
    family = JobFamily(key="proposal-family", label="Proposals", path="proposal-family")
    db.add(family)
    await db.commit()
    return family


async def _job(db, family, code: str, title: str) -> Job:
    job = Job(code=code, title=title, family_id=family.id, status="published")
    db.add(job)
    await db.commit()
    return job


async def _extracted_posting(db, source, *, title="Observability Engineer"):
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id=f"cand-{uuid.uuid4().hex[:8]}",
            title=title,
            url="https://syn.example/cand",
            skills_raw=["sql", "programming", "problem-solving"],
            raw={"description": RICH},
        ),
    )
    await db.commit()
    from app.services.postings.extract_service import extract_posting_now

    await extract_posting_now(db, posting)
    await db.refresh(posting)
    facts = {**(posting.posting_facts or {})}
    facts["job_proposal"] = None
    posting.posting_facts = facts
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(posting, "posting_facts")
    await db.commit()
    return posting


def _candidate(code: str, title: str) -> JobTypeCandidate:
    return JobTypeCandidate(
        code=code,
        title=title,
        family_key="tech",
        family_label="Technology",
        short_description="x" * 1000,
        score=0.5,
        source="skill",
    )


async def test_exact_match_proposes_map_existing_with_zero_provider_calls(
    db, client, auth_headers, kinds, source, monkeypatch
):
    family = await _world(db)
    await _job(db, family, "observability-engineer", "Observability Engineer")
    posting = await _extracted_posting(db, source)

    calls = {"n": 0}

    async def blow_up(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("an exact catalog match must not call a provider")

    monkeypatch.setattr("app.ai.agents.job_type_proposer.ainvoke_structured", blow_up)
    result = await store_job_type_proposal(db, posting)
    await db.commit()
    await db.refresh(posting)

    assert result["status"] == "stored" and result["action"] == "map_existing"
    assert calls["n"] == 0
    proposal = (posting.posting_facts or {})["job_proposal"]
    assert proposal["proposal_version"] == 2
    assert proposal["existing_job_code"] == "observability-engineer"
    assert proposal["job_type"] == "Observability Engineer"
    assert proposal["posting_title"] == "Observability Engineer"


async def test_candidate_order_cap_and_containment_floor(db, client, auth_headers, kinds, source):
    family = await _world(db)
    exact = await _job(db, family, "data-engineer", "Data Engineer")
    containment = await _job(db, family, "software-engineer", "Software Engineer")
    for index in range(JOB_TYPE_CANDIDATE_CAP + 4):
        await _job(db, family, f"filler-{index}", f"Filler Role {index}")

    exact_posting = await _extracted_posting(db, source, title="Data Engineer")
    candidates, match = await job_type_candidates(db, exact_posting, exact_posting.extract)
    assert match is not None and match.code == "data-engineer"
    assert exact.code in {candidate.code for candidate in candidates}
    assert len(candidates) <= JOB_TYPE_CANDIDATE_CAP
    assert candidates[0].source == "exact"

    senior_posting = await _extracted_posting(db, source, title="Senior Data Engineer")
    senior_candidates, no_exact = await job_type_candidates(
        db, senior_posting, senior_posting.extract
    )
    assert no_exact is None
    assert any(
        candidate.code == exact.code and candidate.source == "containment"
        for candidate in senior_candidates
    )
    assert not any(
        candidate.code == containment.code and candidate.source == "containment"
        for candidate in senior_candidates
    ), "a candidate title that is not contained is never a match"


async def test_prompt_is_bounded_and_carries_the_policy():
    prompt = build_user_prompt(
        raw_title="Software Development Engineer III, MuleSoft",
        title_norm="Software Development Engineer, MuleSoft",
        seniority="senior",
        description="d" * 6000,
        skills=[{"skill_key": "programming"}] * 30,
        candidates=[_candidate("software-engineer", "Software Engineer")],
        family_keys={
            "families": [{"key": "tech", "label": "Technology"}],
            "job_types": [{"code": f"j{i}", "title": f"Job {i}"} for i in range(220)],
        },
        language_name="English",
    )
    payload = json.loads(prompt.split("\n\nCONTEXT_JSON: ")[0])
    assert len(payload["description"]) == 4000
    assert len(payload["skills"]) == 20
    assert len(payload["candidates"][0]["short_description"]) == 200
    assert len(payload["published_job_types"]) == 200
    assert "map_existing" in JOB_TYPE_POLICY
    assert "MuleSoft" in JOB_TYPE_POLICY
    assert "Marketing Intern" in JOB_TYPE_POLICY


async def test_unknown_candidate_code_and_family_are_never_trusted(db, monkeypatch):
    posting = type("P", (), {"title": "X", "posting_facts": {}, "id": uuid.uuid4()})()
    extract = {"title_norm": "X", "skills": [{"skill_key": "a"}]}

    async def fake_invoke(*_args, **_kwargs):
        return JobTypeProposalOut(
            action=JobTypeDecision.MAP_EXISTING,
            existing_job_code="not-a-candidate",
            confidence=0.8,
            rationale="hallucinated",
        )

    monkeypatch.setattr("app.ai.agents.job_type_proposer.ainvoke_structured", fake_invoke)
    result = await propose_job_type(
        db,
        posting,
        extract,
        [_candidate("software-engineer", "Software Engineer")],
        {"families": [{"key": "tech", "label": "Technology"}], "job_types": []},
        "English",
    )
    assert result is not None and result.action is JobTypeDecision.NONE


async def test_unconfigured_ai_degrades_to_no_proposal(db, monkeypatch):
    posting = type("P", (), {"title": "X", "posting_facts": {}, "id": uuid.uuid4()})()

    async def unconfigured(*_args, **_kwargs):
        raise AINotConfiguredError("not configured")

    monkeypatch.setattr("app.ai.agents.job_type_proposer.ainvoke_structured", unconfigured)
    result = await propose_job_type(
        db,
        posting,
        {"title_norm": "X", "skills": []},
        [],
        {"families": [], "job_types": []},
        "English",
    )
    assert result is None


async def test_unconfigured_writer_journals_no_ai(
    db, monkeypatch, client, auth_headers, kinds, source
):
    await _world(db)
    posting = await _extracted_posting(db, source, title="Observability Engineer")

    async def unconfigured(*_args, **_kwargs):
        raise AINotConfiguredError("not configured")

    monkeypatch.setattr("app.ai.agents.job_type_proposer.ainvoke_structured", unconfigured)
    result = await store_job_type_proposal(db, posting, run_id=uuid.uuid4())
    await db.commit()
    await db.refresh(posting)

    assert result == {"status": "no_ai", "reason": "unconfigured"}
    assert posting.posting_facts["job_proposal_failed_reason"] == "unconfigured"
    rows = (
        (
            await db.execute(
                select(PostingChange).where(
                    PostingChange.posting_id == posting.id,
                    PostingChange.actor_kind == "extract_llm",
                )
            )
        )
        .scalars()
        .all()
    )
    assert any((row.operation or {}).get("job_proposal") == "failed" for row in rows)


async def test_success_clears_a_previous_failure_marker(
    db, monkeypatch, client, auth_headers, kinds, source
):
    from app.ai.agents.job_type_proposer import JobTypeDecision, JobTypeProposalOut

    await _world(db)
    posting = await _extracted_posting(db, source, title="Observability Engineer")

    async def unconfigured(*_args, **_kwargs):
        raise AINotConfiguredError("not configured")

    monkeypatch.setattr("app.ai.agents.job_type_proposer.ainvoke_structured", unconfigured)
    await store_job_type_proposal(db, posting, run_id=uuid.uuid4())
    await db.commit()
    await db.refresh(posting)
    assert posting.posting_facts["job_proposal_failed_at"]

    async def success(*_args, **_kwargs):
        return (
            JobTypeProposalOut(
                action=JobTypeDecision.CREATE,
                title="Observability Engineer",
                family_key="proposal-family",
                short_description="Keeps systems observable across employers.",
                confidence=0.8,
                rationale="No catalog type covers the occupation.",
            ),
            {"id": None},
        )

    monkeypatch.setattr("app.ai.agents.job_type_proposer.propose_job_type_with_audit", success)
    result = await store_job_type_proposal(db, posting, run_id=uuid.uuid4())
    await db.commit()
    await db.refresh(posting)
    facts = posting.posting_facts or {}
    assert result["status"] == "stored"
    assert "job_proposal_failed_at" not in facts
    assert "job_proposal_failed_reason" not in facts


async def test_proposer_exception_degrades_and_journals(
    db, monkeypatch, client, auth_headers, kinds, source
):
    from app.services.postings.mapping_remap import redecide_and_propose

    await _world(db)
    posting = await _extracted_posting(db, source, title="Observability Engineer")

    async def boom(*_args, **_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.ai.agents.job_type_proposer.propose_job_type_with_audit", boom)
    result = await redecide_and_propose(db, posting, run_id=uuid.uuid4())
    await db.refresh(posting)

    assert result["proposal"] == {"status": "failed"}
    assert posting.mapping_method is None, "the committed mapping decision stands"
    assert posting.posting_facts["job_proposal_failed_reason"] == "RuntimeError"
    rows = (
        (
            await db.execute(
                select(PostingChange).where(
                    PostingChange.posting_id == posting.id,
                    PostingChange.actor_kind == "extract_llm",
                )
            )
        )
        .scalars()
        .all()
    )
    assert any((row.operation or {}).get("job_proposal") == "failed" for row in rows)


async def test_proposer_writes_v2_with_the_audit_ref(db, client, auth_headers, kinds, source):
    await _world(db)
    posting = await _extracted_posting(db, source, title="Observability Engineer")
    run_id = uuid.uuid4()
    result = await store_job_type_proposal(db, posting, run_id=run_id)
    await db.commit()
    await db.refresh(posting)

    assert result["status"] == "stored"
    proposal = (posting.posting_facts or {})["job_proposal"]
    assert proposal["proposal_version"] == 2
    assert proposal["action"] in {"create", "map_existing"}
    assert proposal["short_description"] or proposal["action"] == "map_existing"
    assert proposal["skills"]

    row = (
        await db.execute(
            AIGeneration.__table__.select()
            .where(AIGeneration.task_type == "job_type_proposal")
            .order_by(AIGeneration.created_at.desc())
            .limit(1)
        )
    ).first()
    assert row is not None
    assert row.run_id == run_id


async def test_extract_queues_the_remap_instead_of_proposing(
    db, client, auth_headers, kinds, source
):
    from sqlalchemy import select

    from app.models.background_job_model import BackgroundJob
    from app.models.enums import BackgroundJobType
    from app.services.postings.extract_service import extract_posting_now

    await _world(db)
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="extract-no-proposal",
            title="Observability Engineer",
            url="https://syn.example/extract-no-proposal",
            skills_raw=["sql", "programming", "problem-solving"],
            raw={"description": RICH},
        ),
    )
    await db.commit()
    await extract_posting_now(db, posting)
    await db.refresh(posting)

    assert not isinstance((posting.posting_facts or {}).get("job_proposal"), dict)
    jobs = (
        (
            await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.job_type == BackgroundJobType.POSTING_REMAP.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert any(str(job.payload.get("posting_id")) == str(posting.id) for job in jobs)
    audit = (
        await db.execute(
            AIGeneration.__table__.select().where(AIGeneration.task_type == "job_type_proposal")
        )
    ).first()
    assert audit is None, "the extract path never calls the proposer"


async def test_remap_is_enqueued_with_both_semantic_switches_off(
    db, client, auth_headers, kinds, source
):
    from sqlalchemy import select

    from app.models.background_job_model import BackgroundJob
    from app.models.enums import BackgroundJobType
    from app.services.postings.catalog_settings import (
        SEMANTIC_RERANK_KEY,
        SEMANTIC_RESCUE_KEY,
        set_switch,
    )
    from app.services.postings.extract_service import extract_posting_now

    await _world(db)
    await set_switch(db, SEMANTIC_RESCUE_KEY, False)
    await set_switch(db, SEMANTIC_RERANK_KEY, False)
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="extract-switches-off",
            title="Observability Engineer",
            url="https://syn.example/extract-switches-off",
            skills_raw=["sql", "programming", "problem-solving"],
            raw={"description": RICH},
        ),
    )
    await db.commit()
    await extract_posting_now(db, posting)

    jobs = (
        (
            await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.job_type == BackgroundJobType.POSTING_REMAP.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert any(str(job.payload.get("posting_id")) == str(posting.id) for job in jobs)


async def test_refresh_replaces_a_live_v2_proposal_only_when_asked(
    db, client, auth_headers, kinds, source
):
    await _world(db)
    posting = await _extracted_posting(db, source, title="Observability Engineer")
    first = await store_job_type_proposal(db, posting)
    await db.commit()
    assert first["status"] == "stored"

    skipped = await store_job_type_proposal(db, posting)
    await db.commit()
    assert skipped == {"status": "skipped", "reason": "existing"}

    refreshed = await store_job_type_proposal(db, posting, refresh=True)
    await db.commit()
    await db.refresh(posting)
    assert refreshed["status"] == "stored"
    assert (posting.posting_facts or {})["job_proposal"]["proposal_version"] == 2


async def test_candidate_assembly_reuses_the_semantic_trace(
    db, client, auth_headers, kinds, source
):
    family = await _world(db)
    semantic_job = await _job(db, family, "semantic-role", "Semantic Role")
    posting = await _extracted_posting(db, source, title="Totally Unrelated Title")
    facts = {**(posting.posting_facts or {})}
    facts["mapping_signals"] = {
        "semantic": {"candidates": [{"code": semantic_job.code, "score": 0.81, "shared_skills": 3}]}
    }
    posting.posting_facts = facts
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(posting, "posting_facts")
    await db.commit()

    candidates, exact = await job_type_candidates(db, posting, posting.extract)
    assert exact is None
    assert any(
        candidate.code == semantic_job.code and candidate.source == "semantic"
        for candidate in candidates
    )
