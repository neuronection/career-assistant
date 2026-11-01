from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.errors import NotFoundError
from app.models.application_model import Application
from app.models.job_model import Job, JobSkill, JobTag
from app.models.posting_model import JobPosting, JobSource, PostingInteraction
from app.schemas.posting import (
    AppliedIn,
    ExploreOut,
    PostingDetailOut,
    PostingExtractOut,
    PostingLocationOut,
    PostingMatchOut,
    PostingOut,
    PostingSearchOut,
    PostingSimilarOut,
    PostingsOut,
    SaveIn,
    SeenIn,
    SmartSearchIn,
    SmartSearchOut,
)
from app.schemas.radar import RadarIn
from app.services.deps import get_current_user
from app.services.postings.explore_service import (
    explore,
    parse_explore_filters,
    similar_postings,
    sources_with_counts,
)
from app.services.postings.postings_service import (
    list_postings,
    load_posting_skill_refs,
    mark_seen,
    parse_skill_entries,
    resolve_posting,
    search_postings,
    set_state,
)
from app.services.postings.text import plain_text

router = APIRouter(tags=["postings"])


def _posting_out(
    posting: JobPosting,
    interaction,
    application=None,
    fit=None,
    source_key="",
    org_key="",
    coverage=None,
    skills=None,
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
        org_key=org_key,
        org_match_state=posting.org_match_state,
        location=PostingLocationOut.model_validate(posting.location or {}),
        url=posting.url,
        seniority=posting.seniority,
        employment_type=posting.employment_type,
        contract_type=posting.contract_type,
        work_hours=posting.work_hours,
        hours_per_week_min=float(posting.hours_per_week_min)
        if posting.hours_per_week_min is not None
        else None,
        hours_per_week_max=float(posting.hours_per_week_max)
        if posting.hours_per_week_max is not None
        else None,
        travel_class=posting.travel_class,
        education_level=posting.education_level,
        onsite_policy=posting.onsite_policy,
        salary_currency=posting.salary_currency,
        salary_min=float(posting.salary_min) if posting.salary_min is not None else None,
        salary_max=float(posting.salary_max) if posting.salary_max is not None else None,
        salary_period=posting.salary_period,
        salary_basis=posting.salary_basis,
        salary_normalized_min=(
            float(posting.salary_normalized_min)
            if posting.salary_normalized_min is not None
            else None
        ),
        salary_normalized_max=(
            float(posting.salary_normalized_max)
            if posting.salary_normalized_max is not None
            else None
        ),
        posted_at=posting.posted_at,
        expires_at=posting.expires_at,
        created_at=posting.created_at,
        updated_at=posting.updated_at,
        status=posting.status,
        catalog_job_id=posting.catalog_job_id,
        mapping_method=posting.mapping_method,
        mapping_confidence=posting.mapping_confidence,
        mapping_reason=posting.mapping_reason,
        fit=fit,
        seen=interaction is not None and interaction.seen_at is not None,
        saved=interaction is not None and interaction.saved_at is not None,
        applied_at=application.applied_at if application else None,
        notes=application.notes if application else "",
        application_id=application.id if application else None,
        stage=application.stage if application else None,
        extract_version=posting.extract_version,
        needs_review=posting.needs_review,
        coverage=coverage,
        source_key=source_key,
        catalog_job=catalog_job,
        skills=skills or [],
    )


async def _org_keys(db: AsyncSession) -> dict[UUID, str]:
    from app.models.experience_model import Organization

    rows = (await db.execute(select(Organization))).scalars().all()
    return {row.id: row.key for row in rows}


@router.get("/postings", response_model=PostingsOut)
async def postings(
    source: UUID | None = Query(default=None),
    remote: bool | None = Query(default=None),
    seniority: str | None = Query(default=None),
    catalog_job_id: UUID | None = Query(default=None),
    saved: bool = Query(default=False),
    sort: str = Query(default="fit", pattern="^(fit|fresh)$"),
    company: str | None = Query(default=None, max_length=120),
    no_company: str | None = Query(default=None, pattern="^(rejected|pending)$"),
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
        company=company,
        no_company=no_company,
    )
    sources = {s.id: s.key for s in (await db.execute(select(JobSource))).scalars().all()}
    orgs = await _org_keys(db)
    skill_refs = await load_posting_skill_refs(db, [item["posting"].id for item in result["items"]])
    return PostingsOut(
        total=result["total"],
        unseen=result["unseen"],
        items=[
            _posting_out(
                item["posting"],
                item["interaction"],
                item.get("application"),
                fit=item.get("fit"),
                source_key=sources.get(item["posting"].source_id, ""),
                org_key=orgs.get(item["posting"].org_id, ""),
                skills=skill_refs.get(item["posting"].id),
            )
            for item in result["items"]
        ],
    )


@router.get("/postings/search", response_model=PostingSearchOut)
async def postings_search(
    skills: str = Query(min_length=1, max_length=500),
    mode: str = Query(default="all", pattern="^(all|any)$"),
    priority: str | None = Query(default=None, pattern="^(must_have|nice_to_have|bonus)$"),
    source: UUID | None = Query(default=None),
    remote: bool | None = Query(default=None),
    seniority: str | None = Query(default=None),
    catalog_job_id: UUID | None = Query(default=None),
    saved: bool = Query(default=False),
    sort: str = Query(default="fresh", pattern="^(fit|fresh)$"),
    match_profile: bool = Query(default=False),
    company: str | None = Query(default=None, max_length=120),
    no_company: str | None = Query(default=None, pattern="^(rejected|pending)$"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostingSearchOut:
    """Skill+level search: `?skills=sql:4,python:3` joins
    posting_skills on skill_id + required_level ≥ requested; all/any
    semantics; `match_profile=true` ranks by deterministic coverage of
    the caller's user_skills."""
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
        company=company,
        no_company=no_company,
    )
    sources = {s.id: s.key for s in (await db.execute(select(JobSource))).scalars().all()}
    orgs = await _org_keys(db)
    skill_refs = await load_posting_skill_refs(db, [item["posting"].id for item in result["items"]])
    return PostingSearchOut(
        total=result["total"],
        unseen=result["unseen"],
        items=[
            _posting_out(
                item["posting"],
                item["interaction"],
                item.get("application"),
                fit=item.get("fit"),
                coverage=item.get("coverage"),
                source_key=sources.get(item["posting"].source_id, ""),
                org_key=orgs.get(item["posting"].org_id, ""),
                skills=skill_refs.get(item["posting"].id),
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
    """Explore: the full filter+facet surface. Query params are
    the explore vocabulary — `skills=sql:4,python`, multi-value comma
    lists, `posted_within=7d`, `sort=fit|fresh|salary|relevance` and an
    opaque `cursor`."""
    raw: dict[str, str | list[str]] = dict(request.query_params)
    # Pagination/sort controls are the endpoint's, not filter vocabulary.
    sort = request.query_params.get("sort") or "fit"
    cursor = request.query_params.get("cursor")
    limit = min(max(int(request.query_params.get("limit") or 20), 1), 100)
    for control in ("sort", "cursor", "limit"):
        raw.pop(control, None)
    multi = {key: list(request.query_params.getlist(key)) for key in ("skills",)}
    for key, values in multi.items():
        if values and "," in values[0]:
            raw[key] = [part.strip() for part in values[0].split(",") if part.strip()]
    # org names may contain commas ("Acme, Inc.") — repeated params only,
    # never comma-split (unlike the enum axes below).
    for key in ("org", "org_exclude"):
        values = [value.strip() for value in request.query_params.getlist(key) if value.strip()]
        if values:
            raw[key] = values
    for key in (
        "seniority",
        "employment_type",
        "remote_policy",
        "source",
        "mapped_family",
        "languages",
        "contract",
        "travel",
        "schedule",
        "benefits",
    ):
        values = request.query_params.getlist(key)
        flattened: list[str] = []
        for value in values:
            flattened.extend(part.strip() for part in value.split(",") if part.strip())
        if flattened:
            raw[key] = flattened
    filters = parse_explore_filters(raw)

    result = await explore(db, user.id, filters, sort=sort, cursor=cursor, limit=limit)
    sources = {s.id: s.key for s in (await db.execute(select(JobSource))).scalars().all()}
    orgs = await _org_keys(db)
    skill_refs = await load_posting_skill_refs(db, [item["posting"].id for item in result["items"]])
    return ExploreOut(
        items=[
            _posting_out(
                item["posting"],
                item["interaction"],
                item.get("application"),
                fit=item.get("fit"),
                source_key=sources.get(item["posting"].source_id, ""),
                org_key=orgs.get(item["posting"].org_id, ""),
                skills=skill_refs.get(item["posting"].id),
            )
            for item in result["items"]
        ],
        total=result["total"],
        next_cursor=result["next_cursor"],
        facets=result["facets"],
    )


@router.post("/postings/preview-radar", response_model=ExploreOut)
async def preview_job_radar(
    data: RadarIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExploreOut:
    """Live radar preview: what this configuration would match right now,
    without saving it."""
    from app.services.postings.radar_service import explore_params

    filters = explore_params(data)
    result = await explore(db, user.id, filters, sort="fresh", limit=5)
    sources = {s.id: s.key for s in (await db.execute(select(JobSource))).scalars().all()}
    orgs = await _org_keys(db)
    skill_refs = await load_posting_skill_refs(db, [item["posting"].id for item in result["items"]])
    return ExploreOut(
        items=[
            _posting_out(
                item["posting"],
                item["interaction"],
                item.get("application"),
                fit=item.get("fit"),
                source_key=sources.get(item["posting"].source_id, ""),
                org_key=orgs.get(item["posting"].org_id, ""),
                skills=skill_refs.get(item["posting"].id),
            )
            for item in result["items"]
        ],
        total=result["total"],
        next_cursor=result["next_cursor"],
        facets=result["facets"],
    )


@router.post("/postings/smart-search", response_model=SmartSearchOut)
async def postings_smart_search(
    data: SmartSearchIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SmartSearchOut:
    """Natural-language search (plan 179): the sentence maps onto the
    explore filter vocabulary through one small cached AI call (per-user
    limiter and budget apply on misses; cache hits cost zero). The
    client then runs the normal explore query with the returned
    filters — facets stay live."""
    from app.services.postings.smart_search_service import run_smart_search

    result = await run_smart_search(db, user.id, data.query)
    await db.commit()
    return SmartSearchOut.model_validate(result)


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
    from app.services.postings.posting_fit_service import get_posting_fit

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
        from app.extensions import registry

        try:
            connector_title = registry.get_connector(source.connector_key).title
        except Exception:
            connector_title = source.connector_key
    match = await get_posting_fit(db, user.id, posting)
    similar = await similar_postings(db, posting)

    from app.models.posting_model import PostingInteraction
    from app.services.postings.applications_service import get_application

    interaction = (
        (
            await db.execute(
                select(PostingInteraction).where(
                    PostingInteraction.user_id == user.id,
                    PostingInteraction.posting_id == posting.id,
                )
            )
        )
        .scalars()
        .first()
    )
    application = await get_application(db, user.id, posting.id)

    org_key = ""
    if posting.org_id is not None:
        from app.models.experience_model import Organization

        org_key = (
            await db.execute(select(Organization.key).where(Organization.id == posting.org_id))
        ).scalars().first() or ""
    skill_refs = await load_posting_skill_refs(db, [posting.id])
    out = _posting_out(
        posting,
        interaction,
        application,
        org_key=org_key,
        skills=skill_refs.get(posting.id),
    )
    raw_description = (posting.raw or {}).get("description")
    return PostingDetailOut(
        **out.model_dump(),
        description=plain_text(raw_description if isinstance(raw_description, str) else ""),
        extract=PostingExtractOut.model_validate(posting.extract) if posting.extract else None,
        source_title=(source.title if source else "") or connector_title,
        source_connector=source.key if source else "",
        source_synced_at=source.last_run_at if source else None,
        match=PostingMatchOut.model_validate(match) if match else None,
        similar=[PostingSimilarOut.model_validate(row) for row in similar],
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
        value=datetime.now(UTC) if data.saved else None,
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
        value=datetime.now(UTC) if data.saved else None,
    )
    return {
        "posting_id": str(interaction.posting_id),
        "hidden": interaction.hidden_at is not None,
    }


@router.post("/postings/applied")
async def postings_applied(
    data: AppliedIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Applied tracking: the pipeline row plus its first stage event."""
    from app.services.postings.applications_service import apply_to_posting

    application = await apply_to_posting(
        db,
        user.id,
        data.posting_id,
        applied_via_url=data.applied_via_url,
        stage=data.stage,
    )
    return {
        "posting_id": str(application.posting_id),
        "applied_at": application.applied_at.isoformat() if application.applied_at else None,
        "stage": application.stage,
    }


# ---------------------------------------------------- filter system (plan 136)


@router.post("/postings/filter", response_model=list[PostingOut])
async def postings_filter(
    payload: dict,
    company: str | None = Query(default=None, max_length=120),
    no_company: str | None = Query(default=None, pattern="^(rejected|pending)$"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """The full filter spec search (plan 136): every axis, three-valued
    include/exclude/don't-care, open numeric bounds. `company` /
    `no_company` are the plan-135 feed filters and compose with the spec
    (same semantics as the live feed)."""
    from pydantic import ValidationError as PydanticValidationError

    from app.models.experience_model import Organization
    from app.services.postings.filter_expand import expand_filter_spec
    from app.services.postings.filter_query import build_where
    from app.services.postings.filter_spec import PostingFilterSpec

    try:
        spec = PostingFilterSpec.model_validate(payload.get("filters") or {})
    except PydanticValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid filter spec: {exc}") from exc

    spec = await expand_filter_spec(db, spec)
    where = build_where(spec)
    query = (
        select(JobPosting, PostingInteraction, Application)
        .options(
            selectinload(JobPosting.catalog_job).selectinload(Job.family),
            selectinload(JobPosting.catalog_job)
            .selectinload(Job.tag_links)
            .selectinload(JobTag.tag),
            selectinload(JobPosting.catalog_job)
            .selectinload(Job.skill_links)
            .selectinload(JobSkill.skill),
        )
        .outerjoin(
            PostingInteraction,
            and_(
                PostingInteraction.posting_id == JobPosting.id,
                PostingInteraction.user_id == user.id,
            ),
        )
        .outerjoin(Application, Application.posting_id == JobPosting.id)
        .where(JobPosting.status.in_(["new", "mapped"]))
    )
    for clause in where:
        query = query.where(clause)
    if company is not None:
        org_id = (
            await db.execute(select(Organization.id).where(Organization.key == company))
        ).scalar_one_or_none()
        if org_id is None:
            return []
        query = query.where(JobPosting.org_id == org_id)
    if no_company is not None:
        query = query.where(JobPosting.org_id.is_(None), JobPosting.org_match_state == no_company)
    if spec.sort == "fit":
        query = query.order_by(
            JobPosting.catalog_job_id.desc().nullslast(), JobPosting.posted_at.desc()
        )
    else:
        query = query.order_by(JobPosting.posted_at.desc())
    query = query.limit(200)

    rows = (await db.execute(query)).all()
    sources = {s.id: s.key for s in (await db.execute(select(JobSource))).scalars().all()}
    orgs = await _org_keys(db)
    skill_refs = await load_posting_skill_refs(db, [posting.id for posting, _, _ in rows])
    return [
        _posting_out(
            posting,
            interaction,
            application,
            source_key=sources.get(posting.source_id, ""),
            org_key=orgs.get(posting.org_id, ""),
            skills=skill_refs.get(posting.id),
        )
        for posting, interaction, application in rows
    ]


@router.get("/me/posting-filters", response_model=list[dict])
async def list_filter_presets(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Saved filter presets for the active profile, newest first."""
    from app.core.profile_context import active_profile_id
    from app.models.posting_model import PostingFilterPreset

    profile_id = active_profile_id()
    if profile_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Profile-Id required")
    rows = (
        (
            await db.execute(
                select(PostingFilterPreset)
                .where(PostingFilterPreset.profile_id == profile_id)
                .order_by(PostingFilterPreset.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "tags": r.tags or [],
            "filters": r.filters or {},
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


@router.post("/me/posting-filters", status_code=201, response_model=dict)
async def create_filter_preset(
    payload: dict,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Save (or update by name) a named, tagged filter preset."""
    from pydantic import ValidationError as PydanticValidationError

    from app.core.profile_context import active_profile_id
    from app.models.posting_model import PostingFilterPreset
    from app.services.postings.filter_spec import PostingFilterSpec

    profile_id = active_profile_id()
    if profile_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Profile-Id required")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "name is required")
    tags = [str(t)[:40] for t in (payload.get("tags") or [])][:20]
    try:
        spec = PostingFilterSpec.model_validate(payload.get("filters") or {})
    except PydanticValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid filter spec: {exc}") from exc
    filters = spec.model_dump(mode="json")

    existing = (
        (
            await db.execute(
                select(PostingFilterPreset).where(
                    PostingFilterPreset.profile_id == profile_id,
                    PostingFilterPreset.name == name,
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        existing.tags = tags
        existing.filters = filters
        await db.commit()
        return {
            "id": str(existing.id),
            "name": existing.name,
            "tags": existing.tags,
            "filters": existing.filters,
        }

    preset = PostingFilterPreset(
        profile_id=profile_id,
        name=name[:120],
        tags=tags,
        filters=filters,
    )
    db.add(preset)
    await db.commit()
    return {
        "id": str(preset.id),
        "name": preset.name,
        "tags": preset.tags,
        "filters": preset.filters,
    }


@router.delete("/me/posting-filters/{preset_id}", status_code=204)
async def delete_filter_preset(
    preset_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    from app.core.profile_context import active_profile_id
    from app.models.posting_model import PostingFilterPreset

    profile_id = active_profile_id()
    if profile_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Profile-Id required")
    preset = (
        (
            await db.execute(
                select(PostingFilterPreset).where(
                    PostingFilterPreset.id == preset_id,
                    PostingFilterPreset.profile_id == profile_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if preset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Preset not found")
    await db.delete(preset)
    await db.commit()
