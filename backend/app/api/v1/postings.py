from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import NotFoundError
from app.models.posting_model import JobPosting, JobSource
from app.schemas.posting import (
    AppliedIn,
    ExploreOut,
    PostingDetailOut,
    PostingsOut,
    PostingOut,
    PostingSearchOut,
    SaveIn,
    SeenIn,
)
from app.services.deps import get_current_user
from app.services.explore_service import (
    explore,
    parse_explore_filters,
    similar_postings,
    sources_with_counts,
)
from app.services.postings_service import (
    list_postings,
    mark_seen,
    parse_skill_entries,
    resolve_posting,
    search_postings,
    set_state,
)

router = APIRouter(tags=["postings"])


def _posting_out(
    posting: JobPosting, interaction, fit=None, source_key="", coverage=None
) -> PostingOut:
    from app.schemas.job import JobOut

    catalog_job = None
    if posting.catalog_job is not None:
        catalog_job = JobOut.from_model(posting.catalog_job)
    return PostingOut(
        id=posting.id,
        ref=posting.ref or "",
        source_id=posting.source_id,
        external_id=posting.external_id,
        title=posting.title,
        org=posting.org,
        location=posting.location or {},
        url=posting.url,
        seniority=posting.seniority,
        employment_type=posting.employment_type,
        onsite_policy=posting.onsite_policy,
        salary_currency=posting.salary_currency,
        salary_min=float(posting.salary_min)
        if posting.salary_min is not None
        else None,
        salary_max=float(posting.salary_max)
        if posting.salary_max is not None
        else None,
        salary_period=posting.salary_period,
        posted_at=posting.posted_at,
        expires_at=posting.expires_at,
        status=posting.status,
        catalog_job_id=posting.catalog_job_id,
        mapping_method=posting.mapping_method,
        mapping_confidence=posting.mapping_confidence,
        mapping_reason=posting.mapping_reason,
        fit=fit,
        seen=interaction is not None and interaction.seen_at is not None,
        saved=interaction is not None and interaction.saved_at is not None,
        applied_at=interaction.applied_at if interaction else None,
        notes=interaction.notes if interaction else "",
        extract_version=posting.extract_version,
        needs_review=posting.needs_review,
        coverage=coverage,
        source_key=source_key,
        catalog_job=catalog_job,
    )


@router.get("/postings", response_model=PostingsOut)
async def postings(
    source: UUID | None = Query(default=None),
    remote: bool | None = Query(default=None),
    seniority: str | None = Query(default=None),
    catalog_job_id: UUID | None = Query(default=None),
    saved: bool = Query(default=False),
    sort: str = Query(default="fit", pattern="^(fit|fresh)$"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostingsOut:
    """Live tab: real vacancies mapped onto the catalog, unseen-first."""
    result = await list_postings(
        db,
        user.id,
        source_id=source,
        remote=remote,
        seniority=seniority,
        catalog_job_id=catalog_job_id,
        saved=saved,
        sort=sort,
    )
    sources = {
        s.id: s.key for s in (await db.execute(select(JobSource))).scalars().all()
    }
    return PostingsOut(
        total=result["total"],
        unseen=result["unseen"],
        items=[
            _posting_out(
                item["posting"],
                item["interaction"],
                fit=item.get("fit"),
                source_key=sources.get(item["posting"].source_id, ""),
            )
            for item in result["items"]
        ],
    )


@router.get("/postings/search", response_model=PostingSearchOut)
async def postings_search(
    skills: str = Query(min_length=1, max_length=500),
    mode: str = Query(default="all", pattern="^(all|any)$"),
    priority: str | None = Query(
        default=None, pattern="^(must_have|nice_to_have|bonus)$"
    ),
    source: UUID | None = Query(default=None),
    remote: bool | None = Query(default=None),
    seniority: str | None = Query(default=None),
    catalog_job_id: UUID | None = Query(default=None),
    saved: bool = Query(default=False),
    sort: str = Query(default="fresh", pattern="^(fit|fresh)$"),
    match_profile: bool = Query(default=False),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostingSearchOut:
    """Skill+level search (plan 31): `?skills=sql:4,python:3` joins
    posting_skills on skill_id + required_level ≥ requested; all/any
    semantics; `match_profile=true` ranks by deterministic coverage of
    the caller's user_skills (plan-22 curve)."""
    entries = parse_skill_entries(skills)
    result = await search_postings(
        db,
        user.id,
        entries=entries,
        mode=mode,
        priority=priority,
        source_id=source,
        remote=remote,
        seniority=seniority,
        catalog_job_id=catalog_job_id,
        saved=saved,
        sort=sort,
        match_profile=match_profile,
    )
    sources = {
        s.id: s.key for s in (await db.execute(select(JobSource))).scalars().all()
    }
    return PostingSearchOut(
        total=result["total"],
        unseen=result["unseen"],
        items=[
            _posting_out(
                item["posting"],
                item["interaction"],
                fit=item.get("fit"),
                coverage=item.get("coverage"),
                source_key=sources.get(item["posting"].source_id, ""),
            )
            for item in result["items"]
        ],
    )


@router.get("/postings/explore", response_model=ExploreOut)
async def postings_explore(
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExploreOut:
    """Explore (plan 32): the full filter+facet surface. Query params are
    the explore vocabulary — `skills=sql:4,python`, multi-value comma
    lists, `posted_within=7d`, `sort=fit|fresh|salary|relevance` and an
    opaque `cursor`."""
    raw = dict(request.query_params)
    # Pagination/sort controls are the endpoint's, not filter vocabulary.
    sort = raw.pop("sort", None) or "fit"
    cursor = raw.pop("cursor", None)
    limit = min(max(int(raw.pop("limit", None) or 20), 1), 100)
    multi = {key: [v for v in request.query_params.getlist(key)] for key in ("skills",)}
    for key, values in multi.items():
        if values and "," in values[0]:
            raw[key] = [part.strip() for part in values[0].split(",") if part.strip()]
    for key in (
        "seniority",
        "employment_type",
        "remote_policy",
        "source",
        "mapped_family",
        "languages",
    ):
        values = request.query_params.getlist(key)
        flattened: list[str] = []
        for value in values:
            flattened.extend(part.strip() for part in value.split(",") if part.strip())
        if flattened:
            raw[key] = flattened
    filters = parse_explore_filters(raw)

    result = await explore(db, user.id, filters, sort=sort, cursor=cursor, limit=limit)
    sources = {
        s.id: s.key for s in (await db.execute(select(JobSource))).scalars().all()
    }
    return ExploreOut(
        items=[
            _posting_out(
                item["posting"],
                item["interaction"],
                fit=item.get("fit"),
                source_key=sources.get(item["posting"].source_id, ""),
            )
            for item in result["items"]
        ],
        total=result["total"],
        next_cursor=result["next_cursor"],
        facets=result["facets"],
    )


@router.get("/postings/sources", response_model=list[dict])
async def postings_sources(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Enabled sources with open-posting counts (the filter dropdown)."""
    return await sources_with_counts(db)


@router.get("/postings/{posting_ref}", response_model=PostingDetailOut)
async def posting_detail(
    posting_ref: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostingDetailOut:
    """One posting by ref or id with the structured extract, source
    attribution, match-score card and the similar-postings rail."""
    from sqlalchemy.orm import selectinload

    from app.models.job_model import Job, JobSkill, JobTag
    from app.services.posting_fit_service import get_posting_fit

    posting = await resolve_posting(db, posting_ref)
    if posting is None:
        raise NotFoundError("Posting not found")
    posting = (
        (
            await db.execute(
                select(JobPosting)
                .options(
                    selectinload(JobPosting.catalog_job).selectinload(Job.family),
                    selectinload(JobPosting.catalog_job)
                    .selectinload(Job.tag_links)
                    .selectinload(JobTag.tag),
                    selectinload(JobPosting.catalog_job)
                    .selectinload(Job.skill_links)
                    .selectinload(JobSkill.skill),
                )
                .where(JobPosting.id == posting.id)
            )
        )
        .scalars()
        .unique()
        .first()
    )
    if posting is None:
        raise NotFoundError("Posting not found")

    source = (
        (await db.execute(select(JobSource).where(JobSource.id == posting.source_id)))
        .scalars()
        .first()
    )
    connector_title = source.connector_key if source else ""
    if source is not None:
        from app.connectors import registry

        try:
            connector_title = registry.get_connector(source.connector_key).title
        except Exception:  # noqa: BLE001 — plugin missing: fall back to key
            connector_title = source.connector_key
    match = await get_posting_fit(db, user.id, posting)
    similar = await similar_postings(db, posting)

    out = _posting_out(posting, None)
    return PostingDetailOut(
        **out.model_dump(),
        extract=posting.extract,
        source_title=connector_title,
        source_connector=source.key if source else "",
        source_synced_at=source.last_run_at if source else None,
        match=match,
        similar=similar,
    )


@router.post("/postings/seen")
async def postings_seen(
    data: SeenIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Batch impression marking, like the catalog feed."""
    marked = await mark_seen(db, user.id, data.posting_ids)
    return {"marked": marked}


@router.post("/postings/save")
async def postings_save(
    data: SaveIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Toggle the bookmark on a posting."""
    interaction = await set_state(
        db,
        user.id,
        data.posting_id,
        field="saved_at",
        value=datetime.now(timezone.utc) if data.saved else None,
    )
    return {
        "posting_id": str(interaction.posting_id),
        "saved": interaction.saved_at is not None,
    }


@router.post("/postings/hide")
async def postings_hide(
    data: SaveIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Toggle feed curation on a posting."""
    interaction = await set_state(
        db,
        user.id,
        data.posting_id,
        field="hidden_at",
        value=datetime.now(timezone.utc) if data.saved else None,
    )
    return {
        "posting_id": str(interaction.posting_id),
        "hidden": interaction.hidden_at is not None,
    }


@router.post("/postings/applied")
async def postings_applied(
    data: AppliedIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Applied tracking: set when the user opens the original URL."""
    interaction = await set_state(
        db,
        user.id,
        data.posting_id,
        field="applied_at",
        value=datetime.now(timezone.utc),
        extra={
            "applied_via_url": data.applied_via_url,
            "stage": data.stage.value if data.stage else "applied",
        },
    )
    return {
        "posting_id": str(interaction.posting_id),
        "applied_at": interaction.applied_at.isoformat(),
        "stage": interaction.stage,
    }
