"""HITL profile proposals API (plan 77): list + idempotent resolve."""

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.profile_proposal import (
    ProfileProposalOut,
    ProfileProposalPreviewOut,
    ProfileProposalResolveOut,
)
from app.services.deps import get_current_user
from app.services.profile_proposal_service import (
    ProfileProposalService,
    proposal_title,
)

router = APIRouter(tags=["profile-proposals"])


def _out(proposal) -> ProfileProposalOut:
    return ProfileProposalOut(
        id=proposal.id,
        kind=proposal.kind,
        action=proposal.action,
        status=proposal.status,
        entity_id=proposal.entity_id,
        entity_label=proposal.entity_label,
        title=proposal_title(proposal),
        payload=proposal.payload_json or {},
        diff=proposal.diff_json or [],
        destructive=proposal.action == "delete",
        source=proposal.source,
        chat_session_id=proposal.chat_session_id,
        chat_message_id=proposal.chat_message_id,
        ai_generation_id=proposal.ai_generation_id,
        created_at=proposal.created_at,
        resolved_at=proposal.resolved_at,
        resolve_error=proposal.resolve_error,
    )


@router.get("/me/profile-proposals")
async def list_profile_proposals(
    status: Optional[
        Literal["pending", "approved", "rejected", "conflict", "expired", "reverted"]
    ] = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    service = ProfileProposalService(db)
    proposals = await service.list_(user.id, status=status, limit=limit)
    return {
        "proposals": [_out(p).model_dump(mode="json") for p in proposals],
        "pending_count": await service.pending_count(user.id),
    }


@router.post(
    "/me/profile-proposals/{proposal_id}/approve",
    response_model=ProfileProposalResolveOut,
)
async def approve_profile_proposal(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ProfileProposalResolveOut:
    proposal, applied, already = await ProfileProposalService(db).approve(
        user.id, proposal_id
    )
    return ProfileProposalResolveOut(
        proposal=_out(proposal), applied=applied, already=already
    )


@router.get(
    "/me/profile-proposals/{proposal_id}/preview",
    response_model=ProfileProposalPreviewOut,
)
async def preview_profile_proposal(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ProfileProposalPreviewOut:
    preview = await ProfileProposalService(db).preview(user.id, proposal_id)
    return ProfileProposalPreviewOut(
        before=preview["before"],
        after=preview["after"],
        edits=preview["edits"],
    )


@router.post(
    "/me/profile-proposals/{proposal_id}/revert",
    response_model=ProfileProposalOut,
)
async def revert_profile_proposal(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ProfileProposalOut:
    proposal = await ProfileProposalService(db).revert(user.id, proposal_id)
    return _out(proposal)


@router.post(
    "/me/profile-proposals/{proposal_id}/reject",
    response_model=ProfileProposalResolveOut,
)
async def reject_profile_proposal(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ProfileProposalResolveOut:
    proposal = await ProfileProposalService(db).reject(user.id, proposal_id)
    return ProfileProposalResolveOut(proposal=_out(proposal))


@router.delete("/me/profile-proposals/{proposal_id}", status_code=204)
async def dismiss_profile_proposal(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> None:
    await ProfileProposalService(db).reject(user.id, proposal_id)
