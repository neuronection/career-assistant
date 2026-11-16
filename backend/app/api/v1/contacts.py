"""Contacts and outreach REST surface (plan 213 W1)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AINotConfiguredError, DomainError
from app.schemas.contact import (
    ContactDetailOut,
    ContactIn,
    ContactInteractionIn,
    ContactInteractionOut,
    ContactOut,
    ContactPatch,
    OutreachDraftIn,
    OutreachDraftOut,
)
from app.services.deps import get_current_user
from app.services.profile.contact_service import ContactService

router = APIRouter(prefix="/me/contacts", tags=["contacts"])


def _detail(contact, interactions) -> ContactDetailOut:
    return ContactDetailOut(
        **ContactOut.model_validate(contact).model_dump(),
        interactions=[ContactInteractionOut.model_validate(row) for row in interactions],
    )


@router.get("", response_model=list[ContactOut])
async def list_contacts(
    q: str = Query(default="", max_length=200),
    org: str = Query(default="", max_length=200),
    application_id: uuid.UUID | None = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ContactOut]:
    rows = await ContactService(db).list_contacts(
        user.id, q=q, org=org, application_id=application_id
    )
    return [ContactOut.model_validate(row) for row in rows]


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
async def create_contact(
    payload: ContactIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContactOut:
    return ContactOut.model_validate(await ContactService(db).create(user.id, payload))


@router.get("/{contact_id}", response_model=ContactDetailOut)
async def get_contact(
    contact_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContactDetailOut:
    contact, interactions = await ContactService(db).detail(user.id, contact_id)
    return _detail(contact, interactions)


@router.patch("/{contact_id}", response_model=ContactOut)
async def patch_contact(
    contact_id: uuid.UUID,
    payload: ContactPatch,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContactOut:
    return ContactOut.model_validate(await ContactService(db).update(user.id, contact_id, payload))


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await ContactService(db).delete(user.id, contact_id)


@router.post(
    "/{contact_id}/interactions",
    response_model=ContactInteractionOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_interaction(
    contact_id: uuid.UUID,
    payload: ContactInteractionIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContactInteractionOut:
    return ContactInteractionOut.model_validate(
        await ContactService(db).add_interaction(user.id, contact_id, payload)
    )


@router.delete(
    "/{contact_id}/interactions/{interaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_interaction(
    contact_id: uuid.UUID,
    interaction_id: uuid.UUID,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await ContactService(db).delete_interaction(user.id, contact_id, interaction_id)


@router.post("/{contact_id}/draft", response_model=OutreachDraftOut)
async def draft_outreach(
    contact_id: uuid.UUID,
    payload: OutreachDraftIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OutreachDraftOut:
    try:
        return await ContactService(db).draft(user.id, contact_id, payload)
    except AINotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
