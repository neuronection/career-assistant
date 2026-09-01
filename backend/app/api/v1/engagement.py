from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.enums import SearchScope
from app.schemas.engagement import (
    FeedItemOut,
    FeedOut,
    HideIn,
    RuleIn,
    RuleOut,
    RulesOut,
    SaveIn,
    SearchOut,
    SearchRecordIn,
    SeenIn,
    UnseenCountOut,
)
from app.schemas.job import JobOut
from app.schemas.matching import MatchInsightOut
from app.services.deps import get_current_user, get_profile_for_user
from app.services.engagement_service import EngagementService

router = APIRouter(tags=["engagement"])


def _insight_out(insight) -> MatchInsightOut:
    """Serialise an insight row (shared shape with the matching API)."""
    from app.api.v1.matching import _insight_out as matching_insight_out

    return matching_insight_out(insight)


@router.post("/me/searches", response_model=SearchOut, status_code=201)
async def record_search(
    data: SearchRecordIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SearchOut:
    """Remember a search (debounced: same query+filters inside 30 min updates)."""
    row = await EngagementService(db).record_search(
        user.id, data.scope, data.query, data.filters, data.result_count
    )
    return SearchOut.model_validate(row)


@router.get("/me/searches", response_model=list[SearchOut])
async def list_searches(
    scope: SearchScope | None = Query(default=None),
    saved: bool | None = Query(default=None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SearchOut]:
    """Recent (or saved) searches, newest first."""
    rows = await EngagementService(db).list_searches(user.id, scope=scope, saved=saved)
    return [SearchOut.model_validate(row) for row in rows]


@router.delete("/me/searches/{search_id}", status_code=204)
async def delete_search(
    search_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Drop one remembered search."""
    await EngagementService(db).delete_search(user.id, search_id)


@router.post("/me/searches/{search_id}/save", response_model=SearchOut)
async def save_search(
    search_id: UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SearchOut:
    """Mark a search as saved (reused by alert rules via plan 29)."""
    row = await EngagementService(db).save_search(user.id, search_id)
    return SearchOut.model_validate(row)


@router.get("/feed", response_model=FeedOut)
async def feed(
    view: str = Query(default="all", pattern="^(all|saved)$"),
    sort: str = Query(default="fit", pattern="^(fit|recent)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=50),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeedOut:
    """Discovery feed: unseen-first, fit-sorted, with the exploration slot."""
    profile = await get_profile_for_user(db, user.id)
    result = await EngagementService(db).feed(
        profile, view=view, sort=sort, page=page, page_size=page_size
    )
    return FeedOut(
        total=result["total"],
        unseen=result["unseen"],
        items=[
            FeedItemOut(
                job=JobOut.from_model(item["job"]),
                fit_score=item["fit_score"],
                insight=_insight_out(item["insight"]),
                seen=item["seen"],
                saved=item["saved"],
                user_notes=item["insight"].user_notes,
                exploration=item["exploration"],
            )
            for item in result["items"]
        ],
    )


@router.get("/feed/unseen-count", response_model=UnseenCountOut)
async def feed_unseen_count(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> UnseenCountOut:
    """Badge counter: eligible jobs not yet seen."""
    profile = await get_profile_for_user(db, user.id)
    unseen = await EngagementService(db).unseen_count(profile)
    return UnseenCountOut(unseen=unseen)


@router.post("/feed/seen")
async def mark_seen(
    data: SeenIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Batch-mark jobs seen on impression (insight rows lazily created)."""
    marked = await EngagementService(db).mark_seen(user.id, data.job_ids)
    return {"marked": marked}


@router.post("/feed/save")
async def save_job(
    data: SaveIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Toggle the bookmark on a job."""
    insight = await EngagementService(db).set_saved(user.id, data.job_id, data.saved)
    return {
        "job_id": str(insight.job_id),
        "saved": insight.saved_at is not None,
        "insight": _insight_out(insight),
    }


@router.post("/feed/hide")
async def hide_job(
    data: HideIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Toggle feed curation (hidden) on a job — dismissed stays semantic."""
    insight = await EngagementService(db).set_hidden(user.id, data.job_id, data.hidden)
    return {
        "job_id": str(insight.job_id),
        "hidden": insight.hidden_at is not None,
        "insight": _insight_out(insight),
    }


@router.get("/notifications/rules", response_model=RulesOut)
async def get_rules(
    user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> RulesOut:
    """The caller's alert rules; defaults shown when never edited."""
    rules = await EngagementService(db).get_rules(user.id)
    return RulesOut(items=[RuleOut.model_validate(rule) for rule in rules])


@router.put("/notifications/rules", response_model=RulesOut)
async def put_rule(
    data: RuleIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> RulesOut:
    """Upsert one alert rule (unknown family keys are rejected)."""
    await EngagementService(db).upsert_rule(
        user.id, data.kind, data.params.model_dump(mode="json"), data.enabled
    )
    rules = await EngagementService(db).get_rules(user.id)
    return RulesOut(items=[RuleOut.model_validate(rule) for rule in rules])
