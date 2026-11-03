"""The catalog join (plan 185): ``decide_catalog`` evaluates the
deterministic weighted skill overlap and records the join trace in
``posting_facts["mapping_signals"]``.

The semantic rescue that used to run beside it lived on the retired
``ai_embeddings`` store (plan 50 P1d); the long-text job↔posting matcher
replaces it on the family vector store in plan 50 P2. Until then the semantic
block of the trace stays empty and the overlap decides alone — semantic is
never a gate.
"""

from sqlalchemy import func, select

from app.extensions.sdk import RawPosting
from app.models.ai_model import AIGeneration
from app.models.job_model import Job, JobFamily, JobSkill
from app.models.posting_model import JobPosting, PostingChange, PostingSkill
from app.models.taxonomy_model import Skill
from app.services.postings.postings_service import (
    AUTO_MAP_THRESHOLD,
    decide_catalog,
    upsert_posting,
)
from app.services.postings.semantic_rescue import SEMANTIC_MAP_THRESHOLD


async def _skill(db, key: str) -> Skill:
    row = Skill(key=key, label=key.upper(), category="test")
    db.add(row)
    await db.flush()
    return row


async def _job(
    db,
    code: str,
    family: JobFamily,
    links: list[tuple[Skill, int, str]],
    status: str = "published",
) -> Job:
    job = Job(
        code=code,
        title=code.replace("-", " ").title(),
        family_id=family.id,
        status=status,
    )
    db.add(job)
    await db.flush()
    for skill, level, importance in links:
        db.add(
            JobSkill(
                job_id=job.id,
                skill_id=skill.id,
                required_level=level,
                importance=importance,
            )
        )
    await db.flush()
    return job


async def _weak_job(db, family: JobFamily, sql: Skill, **extra) -> Job:
    """One weak hit: the posting's sql link carries almost no weight
    against two heavy level-10 links — overlap ≈ 0.05 < AUTO_MAP_THRESHOLD."""
    filler_a = await _skill(db, "filler-a")
    filler_b = await _skill(db, "filler-b")
    return await _job(
        db,
        "weak-overlap-role",
        family,
        [(sql, 1, "core"), (filler_a, 10, "core"), (filler_b, 10, "core")],
        **extra,
    )


async def _make_posting(
    db, source, external_id: str, skills: list[str], description: str = ""
) -> JobPosting:
    posting = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id=external_id,
            title=f"Role {external_id}",
            url=f"https://syn.example/{external_id}",
            skills_raw=skills,
            raw={"description": description} if description else {},
        ),
    )
    await db.flush()
    return posting


async def test_keyword_strong_maps_exactly_as_today(db, source):
    """Overlap 1.0 ≥ AUTO_MAP_THRESHOLD → SKILL_OVERLAP, untouched fields
    (the semantic signal never runs) + the join trace in posting_facts."""
    sql = await _skill(db, "sql")
    python = await _skill(db, "python")
    family = JobFamily(key="join-family", label="Join", path="join-family")
    db.add(family)
    await db.flush()
    job = await _job(db, "strong-role", family, [(sql, 7, "core"), (python, 5, "core")])

    posting = await _make_posting(db, source, "join-strong", ["sql", "python"])

    assert posting.status == "mapped"
    assert posting.mapping_method == "skill_overlap"
    assert posting.catalog_job_id == job.id
    assert posting.mapping_confidence == 1.0
    assert "2 skills intersect" in posting.mapping_reason
    signals = posting.posting_facts["mapping_signals"]
    assert signals["overlap"]["score"] == 1.0
    assert signals["semantic"]["top"] is None, "the rescue never runs when overlap clears"

    rows = (
        (
            await db.execute(
                select(PostingChange).where(
                    PostingChange.posting_id == posting.id,
                    PostingChange.actor_kind == "retag",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2, "the skill rewrite and the decision journal separately"
    [decision] = [row for row in rows if "mapping_method" in (row.diff or {})]
    assert decision.operation["auto_map_threshold"] == AUTO_MAP_THRESHOLD
    assert decision.diff["mapping_method"]["to"] == "skill_overlap"
    [rewrite] = [row for row in rows if "mapping_method" not in (row.diff or {})]
    assert "skills" in (rewrite.diff or {}), "the rewrite row carries the skill set-diff"


async def test_weak_overlap_stays_new_with_the_trace(db, source):
    sql = await _skill(db, "sql")
    family = JobFamily(key="join-family3", label="Join3", path="join-family3")
    db.add(family)
    await db.flush()
    await _weak_job(db, family, sql)

    posting = await _make_posting(db, source, "join-weak", ["sql"])

    assert posting.status == "new"
    assert posting.mapping_method is None
    assert posting.catalog_job_id is None
    signals = posting.posting_facts["mapping_signals"]
    assert signals["overlap"]["score"] < AUTO_MAP_THRESHOLD
    assert (
        f"best overlap {signals['overlap']['score']:.2f} below {AUTO_MAP_THRESHOLD} — moderation"
    ) == posting.mapping_reason
    # The rescue ran (overlap missed) and found no indexed job to propose:
    # the trace still carries the space it asked and the pinned threshold.
    semantic = signals["semantic"]
    assert semantic["top"] is None
    assert semantic["threshold"] == SEMANTIC_MAP_THRESHOLD
    assert semantic["candidates"] == []
    assert semantic["space_key"], "the rescue indexed the posting into the space"
    assert semantic["degraded"] is None


async def test_a_cleared_overlap_spends_no_ai(db, source):
    """Overlap ≥ threshold decides bit-identically — the rescue never runs,
    so not even the sanctioned embed is spent."""
    sql = await _skill(db, "sql")
    python = await _skill(db, "python")
    family = JobFamily(key="join-family7", label="Join7", path="join-family7")
    db.add(family)
    await db.flush()
    await _job(db, "joined-role", family, [(sql, 7, "core"), (python, 5, "core")])

    before = int((await db.execute(select(func.count()).select_from(AIGeneration))).scalar_one())
    posting = await _make_posting(db, source, "join-degrade", ["sql", "python"])

    assert posting.mapping_method == "skill_overlap"
    signals = posting.posting_facts["mapping_signals"]
    assert signals["semantic"]["top"] is None
    assert signals["semantic"]["threshold"] is None
    assert signals["semantic"]["candidates"] == []
    after = int((await db.execute(select(func.count()).select_from(AIGeneration))).scalar_one())
    assert after == before, "a cleared overlap spends no AI at all"


async def test_mapping_signals_merge_preserves_other_facts(db, source):
    """``mapping_signals`` merges into posting_facts — apply_extract owns
    other keys in the same dict and must never be clobbered."""
    from sqlalchemy.orm.attributes import flag_modified

    sql = await _skill(db, "sql")
    python = await _skill(db, "python")
    family = JobFamily(key="join-family8", label="Join8", path="join-family8")
    db.add(family)
    await db.flush()
    await _job(db, "strong-role-2", family, [(sql, 7, "core"), (python, 5, "core")])

    posting = await _make_posting(db, source, "join-merge", ["sql", "python"])
    posting.posting_facts = {**(posting.posting_facts or {}), "languages": [{"code": "el"}]}
    flag_modified(posting, "posting_facts")
    await db.flush()

    from app.services.postings.postings_service import map_posting

    await map_posting(db, posting)

    facts = posting.posting_facts
    assert facts["languages"] == [{"code": "el"}]
    assert facts["mapping_signals"]["overlap"]["score"] == 1.0


async def test_manual_mapping_survives_resync(db, source):
    """MANUAL is a human decision — the mapping guard at the upsert
    callers keeps it, whatever the signals say."""
    from app.models.enums import MappingMethod

    sql = await _skill(db, "sql")
    python = await _skill(db, "python")
    family = JobFamily(key="join-family9", label="Join9", path="join-family9")
    db.add(family)
    await db.flush()
    job = await _job(db, "manual-role", family, [(sql, 8, "core"), (python, 6, "core")])

    posting = await _make_posting(db, source, "join-manual", [])
    posting.catalog_job_id = job.id
    posting.mapping_method = MappingMethod.MANUAL.value
    posting.mapping_confidence = 1.0
    posting.mapping_reason = "manually mapped by a moderator"
    posting.status = "mapped"
    await db.flush()

    resynced = await upsert_posting(
        db,
        source,
        RawPosting(
            external_id="join-manual",
            title="Role join-manual v2",
            url="https://syn.example/join-manual",
            skills_raw=["sql"],
            raw={},
        ),
    )
    await db.flush()

    assert resynced.id == posting.id
    assert resynced.mapping_method == MappingMethod.MANUAL.value
    assert resynced.catalog_job_id == job.id


async def test_decide_catalog_never_touches_skill_rows(db, source):
    """The seam decides; only map_posting's skill-writing path rewrites
    PostingSkill rows — levels/priority set by hand survive a re-decision."""
    sql = await _skill(db, "sql")
    family = JobFamily(key="join-family10", label="Join10", path="join-family10")
    db.add(family)
    await db.flush()
    await _job(db, "rows-role", family, [(sql, 7, "core")])

    posting = await _make_posting(db, source, "join-rows", ["sql"])
    assert posting.mapping_method == "skill_overlap"
    row = (
        (await db.execute(select(PostingSkill).where(PostingSkill.posting_id == posting.id)))
        .scalars()
        .first()
    )
    row.required_level = 9
    row.priority = "must_have"
    await db.flush()

    await decide_catalog(db, posting, {sql.id})

    assert row.required_level == 9
    assert row.priority == "must_have"


# ------------------------------------------------- the post-extract join


async def _extract_world(db):
    """Skills + a weak job for the extract tests: the posting resolves only
    sql; the job's sql link carries almost no weight against two heavy
    level-10 links — overlap ≈ 0.05 < AUTO_MAP_THRESHOLD at ingest."""
    from sqlalchemy import select as sa_select

    for key in ("sql", "programming", "problem-solving"):
        existing = (await db.execute(sa_select(Skill).where(Skill.key == key))).scalars().first()
        if existing is None:
            db.add(Skill(key=key, label=key.upper(), category="test"))
    family = JobFamily(key="join-extract", label="JoinExtract", path="join-extract")
    db.add(family)
    await db.flush()
    sql = (await db.execute(sa_select(Skill).where(Skill.key == "sql"))).scalars().first()
    prog = (await db.execute(sa_select(Skill).where(Skill.key == "programming"))).scalars().first()
    prob = (
        (await db.execute(sa_select(Skill).where(Skill.key == "problem-solving"))).scalars().first()
    )
    return sql, await _job(
        db,
        "extract-weak-role",
        family,
        [(sql, 1, "core"), (prog, 10, "core"), (prob, 10, "core")],
    )


async def test_extract_redecide_keeps_levels_and_strong_maps(
    db, client, auth_headers, kinds, source
):
    """The decisive regression guard: the re-decision NEVER touches
    PostingSkill rows — the extract's required_level/priority survive, and
    a keyword-strong map stays SKILL_OVERLAP (bit-identical)."""
    from app.services.postings.extract_service import extract_posting_now

    sql, job = await _extract_world(db)
    # Make the overlap clear: swap the weak sql link for two strong links
    # matching the posting's full set (sql + programming, both in the text).
    from sqlalchemy import delete as sa_delete

    await db.execute(sa_delete(JobSkill).where(JobSkill.job_id == job.id))
    prog = (await db.execute(select(Skill).where(Skill.key == "programming"))).scalars().first()
    db.add(JobSkill(job_id=job.id, skill_id=sql.id, required_level=8, importance="core"))
    db.add(JobSkill(job_id=job.id, skill_id=prog.id, required_level=7, importance="core"))
    await db.flush()

    posting = await _make_posting(
        db,
        source,
        "join-extract-strong",
        ["sql", "programming"],
        description="We need sql and programming. Nothing else.",
    )
    assert posting.mapping_method == "skill_overlap"

    result = await extract_posting_now(db, posting)
    assert result["extracted"] is True
    assert posting.mapping_method == "skill_overlap"
    assert posting.catalog_job_id == job.id

    rows = (
        (await db.execute(select(PostingSkill).where(PostingSkill.posting_id == posting.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 2, "the re-decision neither added nor removed skill rows"
    assert {row.required_level for row in rows} == {4}, "extract's levels survive intact"
    assert all(row.priority == "must_have" for row in rows)


async def test_extract_redecide_skips_manual(db, client, auth_headers, kinds, source):
    """A human mapping stands: the extract re-decision never runs for a
    MANUAL posting — no new retag decision row, mapping fields untouched."""
    from app.models.enums import MappingMethod
    from app.services.postings.extract_service import extract_posting_now

    _sql, job = await _extract_world(db)
    posting = await _make_posting(
        db,
        source,
        "join-extract-manual",
        ["sql"],
        description="We need sql. Nothing else.",
    )
    posting.catalog_job_id = job.id
    posting.mapping_method = MappingMethod.MANUAL.value
    posting.mapping_confidence = 1.0
    posting.mapping_reason = "manually mapped by a moderator"
    posting.status = "mapped"
    await db.flush()
    before_rows = (
        (
            await db.execute(
                select(PostingChange).where(
                    PostingChange.posting_id == posting.id,
                    PostingChange.actor_kind == "retag",
                )
            )
        )
        .scalars()
        .all()
    )

    await extract_posting_now(db, posting)

    assert posting.mapping_method == MappingMethod.MANUAL.value
    after_rows = (
        (
            await db.execute(
                select(PostingChange).where(
                    PostingChange.posting_id == posting.id,
                    PostingChange.actor_kind == "retag",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(after_rows) == len(before_rows), "the re-decision never ran"


async def test_extract_suppress_cascade_flags_without_demoting(
    db, client, auth_headers, kinds, source, monkeypatch
):
    """Low-confidence extract fields are suppressed (needs_review) and the
    skill rows survive untouched — the re-decision sees the same set and
    never demotes an ingest map (extract's update-in-place semantics: the
    set can only grow, nothing is deleted)."""
    from app.ai.agents.posting_extractor import ExtractSkill, PostingExtract
    from app.services.postings.extract_service import extract_posting_now

    sql, job = await _extract_world(db)
    posting = await _make_posting(
        db,
        source,
        "join-extract-suppress",
        ["sql"],
        description="We need sql and programming. Nothing else.",
    )
    prog = (await db.execute(select(Skill).where(Skill.key == "programming"))).scalars().first()
    assert posting.mapping_method == "skill_overlap", (
        "sql + programming clear the threshold against the weak-weighted job"
    )
    before = {
        row.skill_id: (row.required_level, row.priority)
        for row in (
            (await db.execute(select(PostingSkill).where(PostingSkill.posting_id == posting.id)))
            .scalars()
            .all()
        )
    }

    async def low_confidence_extract(*_args, **_kw):
        extract = PostingExtract(
            skills=[
                ExtractSkill(
                    raw_label="sql",
                    required_level=4,
                    priority="must_have",
                    evidence_quote="we need sql",
                    confidence=0.3,
                )
            ],
            field_confidence={"title_norm": 0.1, "skills": 0.3, "salary": 0.2},
        )
        return extract, {"id": None}

    monkeypatch.setattr("app.ai.agents.posting_extractor.extract_posting", low_confidence_extract)

    result = await extract_posting_now(db, posting)
    assert result["extracted"] is True
    assert posting.needs_review is True, "the suppress cascade flags the posting"
    assert posting.mapping_method == "skill_overlap", "no demote: the rows never shrank"
    assert posting.status == "mapped"
    after = {
        row.skill_id: (row.required_level, row.priority)
        for row in (
            (await db.execute(select(PostingSkill).where(PostingSkill.posting_id == posting.id)))
            .scalars()
            .all()
        )
    }
    assert set(after) == {sql.id, prog.id}, "rows survive suppression untouched"
    assert after == before, "the re-decision left the rows byte-identical"
    assert job.id == posting.catalog_job_id
