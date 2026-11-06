"""Lazy before/after preview payloads for proposal cards (plan 99 AD7; plan 123.1)."""

import uuid
from typing import Any, ClassVar

from sqlalchemy import select

from app.core.errors import NotFoundError
from app.models.enums import ProposalAction, ProposalKind
from app.services.proposals.apply import ApplyMixin
from app.services.proposals.kinds import GROUNDED_KINDS, KIND_SPECS
from app.services.proposals.snapshots import _full_snapshot


class PreviewMixin(ApplyMixin):
    """Preview surface (needs ``self.db`` + the apply mixin's loaders)."""

    async def preview(self, user_id: uuid.UUID, proposal_id: uuid.UUID) -> dict:
        """Lazy before/after payloads for the render modal (plan 99 AD7).

        Reads the snapshots persisted at creation — deterministic and
        offline of entity drift. Owner-scoped by ``get``; rows of the
        non-entity kinds and cards created before 99 shipped have no
        snapshots and 404 (the frontend hides the button).

        ``cv_synth`` (plan 101 AD2) previews before-only: the user's own
        KIND_SPECS-shaped snapshots of the referenced sources, fresh at
        preview time; sources deleted since the card degrade to
        label-only rows. The variant output itself does not exist until
        approve drafts it.
        """
        proposal = await self.get(user_id, proposal_id)
        payload = proposal.payload_json or {}
        if proposal.kind == ProposalKind.CV_SYNTH.value:
            resolved_refs = payload.get("resolved_refs")
            if not resolved_refs:
                raise NotFoundError("No preview for this proposal")
            sources = await self._cv_synth_sources(user_id, payload)
            if not sources:
                raise NotFoundError("No preview for this proposal")
            return {
                "before": sources,
                "after": None,
                "edits": {
                    "kind": ProposalKind.CV_SYNTH.value,
                    "action": payload.get("action") or "summarize",
                    "language": payload.get("language") or "en",
                    "resolved_refs": resolved_refs,
                    "posting": payload.get("resolved_posting") or "",
                    "posting_title": payload.get("resolved_posting_title") or "",
                },
            }
        if proposal.kind == ProposalKind.CV_SET_BULLETS.value:
            before = payload.get("before") or []
            bullets = payload.get("bullets") or []
            return {
                "before": [{"text": str(b)} for b in before],
                "after": [{"text": str(b)} for b in bullets],
                "edits": {
                    "kind": ProposalKind.CV_SET_BULLETS.value,
                    "cv_title": payload.get("cv_title") or "",
                    "item_label": payload.get("item_label") or "",
                },
            }
        if proposal.kind not in GROUNDED_KINDS:
            raise NotFoundError("No preview for this proposal")
        if proposal.action == ProposalAction.CREATE.value:
            if "after_snapshot" not in payload:
                raise NotFoundError("No preview for this proposal")
            return {
                "before": None,
                "after": payload["after_snapshot"],
                "edits": payload.get("_edit_ops") or {},
            }
        if proposal.action == ProposalAction.DELETE.value:
            before = payload.get("snapshot")
            if before is None:
                raise NotFoundError("No preview for this proposal")
            return {
                "before": before,
                "after": None,
                "edits": payload.get("_edit_ops") or {},
            }
        if "base_snapshot" not in payload:
            raise NotFoundError("No preview for this proposal")
        return {
            "before": payload["base_snapshot"],
            "after": payload.get("after_snapshot"),
            "edits": payload.get("_edit_ops") or {},
        }

    #: Entity kinds with KIND_SPECS-shaped snapshots available for the
    #: cv_synth preview; every other source key degrades to a label row.
    _CV_SYNTH_SNAPSHOT_KINDS: ClassVar[set[str]] = {
        "experience",
        "projects",
        "volunteer",
        "education",
        "certifications",
        "achievements",
    }

    def _cv_synth_kind_for(self, source_key: str) -> str:
        return {
            "experience": ProposalKind.EXPERIENCE_ITEM.value,
            "projects": ProposalKind.EXPERIENCE_ITEM.value,
            "volunteer": ProposalKind.EXPERIENCE_ITEM.value,
            "education": ProposalKind.EDUCATION_ITEM.value,
            "certifications": ProposalKind.CERTIFICATION.value,
            "achievements": ProposalKind.PROFILE_ACHIEVEMENT.value,
        }.get(source_key, "")

    async def _cv_synth_sources(self, user_id: uuid.UUID, payload: dict) -> list[dict] | None:
        """One stacked before-row per referenced source (plan 101 AD2):
        ref identity + the fresh KIND_SPECS snapshot, label-only when
        the source row is gone; the posting joins as its own row."""
        resolved_refs = payload.get("resolved_refs") or []
        by_key: dict[str, set[str]] = {}
        for ref in resolved_refs:
            source_key = str(ref.get("source_key") or "")
            item_id = str(ref.get("item_id") or "")
            if source_key and item_id:
                by_key.setdefault(source_key, set()).add(item_id)
        labels = {
            f"{ref.get('source_key')}:{ref.get('item_id')}": str(ref.get("label") or "")
            for ref in resolved_refs
        }
        sources: list[dict] = []
        for source_key, item_ids in by_key.items():
            kind = self._cv_synth_kind_for(source_key)
            spec = KIND_SPECS.get(kind)
            for item_id in sorted(item_ids):
                label = labels.get(f"{source_key}:{item_id}") or ""
                entry: dict[str, Any] = {
                    "source_key": source_key,
                    "item_id": item_id,
                    "label": label,
                    "snapshot": None,
                }
                if spec is not None and spec.model is not None:
                    parsed: uuid.UUID | None
                    try:
                        parsed = uuid.UUID(item_id)
                        entity, _ = await self._load_entity(kind, user_id, parsed)
                    except (NotFoundError, ValueError):
                        parsed = None
                        entity = None
                    if entity is not None:
                        entry["snapshot"] = _full_snapshot(kind, entity)
                sources.append(entry)
        posting_id = payload.get("posting_id")
        if posting_id:
            from app.models.posting_model import JobPosting

            try:
                parsed = uuid.UUID(str(posting_id))
            except ValueError:
                parsed = None
            posting = None
            if parsed is not None:
                rows = await self.db.execute(select(JobPosting).where(JobPosting.id == parsed))
                posting = rows.scalars().first()
            if posting is not None:
                sources.append(
                    {
                        "source_key": "posting",
                        "item_id": str(posting.id),
                        "label": str(posting.ref),
                        "snapshot": {
                            "ref": str(posting.ref),
                            "title": str(posting.title),
                            "org": str(posting.org),
                        },
                    }
                )
        if not any(entry["snapshot"] is not None for entry in sources):
            # Plan 101 AD2: all sources gone or unresolvable — the
            # preview has nothing truthful to show.
            return None
        return sources
