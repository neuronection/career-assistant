"""CV intake service: parse → draft → review-first apply.

The AI draft lands in `cv_parse_drafts` and touches nothing else. Apply
writes only user-confirmed selections, using the app's canonical shapes
(40 experience items, 21 skills via the taxonomy lifecycle, 48 entities,
profile section merges) with full provenance — every applied row cites
the source document and evidence quote. Re-intake dedupes on
(org, title, start) so refreshing a CV never duplicates history.
"""

import re
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.cv_intake_model import CvParseDraft
from app.models.document_model import Document
from app.models.experience_model import (
    ExperienceAchievement,
    ExperienceItem,
    ExperienceSkill,
    Organization,
    SkillEvidence,
)
from app.models.profile_entities_model import (
    Certification,
    EducationItem,
    ProfileAchievement,
)
from app.models.taxonomy_model import InterestTag, Skill
from app.models.user_model import Profile, UserInterest, UserSkill
from app.models.enums import (
    ExperienceItemSource,
    ExperienceItemStatus,
    RoleInItem,
    SkillOrigin,
    TagSource,
    UserSkillSource,
)
from app.schemas.cv_extract import CvExtract
from app.services.cv_source_service import cv_extraction_of


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug[:78] or f"skill-{uuid.uuid4().hex[:8]}"


def _parse_date(raw: str) -> date | None:
    text = str(raw or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}", text):
        return date(int(text[:4]), int(text[5:7]), 1)
    if re.fullmatch(r"\d{4}", text):
        return date(int(text), 1, 1)
    return None


LEVEL_ORDER = {"basic": 0, "intermediate": 1, "advanced": 2, "native": 3}


class CvIntakeService:
    """Parse-to-draft and review-first apply for one CV document."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _owned_document(
        self, document_id: uuid.UUID, user_id: uuid.UUID
    ) -> Document:
        rows = await self.db.execute(
            select(Document).where(
                Document.id == document_id, Document.user_id == user_id
            )
        )
        document = rows.scalars().first()
        if document is None:
            raise NotFoundError("Document not found")
        return document

    # ------------------------------------------------------------ parse

    async def parse_to_draft(
        self, document_id: uuid.UUID, user_id: uuid.UUID
    ) -> CvParseDraft:
        """Run the CV_PARSE agent over the extraction text → review draft."""
        from app.ai.agents.cv_parser import parse_cv

        document = await self._owned_document(document_id, user_id)
        if document.kind != "cv":
            raise ValidationError("Not a CV document")
        extraction = cv_extraction_of(document)
        if extraction is None or not extraction.full_text.strip():
            raise ValidationError("Document has no extracted text yet")
        rows = await self.db.execute(
            select(CvParseDraft).where(CvParseDraft.document_id == document.id)
        )
        existing = rows.scalars().first()
        extract = await parse_cv(self.db, user_id, extraction.full_text)
        if existing is not None:
            existing.payload = extract.model_dump(mode="json")
            existing.status = "pending"
            existing.report = {}
            draft = existing
        else:
            draft = CvParseDraft(
                document_id=document.id,
                user_id=user_id,
                status="pending",
                payload=extract.model_dump(mode="json"),
            )
            self.db.add(draft)
        await self.db.commit()
        await self.db.refresh(draft)
        return draft

    async def get_draft(
        self, document_id: uuid.UUID, user_id: uuid.UUID
    ) -> CvParseDraft:
        """The live draft of a document (review screen payload)."""
        await self._owned_document(document_id, user_id)
        rows = await self.db.execute(
            select(CvParseDraft).where(CvParseDraft.document_id == document_id)
        )
        draft = rows.scalars().first()
        if draft is None:
            raise NotFoundError("No draft for this document")
        return draft

    @staticmethod
    def section_count(payload: dict) -> int:
        """Non-empty applicable sections of a draft payload.

        Zero means the extraction found nothing usable — the history UI
        offers re-processing instead of a doomed review.
        """
        basics = payload.get("basics") or {}
        count = 0
        if any(
            basics.get(field)
            for field in ("full_name", "headline", "email", "phone", "location")
        ):
            count += 1
        for section in (
            "education",
            "experience",
            "skills",
            "languages",
            "certifications",
            "awards",
            "interests",
        ):
            if payload.get(section):
                count += 1
        return count

    async def list_drafts(self, user_id: uuid.UUID) -> list[dict]:
        """Every CV draft of the user with its source document.

        The import-history view: newest first, report included so applied
        drafts can show what they created. Documents are joined, not
        queried per row.
        """
        rows = await self.db.execute(
            select(CvParseDraft, Document)
            .join(Document, CvParseDraft.document_id == Document.id)
            .where(CvParseDraft.user_id == user_id)
            .order_by(CvParseDraft.updated_at.desc())
        )
        return [
            {
                "document_id": str(draft.document_id),
                "status": draft.status,
                "updated_at": draft.updated_at,
                "section_count": self.section_count(draft.payload or {}),
                "report": draft.report or {},
                "document": {
                    "id": str(doc.id),
                    "filename": doc.filename,
                    "mime": doc.mime,
                    "size_bytes": doc.size_bytes,
                    "page_count": doc.page_count,
                    "status": doc.status,
                    "error": doc.error,
                    "created_at": doc.created_at,
                },
            }
            for draft, doc in rows.all()
        ]

    async def discard(self, document_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Discard the draft; nothing was ever written to the profile."""
        draft = await self.get_draft(document_id, user_id)
        draft.status = "discarded"
        await self.db.commit()

    # ------------------------------------------------------------ apply

    async def apply(
        self, document_id: uuid.UUID, user_id: uuid.UUID, selections: dict
    ) -> dict:
        """Apply user-confirmed selections; everything else stays draft-free.

        selections maps a CvExtract section to either `true` (all items)
        or a list of indices. Missing sections are not applied (partial
        applies are the norm). Returns a report with created counts,
        proposed skills, conflicts, unmapped items and duplicates.
        """
        await self._owned_document(document_id, user_id)
        draft = await self.get_draft(document_id, user_id)
        if draft.status == "discarded":
            raise ValidationError("Draft was discarded")
        extract = CvExtract.model_validate(draft.payload)
        document_id_str = str(document_id)

        report: dict = {
            "created": {},
            "proposed_skills": [],
            "skill_conflicts": [],
            "unmapped_interests": [],
            "duplicates": [],
        }

        if self._selected(selections, "basics"):
            await self._apply_basics(user_id, extract.basics.model_dump())

        if self._selected(selections, "education"):
            for index in self._indices(selections, "education", len(extract.education)):
                item = extract.education[index]
                created = await self._create_education(user_id, item.model_dump())
                report["created"]["education_items"] = report["created"].get(
                    "education_items", 0
                ) + int(created)

        if self._selected(selections, "experience"):
            for index in self._indices(
                selections, "experience", len(extract.experience)
            ):
                item = extract.experience[index]
                created = await self._create_experience(
                    user_id, document_id_str, item.model_dump(), report
                )
                report["created"]["experience_items"] = report["created"].get(
                    "experience_items", 0
                ) + int(created)

        if self._selected(selections, "skills"):
            for index in self._indices(selections, "skills", len(extract.skills)):
                skill = extract.skills[index]
                await self._apply_skill(
                    user_id,
                    document_id_str,
                    skill.name,
                    skill.level_claim,
                    skill.evidence.quote,
                    report,
                )

        if self._selected(selections, "languages"):
            await self._apply_languages(user_id, extract)

        if self._selected(selections, "certifications"):
            for index in self._indices(
                selections, "certifications", len(extract.certifications)
            ):
                item = extract.certifications[index]
                self.db.add(
                    Certification(
                        user_id=user_id,
                        name=item.name,
                        issuer=item.issuer,
                        issued=_parse_date(item.issued),
                        credential_id=item.credential_id,
                        source=ExperienceItemSource.CV_PARSE.value,
                        status="draft",
                    )
                )
                report["created"]["certifications"] = (
                    report["created"].get("certifications", 0) + 1
                )

        if self._selected(selections, "awards"):
            for index in self._indices(selections, "awards", len(extract.awards)):
                item = extract.awards[index]
                self.db.add(
                    ProfileAchievement(
                        user_id=user_id,
                        kind=item.kind,
                        title=item.title,
                        issuer=item.issuer,
                        date=_parse_date(item.date),
                        source=ExperienceItemSource.CV_PARSE.value,
                        status="draft",
                    )
                )
                report["created"]["profile_achievements"] = (
                    report["created"].get("profile_achievements", 0) + 1
                )

        if self._selected(selections, "interests"):
            await self._apply_interests(user_id, extract, report)

        draft.status = "applied"
        merged = dict(draft.report or {})
        merged.update(report)
        draft.report = merged
        await self.db.commit()
        return report

    # ------------------------------------------------------- selection

    @staticmethod
    def _selected(selections: dict, section: str) -> bool:
        return bool(selections.get(section))

    @staticmethod
    def _indices(selections: dict, section: str, total: int) -> list[int]:
        value = selections.get(section)
        if value is True:
            return list(range(total))
        if isinstance(value, list):
            return [i for i in value if isinstance(i, int) and 0 <= i < total]
        return []

    # ---------------------------------------------------------- appliers

    async def _apply_basics(self, user_id: uuid.UUID, basics: dict) -> None:
        rows = await self.db.execute(select(Profile).where(Profile.user_id == user_id))
        profile = rows.scalars().first()
        if profile is None:
            profile = Profile(user_id=user_id, basics={})
            self.db.add(profile)
            await self.db.flush()
        data = dict(profile.basics or {})
        for field in ("email", "phone", "headline"):
            if basics.get(field):
                data[field] = basics[field]
        if basics.get("location"):
            data["city"] = basics["location"][:80]
        links = basics.get("links") or []
        if links:
            existing_urls = {lnk.get("url") for lnk in data.get("links", [])}
            merged = list(data.get("links") or [])
            for link in links:
                if link.get("url") and link["url"] not in existing_urls:
                    merged.append(
                        {
                            "kind": link.get("kind", "other"),
                            "url": link["url"],
                            "label": link.get("label", ""),
                        }
                    )
            data["links"] = merged[:8]
        profile.basics = data

    async def _resolve_org(self, name: str) -> Organization | None:
        if not name.strip():
            return None
        rows = await self.db.execute(
            select(Organization)
            .where(func.lower(Organization.name) == name.strip().lower())
            .limit(1)
        )
        org = rows.scalars().first()
        if org is not None:
            return org
        org = Organization(
            key=_slug(name),
            name=name.strip()[:200],
            status="proposed",
            provenance={"source": "cv_parse"},
        )
        self.db.add(org)
        await self.db.flush()
        return org

    async def _create_experience(
        self, user_id: uuid.UUID, document_id: str, item: dict, report: dict
    ) -> bool:
        """Create one draft experience item; dedupe on (org, title, start)."""
        org_name = str(item.get("org") or "")
        title = str(item.get("title") or "")
        start = _parse_date(item.get("start") or "")
        dup_condition = [
            ExperienceItem.user_id == user_id,
            func.lower(ExperienceItem.title) == title.lower(),
        ]
        if org_name:
            dup_condition.append(
                func.lower(ExperienceItem.org_name) == org_name.lower()
            )
        if start is not None:
            dup_condition.append(ExperienceItem.start == start)
        rows = await self.db.execute(select(ExperienceItem).where(*dup_condition))
        if rows.scalars().first() is not None:
            report["duplicates"].append(f"{title} @ {org_name or '?'}")
            return False
        org = await self._resolve_org(org_name)
        experience = ExperienceItem(
            user_id=user_id,
            kind=item.get("kind") or "job",
            title=title[:160],
            org_id=org.id if org else None,
            org_name=org_name[:200],
            start=start or date(2000, 1, 1),
            end=_parse_date(item.get("end") or ""),
            open_ended=str(item.get("end") or "").lower() in ("", "present"),
            description=str(item.get("description") or "")[:4000],
            source=ExperienceItemSource.CV_PARSE.value,
            status=ExperienceItemStatus.DRAFT.value,
        )
        self.db.add(experience)
        await self.db.flush()

        for achievement in item.get("achievements") or []:
            metric = achievement.get("metric")
            self.db.add(
                ExperienceAchievement(
                    experience_id=experience.id,
                    text=str(achievement.get("text") or "")[:500],
                    metric=metric or None,
                )
            )

        for skill in item.get("skills") or []:
            resolved = await self._resolve_skill(str(skill.get("name") or ""), report)
            if resolved is None:
                continue
            self.db.add(
                ExperienceSkill(
                    experience_id=experience.id,
                    skill_id=resolved.id,
                    role_in_item=RoleInItem.PRIMARY.value,
                )
            )
        return True

    async def _resolve_skill(self, name: str, report: dict) -> Skill | None:
        """Find-or-propose a taxonomy skill."""
        if not name.strip():
            return None
        key = _slug(name)
        rows = await self.db.execute(
            select(Skill)
            .where(
                or_(Skill.key == key, func.lower(Skill.label) == name.strip().lower())
            )
            .limit(1)
        )
        skill = rows.scalars().first()
        if skill is not None:
            return skill
        skill = Skill(
            key=key,
            label=name.strip()[:120],
            category="general",
            status="proposed",
            origin=SkillOrigin.CV_PARSE.value,
            provenance={"source": "cv_parse"},
        )
        self.db.add(skill)
        await self.db.flush()
        report["proposed_skills"].append(key)
        return skill

    async def _apply_skill(
        self,
        user_id: uuid.UUID,
        document_id: str,
        name: str,
        level_claim: int | None,
        quote: str,
        report: dict,
    ) -> None:
        """Upsert user_skills (source=document) + one evidence ledger row."""
        skill = await self._resolve_skill(name, report)
        if skill is None:
            return
        rows = await self.db.execute(
            select(UserSkill).where(
                UserSkill.user_id == user_id, UserSkill.skill_id == skill.id
            )
        )
        user_skill = rows.scalars().first()
        if user_skill is None:
            user_skill = UserSkill(
                user_id=user_id,
                skill_id=skill.id,
                level=level_claim or 1,
                source=UserSkillSource.DOCUMENT.value,
                confidence=0.8 if level_claim else 0.5,
            )
            self.db.add(user_skill)
            report["created"]["skills"] = report["created"].get("skills", 0) + 1
        elif level_claim and user_skill.level != level_claim:
            report["skill_conflicts"].append(
                f"{skill.key}: kept {user_skill.level}, CV claims {level_claim}"
            )
        self.db.add(
            SkillEvidence(
                user_id=user_id,
                skill_id=skill.id,
                cv_document_id=uuid.UUID(document_id),
                note=(quote or "claimed in CV")[:500],
                level_value=level_claim or user_skill.level,
                confidence=0.8 if level_claim else 0.5,
                claimed_at=datetime.now(timezone.utc),
            )
        )

    async def _create_education(self, user_id: uuid.UUID, item: dict) -> bool:
        rows = await self.db.execute(
            select(EducationItem).where(
                EducationItem.user_id == user_id,
                func.lower(EducationItem.institution)
                == str(item.get("institution", "")).lower(),
                func.lower(EducationItem.program)
                == str(item.get("program", "")).lower(),
            )
        )
        if rows.scalars().first() is not None:
            return False
        self.db.add(
            EducationItem(
                user_id=user_id,
                institution=str(item.get("institution") or "")[:200],
                org_name=str(item.get("institution") or "")[:200],
                program=str(item.get("program") or "")[:200],
                level=str(item.get("level") or "high_school")[:30],
                start=_parse_date(item.get("start") or ""),
                end=_parse_date(item.get("end") or ""),
                in_progress=not item.get("end"),
                grade_band=item.get("grade_band"),
                source=ExperienceItemSource.CV_PARSE.value,
                status="draft",
            )
        )
        return True

    async def _apply_languages(self, user_id: uuid.UUID, extract: CvExtract) -> None:
        rows = await self.db.execute(select(Profile).where(Profile.user_id == user_id))
        profile = rows.scalars().first()
        if profile is None:
            profile = Profile(user_id=user_id, basics={})
            self.db.add(profile)
            await self.db.flush()
        academics = dict(profile.academics or {})
        languages = list(academics.get("languages") or [])
        existing = {lang.get("code") for lang in languages}
        for extracted in extract.languages:
            if extracted.code not in existing:
                languages.append({"code": extracted.code, "level": extracted.level})
        academics["languages"] = languages[:10]
        profile.academics = academics

    async def _apply_interests(
        self, user_id: uuid.UUID, extract: CvExtract, report: dict
    ) -> None:
        """Map extracted interest labels onto taxonomy tags (user_interests)."""
        known = (await self.db.execute(select(InterestTag))).scalars().all()
        by_key = {tag.key.lower(): tag for tag in known}
        by_label = {tag.label.lower(): tag for tag in known}
        rows = await self.db.execute(
            select(UserInterest.interest_tag_id).where(UserInterest.user_id == user_id)
        )
        existing_ids = {row[0] for row in rows.all()}
        for extracted in extract.interests:
            label = extracted.label.strip().lower()
            tag = by_key.get(label) or by_label.get(label)
            if tag is None:
                report["unmapped_interests"].append(extracted.label)
                continue
            if tag.id in existing_ids:
                continue
            self.db.add(
                UserInterest(
                    user_id=user_id,
                    interest_tag_id=tag.id,
                    weight=3,
                    source=TagSource.AI.value,
                    evidence={"source_document": "cv_parse"},
                )
            )
            existing_ids.add(tag.id)
