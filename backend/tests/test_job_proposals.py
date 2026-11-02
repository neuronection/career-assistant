"""The HITL job proposal lifecycle (plan 185 S4): an unmapped-and-rich
extract proposes into ``posting_facts["job_proposal"]``; an admin applies
it (creates the PUBLISHED catalog job + maps MANUAL + clears the proposal
+ embeds the job — one transaction) or dismisses it (explicit JSON null).
The pending filter is the JSON-TYPE test, never presence."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.extensions.sdk import RawPosting
from app.models.embedding_model import AIEmbedding
from app.models.job_model import Job, JobFamily, JobSkill
from app.models.posting_model import JobPosting, PostingChange
from app.models.taxonomy_model import Skill
from app.services.postings.extract_service import extract_posting_now
from app.services.postings.postings_service import upsert_posting
from tests.conftest import session_headers

RICH_DESCRIPTION = "We need sql, programming and problem-solving. Salary: 40000-60000 EUR per year."
RICH_DESCRIPTION_2 = "We need welding, plumbing and scaffolding. Salary: 30000-50000 EUR per year."


async def _seed_world(db) -> JobFamily:
    from sqlalchemy import select as sa_select

    for key in (
        "sql",
        "programming",
        "problem-solving",
        "welding",
        "plumbing",
        "scaffolding",
    ):
        existing = (await db.execute(sa_select(Skill).where(Skill.key == key))).scalars().first()
        if existing is None:
            db.add(Skill(key=key, label=key.upper(), category="test"))
    family = JobFamily(key="proposal-family", label="Proposals", path="proposal-family")
    db.add(family)
    await db.commit()
    return family


async def _rich_unmapped_posting(
    db,
    source,
    external_id="proposal-1",
    description: str = RICH_DESCRIPTION,
    skills_raw: list[str] | None = None,
) -> JobPosting:
    """An extract-rich posting the catalog cannot answer: no jobs link the
    skills, so the join ends unmapped and the extract proposes."""
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id=external_id,
            title="Observability Engineer",
            url=f"https://syn.example/{external_id}",
            skills_raw=skills_raw or ["sql"],
            raw={"description": description},
        ),
    )
    await db.commit()
    result = await extract_posting_now(db, posting)
    assert result["extracted"] is True
    await db.refresh(posting)
    return posting


def _proposal_of(posting: JobPosting) -> dict:
    value = (posting.posting_facts or {}).get("job_proposal")
    assert isinstance(value, dict), "a live proposal is stored"
    return value


async def test_rich_unmapped_extract_stores_the_proposal(db, client, auth_headers, kinds, source):
    family = await _seed_world(db)
    assert family.key
    posting = await _rich_unmapped_posting(db, source)

    proposal = _proposal_of(posting)
    assert proposal["title_norm"] == "Observability Engineer"
    assert len(proposal["skills"]) >= 3
    assert {s["skill_key"] for s in proposal["skills"]} == {
        "sql",
        "programming",
        "problem-solving",
    }
    assert proposal["extract_version"] == 4
    assert proposal["proposed_at"]
    assert len(proposal["short_description"]) <= 500
    stored_rows = (
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
    assert any((row.operation or {}).get("job_proposal") == "stored" for row in stored_rows), (
        "the writer journals its mutation in the extract transaction"
    )


def test_generic_archetype_title_strips_seniority_prefixes():
    """The catalog job is an ARCHETYPE: seniority is a posting-level fact,
    so the proposed default title is level-generic ("Senior Data Engineer"
    proposes "Data Engineer"); the posting keeps its own title/seniority."""
    from app.services.postings.job_proposal_service import generic_archetype_title

    assert generic_archetype_title("Senior Data Engineer") == "Data Engineer"
    assert generic_archetype_title("Sr. Data Engineer") == "Data Engineer"
    assert generic_archetype_title("Lead Platform Engineer") == "Platform Engineer"
    assert generic_archetype_title("JUNIOR Analyst") == "Analyst"
    assert generic_archetype_title("Data Engineer") == "Data Engineer"
    assert generic_archetype_title("Mid-Level Data Engineer") == "Mid-Level Data Engineer", (
        "hyphenated compounds are one token — not a qualifier"
    )
    assert generic_archetype_title("Principal") == "Principal", "the remainder must stay meaningful"


async def test_senior_posting_proposes_the_generic_title(db, client, auth_headers, kinds, source):
    await _seed_world(db)
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="proposal-senior",
            title="Senior Data Engineer",
            url="https://syn.example/proposal-senior",
            skills_raw=["sql"],
            raw={"description": RICH_DESCRIPTION},
        ),
    )
    await db.commit()
    await extract_posting_now(db, posting)
    await db.refresh(posting)

    proposal = _proposal_of(posting)
    assert proposal["title_norm"] == "Data Engineer", "level-generic archetype title"
    assert proposal["posting_title"] == "Senior Data Engineer", "the posting keeps its own"
    assert proposal["seniority"] == (posting.extract or {}).get("seniority"), (
        "seniority passes through as a posting-level attribute"
    )


def test_proposal_surface_hygiene():
    """The standardized proposal surface: catalog summary preferred,
    residual section labels stripped, truncation at a sentence end."""
    from app.services.postings.job_proposal_service import (
        _sentence_cap,
        _strip_label_prefixes,
        generic_archetype_title,
    )

    assert _strip_label_prefixes(
        "Job Title: PR & Communication Specialist: Job Location: Dusseldorf"
    ) == ("PR & Communication Specialist: Job Location: Dusseldorf")
    assert (
        _strip_label_prefixes("Job Description: - Handle claims. - Assess liability.")
        == "- Handle claims. - Assess liability."
    )
    assert (
        generic_archetype_title(_strip_label_prefixes("Job Title: Senior Data Engineer"))
        == "Data Engineer"
    ), "label chrome strips before the seniority strip"

    noisy = (
        "Job Description: - Διαχείριση αιεκιστικών μηχανημάτων. Ενεπίωφρονας "
        "ετώσεων με τις διαδικασία. "
        "Second sentence ends here. "
        + ("Filler sentence that pads the text well past the cap. " * 12)
        + "Trailing sentence that would be cut mid-way otherwise"
    )
    assert _strip_label_prefixes(noisy).startswith("- Διαχείριση")
    normalized = " ".join(_strip_label_prefixes(noisy).split())
    capped = _sentence_cap(normalized)
    assert len(capped) <= 500
    assert capped.endswith("cap."), "the cap lands on a sentence end, never mid-word"
    assert normalized.startswith(capped), "the cap is a prefix cut, at a sentence end"


async def test_catalog_summary_preferred_and_standardizes_the_surface(
    db, client, auth_headers, kinds, source, monkeypatch
):
    """When the extract carries the canonical-language summary, the
    proposal shows THAT — not the raw board text."""
    from app.ai.agents.posting_extractor import ExtractSkill, PostingExtract
    from app.services.postings.extract_service import extract_posting_now

    await _seed_world(db)
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="proposal-summary",
            title="Τεχνολόγος Ακτινολόγος",
            url="https://syn.example/proposal-summary",
            skills_raw=["sql"],
            raw={"description": RICH_DESCRIPTION},
        ),
    )
    await db.commit()

    async def scripted_extract(*_args, **_kw):
        extract = PostingExtract(
            title_norm="Τεχνολόγος Ακτινολόγος",
            description_clean="Job Description: - Χειρισμός αικιστικών μηχανημάτων.",
            catalog_summary=(
                "Radiographer for the Diavgmatiko Centre of Affidea Alimos. "
                "Handles radiological machines and patient positioning. Full time."
            ),
            skills=[
                ExtractSkill(
                    skill_key="sql",
                    required_level=4,
                    priority="must_have",
                    evidence_quote="we need sql",
                    confidence=0.9,
                ),
                ExtractSkill(
                    skill_key="programming",
                    required_level=4,
                    priority="must_have",
                    evidence_quote="and programming",
                    confidence=0.9,
                ),
                ExtractSkill(
                    skill_key="problem-solving",
                    required_level=4,
                    priority="must_have",
                    evidence_quote="and problem-solving",
                    confidence=0.9,
                ),
            ],
        )
        return extract, {"id": None}

    monkeypatch.setattr("app.ai.agents.posting_extractor.extract_posting", scripted_extract)
    await extract_posting_now(db, posting)
    await db.refresh(posting)

    proposal = _proposal_of(posting)
    assert proposal["title_norm"] == "Τεχνολόγος Ακτινολόγος", (
        "the extract's title passes through as-is here (no seniority to strip)"
    )
    assert proposal["short_description"].startswith("Radiographer for the Diavgmatiko"), (
        "the canonical-language summary wins over the raw board text"
    )
    assert "Job Description:" not in proposal["short_description"]


async def test_mapped_or_poor_extracts_never_propose(db, client, auth_headers, kinds, source):
    sql, programming = None, None
    family = await _seed_world(db)
    sql_row = (await db.execute(select(Skill).where(Skill.key == "sql"))).scalars().first()
    programming_row = (
        (await db.execute(select(Skill).where(Skill.key == "programming"))).scalars().first()
    )
    sql, programming = sql_row, programming_row
    # A job linking the full set → the ingest map clears → never unmapped.
    db.add(
        Job(
            code="proposal-covered",
            title="Covered Role",
            family_id=family.id,
            status="published",
        )
    )
    await db.flush()
    job = (await db.execute(select(Job).where(Job.code == "proposal-covered"))).scalars().first()
    db.add(JobSkill(job_id=job.id, skill_id=sql.id, required_level=8, importance="core"))
    db.add(JobSkill(job_id=job.id, skill_id=programming.id, required_level=8, importance="core"))
    await db.commit()

    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="proposal-covered-posting",
            title="Covered Engineer",
            url="https://syn.example/proposal-covered-posting",
            skills_raw=["sql", "programming"],
            raw={"description": "We need sql and programming."},
        ),
    )
    await db.commit()
    await extract_posting_now(db, posting)
    await db.refresh(posting)

    assert posting.mapping_method is not None
    assert not isinstance((posting.posting_facts or {}).get("job_proposal"), dict), (
        "a mapped posting never proposes"
    )


async def test_proposal_lifecycle_queue_apply_dismiss(db, client, auth_headers, kinds, source):
    from sqlalchemy.orm import joinedload

    from app.models.enums import JobSkillImportance
    from app.services.postings.job_proposal_service import PRIORITY_TO_IMPORTANCE

    family = await _seed_world(db)
    posting = await _rich_unmapped_posting(db, source)
    proposal = _proposal_of(posting)

    queue = (await client.get("/api/v1/admin/postings/job-proposals", headers=auth_headers)).json()
    assert len(queue) == 1
    assert queue[0]["id"] == str(posting.id)
    assert queue[0]["proposal"]["title_norm"] == "Observability Engineer"
    assert "mapping_signals" in queue[0]
    assert queue[0]["proposal"] == proposal

    applied = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
        json={"family_key": "proposal-family"},
        headers=auth_headers,
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["mapping_method"] == "manual"
    assert body["status"] == "mapped"

    await db.refresh(posting)
    facts = posting.posting_facts or {}
    assert facts["job_proposal"] is None, "an applied proposal clears explicitly"
    assert facts["job_proposal_applied_at"]
    assert posting.status == "mapped"
    job = (await db.execute(select(Job).where(Job.code == body["job_code"]))).scalars().one()
    assert job.status == "published"
    assert job.source == "ai"
    assert job.family_id == family.id
    assert job.short_description, "the extract's description seeds the catalog page"
    links = (
        (
            await db.execute(
                select(JobSkill)
                .options(joinedload(JobSkill.skill))
                .where(JobSkill.job_id == job.id)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    by_key = {link.skill.key: link for link in links}
    assert by_key, "the resolved proposal skills become job skill links"
    for link in links:
        proposal_skill = next(s for s in proposal["skills"] if s["skill_key"] == link.skill.key)
        assert (
            link.importance
            == PRIORITY_TO_IMPORTANCE.get(
                proposal_skill["priority"], JobSkillImportance.IMPORTANT
            ).value
        ), "the priority→importance map is pinned per link"
    assert {link.required_level for link in links} == {4}

    # The queue is empty afterwards; the vectors exist for the new job.
    queue_after = (
        await client.get("/api/v1/admin/postings/job-proposals", headers=auth_headers)
    ).json()
    assert queue_after == []
    vectors = (
        (
            await db.execute(
                select(AIEmbedding).where(
                    AIEmbedding.entity_kind == "job", AIEmbedding.entity_id == job.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(vectors) == 1, "the applied job embeds in the same transaction"

    # A second rich posting dismisses instead — and lands the audit trail.
    posting2 = await _rich_unmapped_posting(
        db,
        source,
        external_id="proposal-2",
        description=RICH_DESCRIPTION_2,
        skills_raw=["welding"],
    )
    dismissed = await client.post(
        f"/api/v1/admin/postings/{posting2.id}/job-proposal/dismiss",
        headers=auth_headers,
    )
    assert dismissed.status_code == 200
    await db.refresh(posting2)
    facts2 = posting2.posting_facts or {}
    assert facts2["job_proposal"] is None
    assert facts2["job_proposal_rejected_at"]
    pending_after = (
        await client.get("/api/v1/admin/postings/job-proposals", headers=auth_headers)
    ).json()
    assert pending_after == [], "a dismissed proposal is not pending"

    [journal] = (
        (
            await db.execute(
                select(PostingChange).where(
                    PostingChange.posting_id == posting2.id,
                    PostingChange.actor_kind == "manual",
                )
            )
        )
        .scalars()
        .all()
    )
    assert journal.operation["job_proposal"] == "dismissed"


async def test_queue_suggests_the_skill_affinity_family(db, client, auth_headers, kinds, source):
    """The apply dialog's default: importance-weighted overlap between the
    posting's resolved skills and each family's published jobs — a
    suggestion, never an autonomous choice; uncovered postings start the
    picker empty. Each covering job stays individually BELOW the auto-map
    threshold (diluted with heavy filler links) so the posting stays
    unmapped — the family-level aggregate is what suggests."""
    family = await _seed_world(db)
    other = JobFamily(key="other-family", label="Other", path="other-family")
    db.add(other)
    await db.flush()
    sql_row = (await db.execute(select(Skill).where(Skill.key == "sql"))).scalars().first()
    programming = (
        (await db.execute(select(Skill).where(Skill.key == "programming"))).scalars().first()
    )
    problem = (
        (await db.execute(select(Skill).where(Skill.key == "problem-solving"))).scalars().first()
    )
    filler = Skill(key="suggest-filler", label="Suggest Filler", category="test")
    db.add(filler)
    await db.flush()
    for covered_skill in (sql_row, programming, problem):
        diluted = Job(
            code=f"suggestion-diluted-{covered_skill.key}",
            title="Diluted",
            family_id=family.id,
            status="published",
        )
        db.add(diluted)
        await db.flush()
        db.add(
            JobSkill(
                job_id=diluted.id,
                skill_id=covered_skill.id,
                required_level=1,
                importance="core",
            )
        )
        db.add(
            JobSkill(
                job_id=diluted.id,
                skill_id=filler.id,
                required_level=10,
                importance="core",
            )
        )
    unrelated = Job(code="suggestion-other", title="Other", family_id=other.id, status="published")
    db.add(unrelated)
    await db.flush()
    db.add(JobSkill(job_id=unrelated.id, skill_id=filler.id, required_level=10, importance="core"))
    await db.commit()

    posting = await _rich_unmapped_posting(db, source, external_id="suggest-1")
    assert posting.mapping_method is None, "each diluted job stays below the threshold"
    uncovered = await _rich_unmapped_posting(
        db,
        source,
        external_id="suggest-2",
        description="We need welding, plumbing and scaffolding.",
        skills_raw=["welding"],
    )

    queue = (await client.get("/api/v1/admin/postings/job-proposals", headers=auth_headers)).json()
    by_id = {row["id"]: row for row in queue}
    assert by_id[str(posting.id)]["suggested_family_key"] == "proposal-family"
    assert by_id[str(uncovered.id)]["suggested_family_key"] is None


async def test_generic_only_overlap_never_guesses(db, client, auth_headers, kinds, source):
    """A posting whose only shared skills are generic (linked by several
    families, none exclusive) gets NO suggestion — the picker starts empty
    rather than guessing an alphabetically-first family."""
    family = await _seed_world(db)
    other = JobFamily(key="aaa-generic", label="AAA Generic", path="aaa-generic")
    db.add(other)
    await db.flush()
    generic_skills = []
    for index in range(3):
        skill = Skill(key=f"generic-skill-{index}", label=f"Generic {index}", category="test")
        db.add(skill)
        generic_skills.append(skill)
    filler = Skill(key="generic-filler", label="Generic Filler", category="test")
    db.add(filler)
    await db.flush()
    for family_id in (family.id, other.id):
        generic_job = Job(
            code=f"generic-{family_id.hex[:6]}",
            title="Generic",
            family_id=family_id,
            status="published",
        )
        db.add(generic_job)
        await db.flush()
        for skill in generic_skills:
            db.add(
                JobSkill(
                    job_id=generic_job.id,
                    skill_id=skill.id,
                    required_level=1,
                    importance="core",
                )
            )
        # Heavy filler keeps each job individually below the auto-map
        # threshold, so the posting stays unmapped and proposes.
        db.add(
            JobSkill(
                job_id=generic_job.id,
                skill_id=filler.id,
                required_level=10,
                importance="core",
            )
        )
    await db.commit()

    posting = await _rich_unmapped_posting(
        db,
        source,
        external_id="generic-only",
        description="We need generic-skill-0, generic-skill-1 and generic-skill-2.",
        skills_raw=["generic-skill-0"],
    )
    queue = (await client.get("/api/v1/admin/postings/job-proposals", headers=auth_headers)).json()
    row = next(entry for entry in queue if entry["id"] == str(posting.id))
    assert row["suggested_family_key"] is None, "generic-only overlap is not evidence — no guess"


async def test_apply_caps_the_skill_links_at_the_catalog_contract(
    db, client, auth_headers, kinds, source, monkeypatch
):
    """The catalog contract caps a job at 15 skill links (JobCreate); a
    21-resolvable proposal applies cleanly with the best 15 — must-have
    first, never a 500."""
    from app.ai.agents.posting_extractor import ExtractSkill, PostingExtract
    from app.services.postings.extract_service import extract_posting_now

    await _seed_world(db)
    extra = []
    for index in range(18):
        skill = Skill(key=f"cap-skill-{index:02d}", label=f"Cap {index}", category="test")
        db.add(skill)
        extra.append(skill)
    await db.commit()

    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="cap-apply",
            title="Cap Test Engineer",
            url="https://syn.example/cap-apply",
            skills_raw=["sql"],
            raw={"description": RICH_DESCRIPTION},
        ),
    )
    await db.commit()

    async def scripted_extract(*_args, **_kw):
        extract = PostingExtract(
            title_norm="Cap Test Engineer",
            catalog_summary="A role with many skills.",
            skills=[
                ExtractSkill(
                    skill_key="sql",
                    required_level=6,
                    priority="must_have",
                    evidence_quote="we need sql",
                    confidence=0.9,
                ),
                *[
                    ExtractSkill(
                        skill_key=skill.key,
                        required_level=5,
                        priority="must_have" if index < 3 else "nice_to_have",
                        evidence_quote="skills",
                        confidence=0.9,
                    )
                    for index, skill in enumerate(extra)
                ],
            ],
        )
        return extract, {"id": None}

    monkeypatch.setattr("app.ai.agents.posting_extractor.extract_posting", scripted_extract)
    await extract_posting_now(db, posting)
    await db.refresh(posting)
    assert len(_proposal_of(posting)["skills"]) == 19

    applied = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
        json={"family_key": "proposal-family"},
        headers=auth_headers,
    )
    assert applied.status_code == 200, applied.text
    job = (
        (await db.execute(select(Job).where(Job.code == applied.json()["job_code"])))
        .scalars()
        .one()
    )
    links = (
        (
            await db.execute(
                select(JobSkill)
                .options(joinedload(JobSkill.skill))
                .where(JobSkill.job_id == job.id)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    assert len(links) == 15, "the catalog contract's cap, not a 500"
    keys = {link.skill.key for link in links}
    assert "sql" in keys
    assert {"cap-skill-00", "cap-skill-01", "cap-skill-02"} <= keys, (
        "must-have skills win the 15 slots"
    )
    assert {link.importance for link in links if link.skill.key == "sql"} == {"core"}


async def test_apply_dedupes_repeated_skill_keys_never_500s(
    db, client, auth_headers, kinds, source, monkeypatch
):
    """Two extract mentions may carry the SAME skill_key (a model repeats a
    key; under plan-153 v5 two labels resolving to one key is designed
    behavior) — apply keeps the best entry per key, never trips
    uq_job_skills_job_skill with a 500."""
    from app.ai.agents.posting_extractor import ExtractSkill, PostingExtract
    from app.services.postings.extract_service import extract_posting_now

    await _seed_world(db)
    extra = []
    for index in range(2):
        skill = Skill(key=f"dup-skill-{index:02d}", label=f"Dup {index}", category="test")
        db.add(skill)
        extra.append(skill)
    await db.commit()

    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="dup-apply",
            title="Dup Test Engineer",
            url="https://syn.example/dup-apply",
            skills_raw=["sql"],
            raw={"description": RICH_DESCRIPTION},
        ),
    )
    await db.commit()

    async def scripted_extract(*_args, **_kw):
        extract = PostingExtract(
            title_norm="Dup Test Engineer",
            catalog_summary="A role with repeated mentions of one skill.",
            skills=[
                ExtractSkill(
                    skill_key="sql",
                    required_level=8,
                    priority="must_have",
                    evidence_quote="deep sql expertise",
                    confidence=0.9,
                ),
                ExtractSkill(
                    skill_key="sql",
                    required_level=4,
                    priority="nice_to_have",
                    evidence_quote="some sql",
                    confidence=0.7,
                ),
                *[
                    ExtractSkill(
                        skill_key=skill.key,
                        required_level=5,
                        priority="must_have",
                        evidence_quote="skills",
                        confidence=0.9,
                    )
                    for skill in extra
                ],
            ],
        )
        return extract, {"id": None}

    monkeypatch.setattr("app.ai.agents.posting_extractor.extract_posting", scripted_extract)
    await extract_posting_now(db, posting)
    await db.refresh(posting)
    assert len(_proposal_of(posting)["skills"]) == 4

    applied = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
        json={"family_key": "proposal-family"},
        headers=auth_headers,
    )
    assert applied.status_code == 200, applied.text
    job = (
        (await db.execute(select(Job).where(Job.code == applied.json()["job_code"])))
        .scalars()
        .one()
    )
    links = (
        (
            await db.execute(
                select(JobSkill)
                .options(joinedload(JobSkill.skill))
                .where(JobSkill.job_id == job.id)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    assert len(links) == 3, "one link per distinct skill key, not a 500"
    sql_links = [link for link in links if link.skill.key == "sql"]
    assert len(sql_links) == 1
    assert sql_links[0].importance == "core" and sql_links[0].required_level == 8


async def test_apply_slug_dedupes_and_overrides(db, client, auth_headers, kinds, source):
    family = await _seed_world(db)
    db.add(
        Job(
            code="observability-engineer",
            title="Existing Role",
            family_id=family.id,
            status="published",
        )
    )
    await db.commit()

    posting = await _rich_unmapped_posting(db, source, external_id="proposal-slug")
    applied = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
        json={
            "family_key": "proposal-family",
            "title": "Observability Engineer II",
            "short_description": "Hand-tuned page.",
        },
        headers=auth_headers,
    )
    assert applied.status_code == 200, applied.text
    job = (
        (await db.execute(select(Job).where(Job.code == applied.json()["job_code"])))
        .scalars()
        .one()
    )
    assert job.code.startswith("observability-engineer"), "slugified from the title"
    assert job.code != "observability-engineer", "deduped against the taken code"
    assert job.title == "Observability Engineer II"
    assert job.short_description == "Hand-tuned page."


async def test_apply_failure_leaves_no_job_row(
    db, client, auth_headers, kinds, source, monkeypatch
):
    """The commit-semantics regression: a mid-apply failure (the job embed
    raises) leaves NO job row and the proposal pending — one transaction."""
    await _seed_world(db)
    posting = await _rich_unmapped_posting(db, source, external_id="proposal-fail")

    async def broken_embed_texts(_db, texts, **_kw):
        raise RuntimeError("embeddings provider down mid-apply")

    monkeypatch.setattr("app.ai.gateway.embed_texts", broken_embed_texts)

    with pytest.raises(RuntimeError):
        await client.post(
            f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
            json={"family_key": "proposal-family"},
            headers=auth_headers,
        )

    jobs = (await db.execute(select(Job))).scalars().all()
    assert jobs == [], "the flushed job never committed"
    await db.refresh(posting)
    assert isinstance((posting.posting_facts or {}).get("job_proposal"), dict), (
        "the proposal stays pending"
    )
    assert posting.mapping_method is None


async def test_apply_requires_a_known_family(db, client, auth_headers, kinds, source):
    await _seed_world(db)
    posting = await _rich_unmapped_posting(db, source, external_id="proposal-family-miss")
    applied = await client.post(
        f"/api/v1/admin/postings/{posting.id}/job-proposal/apply",
        json={"family_key": "no-such-family"},
        headers=auth_headers,
    )
    assert applied.status_code == 404


async def test_job_proposals_require_admin(client, auth_headers, kinds, db, source):
    await _seed_world(db)
    _ = auth_headers  # the fixture admin exists first — a fresh register is not auto-admin
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "proposer@example.com", "password": "password123"},
    )
    headers = session_headers(register)

    queue = await client.get("/api/v1/admin/postings/job-proposals", headers=headers)
    assert queue.status_code == 403
    applied = await client.post(
        "/api/v1/admin/postings/00000000-0000-0000-0000-000000000000/job-proposal/dismiss",
        headers=headers,
    )
    assert applied.status_code == 403


async def test_pending_predicate_lies_not_on_presence(db, client, auth_headers, kinds, source):
    """The JSON-TYPE test: an explicit null under the key is NEVER pending
    (the dismissed proposal above exercises the same path — here pinned at
    the predicate level against the live dialect)."""
    from app.services.postings.job_proposal_service import (
        JobProposalService,
        pending_predicate,
    )

    assert "jsonb_typeof" in str(pending_predicate("postgresql"))
    assert "json_type" in str(pending_predicate("sqlite"))

    await _seed_world(db)
    posting = await _rich_unmapped_posting(db, source, external_id="proposal-pred")
    service = JobProposalService(db)
    assert len(await service.pending()) == 1
    stub_user = type("U", (), {"id": "00000000-0000-0000-0000-000000000000"})
    await service.dismiss(posting, user=stub_user)
    assert await service.pending() == [], "explicit null ≠ pending"
