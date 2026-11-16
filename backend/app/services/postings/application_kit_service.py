"""The application kit (plan 212 S1.3): one read model per posting.

The kit turns a saved posting into a reviewable application: the S1.1
gap report, the user's CV / cover-letter state, deterministic screening
prompts and a sourced checklist. Every list is bounded, nothing is
written — `prepare` recomputes deterministically and creates neither a
CV, a letter nor an application row, and the only writes (linking
documents, recording `applied_at`/stage) stay on `ApplicationService`
behind an explicit user action. No AI runs here and no new AI task
exists: the deterministic tailor coverage is reused as-is, and AI
proposals remain CV Studio's own draft-then-approve actions.

Checklist labels are static English strings (like the ATS lint's own
messages) with their source attached; hints are general guidance and
never claim to simulate any ATS product.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.application_model import Application, ApplicationEvent
from app.models.cv_model import CvDocument
from app.models.posting_model import JobPosting
from app.schemas.application import ApplicationEventOut
from app.schemas.kit import (
    ApplicationKitOut,
    KitAnswerPrompt,
    KitApplicationState,
    KitCheckLevel,
    KitChecklistItem,
    KitCvState,
    KitDocumentRef,
    KitLetterState,
    KitLinkedDocuments,
    KitPostingOut,
    KitPrepareOut,
    PostingKitOut,
)
from app.schemas.posting import (
    PostingExtractOut,
    PostingGapOut,
    PostingLocationOut,
)
from app.services.cv.cv_export_service import CvExportService
from app.services.cv.cv_suggestion_service import CvSuggestionService, tailor_coverage
from app.services.postings.applications_service import ApplicationService
from app.services.postings.gap_service import (
    build_posting_gap,
    skill_labels,
    skill_levels,
    user_evidence,
)

CV_CANDIDATE_CAP = 10
TIMELINE_CAP = 50

# Deterministic common screening prompts (S1.3 placeholder state): a
# fixed, bounded set; `saved_answer` stays null until the S1.5 answer
# library lands. The frontend localizes by `key` and falls back to the
# server prompt.
ANSWER_PROMPTS: tuple[tuple[str, str], ...] = (
    ("availability", "When can you start?"),
    ("work_authorization", "Are you legally authorized to work in the job's location?"),
    ("salary_expectation", "What are your salary expectations?"),
    ("notice_period", "How much notice does your current role require?"),
    ("languages", "Which languages do you speak, and at what level?"),
    ("relocation", "Are you willing to relocate for this role?"),
)

# Static, sourced hints — general guidance, never a simulation of any
# ATS product and never a vendor claim.
FILE_HINTS: tuple[tuple[str, KitCheckLevel, str, str], ...] = (
    (
        "file_format",
        "info",
        "Send PDF unless the posting asks for another format — "
        "PDF keeps your layout stable in every reader.",
        "guidance",
    ),
    (
        "file_size",
        "info",
        "Keep the attachment small — a one-page PDF is typically well under 1 MB.",
        "guidance",
    ),
    (
        "file_name",
        "info",
        "Name the file with your name and the role so a recruiter can find it later.",
        "guidance",
    ),
)


def _doc_ref(cv: CvDocument) -> KitDocumentRef:
    return KitDocumentRef(
        id=cv.id,
        title=cv.title,
        kind=cv.kind,
        updated_at=cv.updated_at,
        target_posting_id=cv.target_posting_id,
    )


async def _owned_cv(db: AsyncSession, user_id: uuid.UUID, cv_id: uuid.UUID) -> CvDocument | None:
    return (
        (
            await db.execute(
                select(CvDocument).where(CvDocument.id == cv_id, CvDocument.user_id == user_id)
            )
        )
        .scalars()
        .first()
    )


class ApplicationKitService:
    """Builds the posting/application kit read models (no writes)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------ state

    async def _cv_state(self, user_id: uuid.UUID, posting_id: uuid.UUID) -> KitCvState:
        """Resumes newest first (bounded); the posting-scoped variant is
        looked up explicitly so an older tailored CV is never missed by
        the newest-first cap."""
        variant = (
            (
                await self.db.execute(
                    select(CvDocument)
                    .where(
                        CvDocument.user_id == user_id,
                        CvDocument.kind == "resume",
                        CvDocument.target_posting_id == posting_id,
                    )
                    .order_by(CvDocument.updated_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        rows = await self.db.execute(
            select(CvDocument)
            .where(CvDocument.user_id == user_id, CvDocument.kind == "resume")
            .order_by(CvDocument.updated_at.desc())
            .limit(CV_CANDIDATE_CAP)
        )
        resumes = list(rows.scalars().all())
        if variant is not None and variant.id not in {cv.id for cv in resumes}:
            resumes = [variant, *resumes[: CV_CANDIDATE_CAP - 1]]
        return KitCvState(
            needs_cv=not resumes,
            candidates=[_doc_ref(cv) for cv in resumes],
            variant=_doc_ref(variant) if variant is not None else None,
        )

    async def _letter_state(self, user_id: uuid.UUID, posting_id: uuid.UUID) -> KitLetterState:
        """Letters newest first (bounded); the posting-scoped letter is
        looked up explicitly, same as the CV variant."""
        doc = (
            (
                await self.db.execute(
                    select(CvDocument)
                    .where(
                        CvDocument.user_id == user_id,
                        CvDocument.kind == "cover_letter",
                        CvDocument.target_posting_id == posting_id,
                    )
                    .order_by(CvDocument.updated_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        rows = await self.db.execute(
            select(CvDocument)
            .where(CvDocument.user_id == user_id, CvDocument.kind == "cover_letter")
            .order_by(CvDocument.updated_at.desc())
            .limit(CV_CANDIDATE_CAP)
        )
        letters = list(rows.scalars().all())
        if doc is not None and doc.id not in {cv.id for cv in letters}:
            letters = [doc, *letters[: CV_CANDIDATE_CAP - 1]]
        return KitLetterState(
            doc=_doc_ref(doc) if doc is not None else None,
            candidates=[_doc_ref(cv) for cv in letters],
        )

    async def _application(self, user_id: uuid.UUID, posting_id: uuid.UUID) -> Application | None:
        return (
            (
                await self.db.execute(
                    select(Application).where(
                        Application.user_id == user_id,
                        Application.posting_id == posting_id,
                    )
                )
            )
            .scalars()
            .first()
        )

    # -------------------------------------------------------- checklist

    def _posting_checklist(self, posting: JobPosting) -> list[KitChecklistItem]:
        expires = posting.expires_at
        if expires is None:
            return [
                KitChecklistItem(
                    id="posting_open",
                    level="info",
                    label="No closing date stated on the source — check the "
                    "original before applying.",
                    source="posting",
                )
            ]
        expired = expires <= datetime.now(UTC)
        if expired:
            return [
                KitChecklistItem(
                    id="posting_open",
                    level="warn",
                    label="The posting's expiry date has passed — "
                    "check the original before applying.",
                    source="posting",
                )
            ]
        return [
            KitChecklistItem(
                id="posting_open",
                level="pass",
                label=f"Posting is open — source expiry {expires.date().isoformat()}.",
                source="posting",
            )
        ]

    async def _cv_checklist(self, cv: CvDocument | None) -> list[KitChecklistItem]:
        """Page count and contact facts from the existing lint — one
        render, measured when the PDF engine is available."""
        if cv is None:
            return [
                KitChecklistItem(
                    id="cv_missing",
                    level="warn",
                    label="No CV yet — create one in CV Studio to attach to this application.",
                    source="kit",
                )
            ]
        report = await CvExportService(self.db).lint_report(cv)
        items: list[KitChecklistItem] = []
        metrics = report.get("metrics") or {}
        pages = metrics.get("pages_actual")
        page_source = metrics.get("page_count_source")
        max_pages = cv.max_pages
        if pages is None:
            items.append(
                KitChecklistItem(
                    id="cv_pages",
                    level="info",
                    label="Page count not measured yet — export once from CV Studio to measure it.",
                    source="kit",
                )
            )
        else:
            over = bool(metrics.get("pages_actual_over_budget"))
            items.append(
                KitChecklistItem(
                    id="cv_pages",
                    level="warn" if over else "pass",
                    label=f"Measured {pages} page(s) ({page_source}) against a "
                    f"{max_pages}-page budget.",
                    source=str(page_source or "kit"),
                )
            )
        contact_problems = [
            check
            for check in report.get("checks") or []
            if check.get("id") in ("contact_name", "contact_email", "contact_phone")
            and check.get("level") in ("fail", "warn")
        ]
        if contact_problems:
            items.append(
                KitChecklistItem(
                    id="cv_contact",
                    level="warn",
                    label="; ".join(str(check.get("message")) for check in contact_problems),
                    source="lint",
                )
            )
        else:
            items.append(
                KitChecklistItem(
                    id="cv_contact",
                    level="pass",
                    label="Name, email and phone are in the header.",
                    source="lint",
                )
            )
        return items

    async def _answers(
        self, user_id: uuid.UUID, extract: PostingExtractOut | None
    ) -> list[KitAnswerPrompt]:
        from app.models.profile_entities_model import SavedAnswer

        saved_rows = await self.db.execute(
            select(SavedAnswer).where(SavedAnswer.user_id == user_id)
        )
        saved = {row.question_key: row for row in saved_rows.scalars().all()}
        prompts = [
            KitAnswerPrompt(
                key=key,
                prompt=text,
                saved_answer=(saved[key].answer_text if key in saved else None),
                saved_answer_id=(saved[key].id if key in saved else None),
            )
            for key, text in ANSWER_PROMPTS
        ]
        languages = [
            row.code for row in (extract.language_requirements if extract else []) if row.code
        ]
        if languages:
            prompts.append(
                KitAnswerPrompt(
                    key="languages_posting",
                    prompt="The posting mentions these languages: "
                    + ", ".join(languages[:6])
                    + ". Do you meet the level required?",
                    saved_answer=(
                        saved["languages_posting"].answer_text
                        if "languages_posting" in saved
                        else None
                    ),
                    saved_answer_id=(
                        saved["languages_posting"].id if "languages_posting" in saved else None
                    ),
                )
            )
        return prompts[:8]

    # ------------------------------------------------------------ kits

    def _posting_identity(self, posting: JobPosting) -> KitPostingOut:
        return KitPostingOut(
            id=posting.id,
            ref=posting.ref or "",
            title=posting.title,
            org=posting.org or "",
            url=posting.url or "",
            location=PostingLocationOut.model_validate(posting.location or {}),
            posted_at=posting.posted_at,
            expires_at=posting.expires_at,
            employment_type=posting.employment_type,
            seniority=posting.seniority,
            extract_ready=bool(posting.extract),
        )

    async def posting_kit(self, user_id: uuid.UUID, posting: JobPosting) -> PostingKitOut:
        """The pre-application kit for one posting."""
        extract = PostingExtractOut.model_validate(posting.extract) if posting.extract else None
        gap: PostingGapOut | None = None
        if extract is not None:
            gap = await build_posting_gap(self.db, user_id, extract.skills)
        cv_state = await self._cv_state(user_id, posting.id)
        letter_state = await self._letter_state(user_id, posting.id)
        checklist = self._posting_checklist(posting)
        variant_cv_id = cv_state.variant.id if cv_state.variant is not None else None
        target_cv = None
        if variant_cv_id is not None:
            target_cv = await _owned_cv(self.db, user_id, variant_cv_id)
        if target_cv is None and cv_state.candidates:
            target_cv = await _owned_cv(self.db, user_id, cv_state.candidates[0].id)
        checklist.extend(await self._cv_checklist(target_cv))
        checklist.extend(
            KitChecklistItem(id=item_id, level=level, label=label, source=source)
            for item_id, level, label, source in FILE_HINTS
        )
        application = await self._application(user_id, posting.id)
        return PostingKitOut(
            posting=self._posting_identity(posting),
            gap=gap,
            cv=cv_state,
            cover_letter=letter_state,
            answers=await self._answers(user_id, extract),
            checklist=checklist[:10],
            application=(
                KitApplicationState(
                    id=application.id,
                    stage=application.stage,
                    applied_at=application.applied_at,
                    cv_id=application.cv_id,
                    cover_letter_id=application.cover_letter_id,
                )
                if application is not None
                else None
            ),
        )

    async def application_kit(
        self, user_id: uuid.UUID, application_id: uuid.UUID
    ) -> ApplicationKitOut:
        """The kit plus the application timeline and linked documents.

        Ownership rides `ApplicationService.get` (404 on foreign rows —
        never a 403 that confirms someone else's id)."""
        service = ApplicationService(self.db)
        application = await service.get(user_id, application_id)
        posting = await self.db.get(JobPosting, application.posting_id)
        if posting is None:
            raise NotFoundError("Posting not found")
        base = await self.posting_kit(user_id, posting)
        events = (
            (
                await self.db.execute(
                    select(ApplicationEvent)
                    .where(ApplicationEvent.application_id == application_id)
                    .order_by(ApplicationEvent.at.desc(), ApplicationEvent.created_at.desc())
                    .limit(TIMELINE_CAP + 1)
                )
            )
            .scalars()
            .all()
        )
        truncated = len(events) > TIMELINE_CAP
        documents = await self._linked_documents(user_id, application)
        return ApplicationKitOut(
            **base.model_dump(),
            timeline=[ApplicationEventOut.model_validate(event) for event in events[:TIMELINE_CAP]],
            timeline_truncated=truncated,
            documents=documents,
        )

    async def _linked_documents(
        self, user_id: uuid.UUID, application: Application
    ) -> KitLinkedDocuments:
        ids = [doc_id for doc_id in (application.cv_id, application.cover_letter_id) if doc_id]
        refs: dict[uuid.UUID, CvDocument] = {}
        if ids:
            rows = await self.db.execute(
                select(CvDocument).where(CvDocument.user_id == user_id, CvDocument.id.in_(ids))
            )
            refs = {cv.id: cv for cv in rows.scalars().all()}
        cv_row = refs.get(application.cv_id) if application.cv_id else None
        letter_row = refs.get(application.cover_letter_id) if application.cover_letter_id else None
        return KitLinkedDocuments(
            cv=_doc_ref(cv_row) if cv_row is not None else None,
            cover_letter=_doc_ref(letter_row) if letter_row is not None else None,
        )

    # ---------------------------------------------------------- prepare

    async def prepare(self, user_id: uuid.UUID, posting: JobPosting) -> KitPrepareOut:
        """Idempotent deterministic prep — the same output on every run.

        With a CV: the tailor coverage (the same deterministic rows the
        CV Studio tailor table shows) plus the missing-section report.
        Without a CV: `needs_cv` with the CV Studio CTA. Without an
        extract: `extract_ready=false` and no coverage — degraded but
        explicit. Never creates a CV, a letter or an application."""
        extract = PostingExtractOut.model_validate(posting.extract) if posting.extract else None
        cv_state = await self._cv_state(user_id, posting.id)
        letter_state = await self._letter_state(user_id, posting.id)
        target: CvDocument | None = None
        if cv_state.variant is not None:
            target = await _owned_cv(self.db, user_id, cv_state.variant.id)
        elif cv_state.candidates:
            target = await _owned_cv(self.db, user_id, cv_state.candidates[0].id)
        if target is None:
            return KitPrepareOut(
                posting_id=posting.id,
                ref=posting.ref or "",
                needs_cv=True,
                extract_ready=extract is not None,
                cover_letter=letter_state,
            )
        coverage = None
        if extract is not None:
            keys = [skill.skill_key for skill in extract.skills if skill.skill_key]
            levels = await skill_levels(self.db, user_id, keys)
            labels = await skill_labels(self.db, keys)
            evidence = await user_evidence(self.db, user_id, keys)
            coverage = tailor_coverage(extract, levels, labels, evidence)
        suggestions = CvSuggestionService(self.db)
        gaps = await suggestions.section_gap_report(target)
        return KitPrepareOut(
            posting_id=posting.id,
            ref=posting.ref or "",
            needs_cv=False,
            extract_ready=extract is not None,
            cv_id=target.id,
            coverage=coverage,
            section_gaps=gaps,
            cover_letter=letter_state,
        )
