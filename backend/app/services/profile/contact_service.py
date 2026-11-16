"""Contacts and outreach drafts (plan 213 W1).

Flat, user-owned records with explicit ownership on every read/write.
Drafts are copy-only: one typed structured call through the existing
`ASSIST` task, grounded in the contact/application/posting/profile facts
we hand it; nothing is sent and nothing is scraped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json
from app.ai.gateway import ainvoke_structured
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.application_model import Application
from app.models.contact_model import Contact, ContactInteraction
from app.models.enums import AITaskType
from app.models.posting_model import JobPosting
from app.schemas.contact import (
    ContactIn,
    ContactInteractionIn,
    ContactPatch,
    OutreachDraftAI,
    OutreachDraftIn,
    OutreachDraftOut,
    OutreachEvidence,
)
from app.services.profile.profile_service import ProfileService

CONTACTS_LIST_CAP = 500

OUTREACH_SYSTEM = """You draft one short outreach message for a job seeker.
Use only the supplied contact, application, posting and profile facts.
Never invent a company, person, role, deadline or relationship. Keep the
subject under 120 characters and the body under 900 characters. The user
will copy the message and send it themselves; do not claim it was sent.
Return JSON with subject, body and evidence_refs. Each evidence_ref must
name one supplied fact by source and label."""


class ContactService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_contacts(
        self,
        user_id: uuid.UUID,
        *,
        q: str = "",
        org: str = "",
        application_id: uuid.UUID | None = None,
    ) -> list[Contact]:
        query = select(Contact).where(Contact.user_id == user_id)
        if q.strip():
            pattern = f"%{q.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(Contact.name).like(pattern),
                    func.lower(Contact.org).like(pattern),
                    func.lower(Contact.role).like(pattern),
                    func.lower(Contact.email).like(pattern),
                )
            )
        if org.strip():
            query = query.where(func.lower(Contact.org) == org.strip().lower())
        if application_id is not None:
            query = query.join(Application, Application.contact_id == Contact.id).where(
                Application.user_id == user_id,
                Application.id == application_id,
            )
        rows = await self.db.execute(
            query.order_by(
                Contact.last_contacted_at.desc().nulls_last(),
                func.lower(Contact.name),
            ).limit(CONTACTS_LIST_CAP)
        )
        return list(rows.scalars().all())

    async def get(self, user_id: uuid.UUID, contact_id: uuid.UUID) -> Contact:
        contact = await self.db.get(Contact, contact_id)
        if contact is None or contact.user_id != user_id:
            raise NotFoundError("Contact not found")
        return contact

    async def detail(
        self, user_id: uuid.UUID, contact_id: uuid.UUID
    ) -> tuple[Contact, list[ContactInteraction]]:
        contact = await self.get(user_id, contact_id)
        rows = await self.db.execute(
            select(ContactInteraction)
            .where(ContactInteraction.contact_id == contact.id)
            .order_by(ContactInteraction.at.desc())
        )
        return contact, list(rows.scalars().all())

    @staticmethod
    def email_key(email: str) -> str | None:
        value = (email or "").strip().lower()
        return value[:200] or None

    async def create(self, user_id: uuid.UUID, payload: ContactIn) -> Contact:
        key = self.email_key(payload.email)
        if key is not None:
            existing = (
                (
                    await self.db.execute(
                        select(Contact).where(Contact.user_id == user_id, Contact.email_key == key)
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                raise ConflictError("A contact with that email already exists")
        contact = Contact(
            user_id=user_id,
            **payload.model_dump(),
            email_key=key,
        )
        self.db.add(contact)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError("A contact with that email already exists") from exc
        await self.db.refresh(contact)
        return contact

    async def update(
        self, user_id: uuid.UUID, contact_id: uuid.UUID, patch: ContactPatch
    ) -> Contact:
        contact = await self.get(user_id, contact_id)
        data = patch.model_dump(exclude_unset=True)
        if "email" in data:
            key = self.email_key(data["email"] or "")
            if key is not None:
                other = (
                    (
                        await self.db.execute(
                            select(Contact).where(
                                Contact.user_id == user_id,
                                Contact.email_key == key,
                                Contact.id != contact.id,
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if other is not None:
                    raise ConflictError("Another contact already uses that email")
            contact.email_key = key
        for field, value in data.items():
            setattr(contact, field, value)
        await self.db.commit()
        await self.db.refresh(contact)
        return contact

    async def delete(self, user_id: uuid.UUID, contact_id: uuid.UUID) -> None:
        contact = await self.get(user_id, contact_id)
        await self.db.delete(contact)
        await self.db.commit()

    async def add_interaction(
        self, user_id: uuid.UUID, contact_id: uuid.UUID, payload: ContactInteractionIn
    ) -> ContactInteraction:
        contact = await self.get(user_id, contact_id)
        if payload.application_id is not None:
            application = await self.db.get(Application, payload.application_id)
            if application is None or application.user_id != user_id:
                raise NotFoundError("Application not found")
        at = payload.at
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        interaction = ContactInteraction(
            contact_id=contact.id,
            application_id=payload.application_id,
            kind=payload.kind,
            at=at,
            channel=payload.channel,
            notes=payload.notes,
        )
        self.db.add(interaction)
        await self.db.flush()
        await self._recompute_last_contacted(contact)
        await self.db.commit()
        await self.db.refresh(interaction)
        return interaction

    async def delete_interaction(
        self, user_id: uuid.UUID, contact_id: uuid.UUID, interaction_id: uuid.UUID
    ) -> None:
        contact = await self.get(user_id, contact_id)
        row = await self.db.get(ContactInteraction, interaction_id)
        if row is None or row.contact_id != contact.id:
            raise NotFoundError("Interaction not found")
        await self.db.delete(row)
        await self.db.flush()
        await self._recompute_last_contacted(contact)
        await self.db.commit()

    async def _recompute_last_contacted(self, contact: Contact) -> None:
        latest = (
            await self.db.execute(
                select(func.max(ContactInteraction.at)).where(
                    ContactInteraction.contact_id == contact.id
                )
            )
        ).scalar_one_or_none()
        contact.last_contacted_at = latest

    async def draft(
        self,
        user_id: uuid.UUID,
        contact_id: uuid.UUID,
        payload: OutreachDraftIn,
    ) -> OutreachDraftOut:
        contact = await self.get(user_id, contact_id)
        application: Application | None = None
        posting: JobPosting | None = None
        if payload.application_id is not None:
            row = (
                await self.db.execute(
                    select(Application, JobPosting)
                    .join(JobPosting, JobPosting.id == Application.posting_id)
                    .where(
                        Application.id == payload.application_id,
                        Application.user_id == user_id,
                    )
                )
            ).first()
            if row is None:
                raise NotFoundError("Application not found")
            application, posting = row[0], row[1]

        profile = await ProfileService(self.db).get(user_id)
        basics = profile.basics or {}
        evidence: list[OutreachEvidence] = [
            OutreachEvidence(
                source="contact",
                label="contact",
                quote=" · ".join(
                    part
                    for part in (
                        contact.name,
                        contact.role,
                        contact.org,
                    )
                    if part
                ),
            )
        ]
        if basics.get("headline"):
            evidence.append(
                OutreachEvidence(
                    source="profile",
                    label="headline",
                    quote=str(basics["headline"])[:500],
                )
            )
        if application is not None:
            evidence.append(
                OutreachEvidence(
                    source="application",
                    label="stage",
                    quote=f"stage: {application.stage}",
                )
            )
        if posting is not None:
            evidence.append(
                OutreachEvidence(
                    source="posting",
                    label="role",
                    quote=f"{posting.org} — {posting.title}"[:500],
                )
            )
        context = {
            "kind": payload.kind,
            "contact": {
                "name": contact.name,
                "role": contact.role,
                "org": contact.org,
                "notes": contact.notes,
            },
            "application": {"stage": application.stage} if application else None,
            "posting": (
                {"org": posting.org, "title": posting.title, "url": posting.url}
                if posting
                else None
            ),
            "profile": {
                "headline": basics.get("headline") or "",
                "city": basics.get("city") or "",
                "country": basics.get("country") or "",
            },
            "evidence": [entry.model_dump() for entry in evidence],
        }

        result = await ainvoke_structured(
            self.db,
            AITaskType.ASSIST,
            OutreachDraftAI,
            system=OUTREACH_SYSTEM,
            user=context_json(context),
            user_id=user_id,
        )
        allowed = {(entry.source, entry.label): entry for entry in evidence}
        cited: list[OutreachEvidence] = []
        for ref in result.evidence_refs:
            match = allowed.get((ref.source, ref.label))
            if match is not None and match not in cited:
                cited.append(match)
        if not cited:
            raise ValidationError("The draft did not cite any supplied evidence")
        return OutreachDraftOut(
            kind=payload.kind,
            subject=result.subject,
            body=result.body,
            evidence_refs=cited[:12],
            model=AITaskType.ASSIST.value,
            generated_at=datetime.now(UTC),
        )
