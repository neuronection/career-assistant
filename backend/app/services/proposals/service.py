"""HITL profile proposals (plan 77): create → diff → persist → idempotent resolve.

The chatbot proposes, the user resolves. Every apply dispatches to the
same service methods the REST forms use — this module owns only the
proposal lifecycle: payload validation (REST schemas, reused verbatim),
field-diff computation, conflict detection against ``base_updated_at``,
and idempotent resolve. Cards are first-class rows: they survive chat
session deletion and expire after ``PROPOSAL_TTL``.

Plan 123.1 layout: this module keeps the lifecycle core (create /
resolve / queries) and the public class; the registry, anchoring,
diffing, snapshots, apply plumbing, preview and telemetry live in the
sibling ``proposals/*`` modules. ``app.services.profile_proposal_service``
remains the stable import surface (thin facade).
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from app.models.enums import ProposalAction, ProposalKind, ProposalStatus
from app.models.profile_proposal_model import ProfileProposal
from app.schemas.profile_proposal import (
    CvChoiceOpPayload,
    CvChoiceOption,
    CvSetBulletsOpPayload,
    CvSynthOpPayload,
    ProfileSectionPatchIn,
    ToolExecutionPayload,
)
from app.services.proposals.anchors import (
    _strip_entity_heading_echo,
    resolve_cv_set_bullets,
    resolve_cv_synth_payload,
    resolve_ops,
)
from app.services.proposals.diff import (
    _cv_choice_diff,
    _cv_choice_label,
    _edit_summary_rows,
    _jsonish,
)
from app.services.proposals.kinds import (
    _SECTION_MODELS,
    ACTION_VERBS,
    GROUNDED_KINDS,
    KIND_SPECS,
    PROPOSAL_TTL,
    _validate_choice_options,
)
from app.services.proposals.preview import PreviewMixin
from app.services.proposals.snapshots import _full_snapshot

logger = logging.getLogger(__name__)


class ProfileProposalService(PreviewMixin):
    """Proposal lifecycle; apply always dispatches to the form services."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------ create

    async def create(
        self,
        user_id: uuid.UUID,
        *,
        kind: str,
        action: str,
        payload: dict,
        entity_id: uuid.UUID | None = None,
        source: str = "chat",
        origin: dict | None = None,
        edit_ops: dict | None = None,
        chat_session_id: uuid.UUID | None = None,
        chat_message_id: uuid.UUID | None = None,
        ai_generation_id: uuid.UUID | None = None,
    ) -> ProfileProposal:
        """Validate one op against its REST schema and persist the card.

        ``origin`` carries non-chat provenance (MCP token label + request
        id) for the ADR-0015 audit requirement. ``edit_ops`` (plan 99.2)
        carries the raw anchored-edit instructions; they merge into ``payload_json`` after schema
        validation (the REST schema stays clean) for audit, card copy
        and preview highlighting.
        """
        spec = KIND_SPECS.get(kind)
        if spec is None:
            raise ValidationError(f"Unknown proposal kind: {kind}")
        if action not in ACTION_VERBS:
            raise ValidationError(f"Unknown proposal action: {action}")
        if kind == ProposalKind.PROFILE_SECTION.value:
            if action != ProposalAction.UPDATE.value:
                raise ValidationError("Profile sections support update only")
        elif kind == ProposalKind.CV_SYNTH.value:
            if action != ProposalAction.CREATE.value:
                raise ValidationError("CV variant ops support create only")
            if entity_id is not None:
                raise ValidationError("cv_synth ops carry no entity_id")
        elif kind == ProposalKind.CV_SET_BULLETS.value:
            if action != ProposalAction.UPDATE.value:
                raise ValidationError("CV bullet ops support update only")
            if entity_id is not None:
                raise ValidationError("cv_set_bullets ops carry no entity_id")
        elif kind == ProposalKind.CV_CHOICE.value:
            if action != ProposalAction.CREATE.value:
                raise ValidationError("CV choice ops support create only")
            if entity_id is not None:
                raise ValidationError("cv_choice ops carry no entity_id")
        elif kind == ProposalKind.TOOL_EXECUTION.value:
            if action != ProposalAction.CREATE.value:
                raise ValidationError("tool_execution ops support create only")
            if entity_id is not None:
                raise ValidationError("tool_execution ops carry no entity_id")
        elif action == ProposalAction.CREATE.value:
            if entity_id is not None:
                raise ValidationError("create ops carry no entity_id")
        else:
            if entity_id is None:
                raise ValidationError(f"{action} ops require entity_id")
            if action == ProposalAction.DELETE.value:
                payload = {}

        entity: Any = None
        label = ""
        base_updated_at: datetime | None = None
        diff: list[dict] = []
        # Plan 99 AD7: KIND_SPECS-shaped before/after snapshots for the
        # grounded entity kinds — the preview endpoint reads them lazily
        # and revert inverse-applies them. Never diff-capped.
        base_snapshot: dict | None = None
        after_snapshot: dict | None = None

        if kind == ProposalKind.PROFILE_SECTION.value:
            patch = ProfileSectionPatchIn.model_validate(payload)
            section_model = _SECTION_MODELS[patch.section]
            section_model.model_validate(patch.value)
            stored_payload = {
                "section": patch.section,
                "value": patch.value,
            }
            profile = await self._load_profile(user_id)
            base_updated_at = profile.updated_at
            label = patch.section.replace("_", " ")
            diff = self._section_diff(profile, patch.section, patch.value)
        elif kind == ProposalKind.CV_SYNTH.value:
            op_payload = CvSynthOpPayload.model_validate(payload)
            stored_payload = op_payload.model_dump(mode="json")
            # Plan 101 AD1: resolve every ref to a human label ONCE at
            # card creation; the labels live in payload_json (audit +
            # preview reuse) and drive both the title and the diff rows.
            stored_payload.update(await resolve_cv_synth_payload(self.db, user_id, stored_payload))
            label = self._cv_synth_label(stored_payload)
            diff = self._cv_synth_diff(stored_payload)
        elif kind == ProposalKind.CV_SET_BULLETS.value:
            op_payload = CvSetBulletsOpPayload.model_validate(payload)
            stored_payload = op_payload.model_dump(mode="json")
            # Plan 107: ground in server truth ONCE at card creation —
            # the card shows the CURRENT bullets (override ?? snapshot)
            # against the proposal, and revert restores `prior`.
            resolved = await resolve_cv_set_bullets(self.db, user_id, stored_payload)
            base_updated_at = resolved["cv_updated_at"]
            entity_id = op_payload.cv_id
            stored_payload.update(
                {
                    "cv_title": resolved["cv_title"],
                    "item_label": resolved["item_label"],
                    "before": resolved["before"],
                    "prior": resolved["prior"],
                    "prior_variant_id": resolved["prior_variant_id"],
                    "cv_updated_at": resolved["cv_updated_at"].isoformat(),
                }
            )
            # The CV prints title/org as the row heading — strip echoed
            # leads from the proposed bullets (deterministic, same funnel
            # as the CV generator); a bullet that says nothing BEYOND the
            # heading is dropped entirely.
            from app.services.cv.cv_context_service import (
                _heading_echo_lead_only,
                _strip_subject_echo,
            )

            heading_row = resolved["entity_row"]
            cleaned_bullets: list[str] = []
            for bullet in stored_payload.get("bullets") or []:
                text = str(bullet)
                if _heading_echo_lead_only(heading_row, text):
                    continue
                cleaned = _strip_subject_echo(heading_row, text)
                if cleaned.strip():
                    cleaned_bullets.append(cleaned)
            stored_payload["bullets"] = cleaned_bullets
            if not stored_payload["bullets"]:
                raise ValidationError("proposal strips to no bullets")
            label = self._cv_bullets_label(stored_payload)
            diff = self._cv_bullets_diff(stored_payload)
        elif kind == ProposalKind.CV_CHOICE.value:
            choice_payload = CvChoiceOpPayload.model_validate(payload)
            _validate_choice_options(choice_payload)
            stored_payload = choice_payload.model_dump(mode="json")
            label = _cv_choice_label(stored_payload)
            diff = _cv_choice_diff(stored_payload)
        elif kind == ProposalKind.TOOL_EXECUTION.value:
            op_payload = ToolExecutionPayload.model_validate(payload)
            stored_payload = op_payload.model_dump(mode="json")
            label = op_payload.summary or op_payload.tool
            diff = [
                {"field": "tool", "label": "Tool", "after": op_payload.tool},
                *(
                    {
                        "field": name,
                        "label": name.replace("_", " ").title(),
                        "after": value,
                    }
                    for name, value in op_payload.args.items()
                ),
            ]
        elif action == ProposalAction.CREATE.value:
            model = spec.create_model
            assert model is not None
            validated = model.model_validate(payload)
            stored_payload = validated.model_dump(mode="json")
            label = self._create_label(kind, stored_payload)
            diff = self._create_diff(spec, stored_payload)
            after_snapshot = dict(stored_payload)
        else:
            entity, base_updated_at = await self._load_entity(kind, user_id, entity_id)
            label = self._entity_label(kind, entity)
            if action == ProposalAction.DELETE.value:
                stored_payload = {"snapshot": _full_snapshot(kind, entity)}
                after_snapshot = None
                diff = [
                    {
                        "field": field,
                        "label": field_label,
                        "before": _jsonish(value),
                        "after": None,
                    }
                    for field, field_label in spec.fields
                    if (value := getattr(entity, field, None)) not in (None, "", [])
                ]
            else:
                model = spec.update_model
                assert model is not None
                validated = model.model_validate(payload)
                stored_payload = validated.model_dump(mode="json", exclude_unset=True)
                if not stored_payload:
                    raise ValidationError("update payload sets no fields")
                _strip_entity_heading_echo(kind, entity, stored_payload)
                diff = self._update_diff(spec, entity, stored_payload)
                base_snapshot = _full_snapshot(kind, entity)
                after_snapshot = {**base_snapshot, **stored_payload}

        if edit_ops:
            diff = [*diff, *_edit_summary_rows(edit_ops)]
            stored_payload = {**stored_payload, "_edit_ops": edit_ops}

        if kind in GROUNDED_KINDS:
            stored_payload["base_snapshot"] = base_snapshot
            stored_payload["after_snapshot"] = after_snapshot

        if edit_ops:
            stored_payload = {**stored_payload, "_edit_ops": edit_ops}

        proposal = ProfileProposal(
            user_id=user_id,
            kind=kind,
            action=action,
            entity_id=entity_id,
            entity_label=label[:200],
            payload_json=stored_payload,
            base_updated_at=base_updated_at,
            diff_json=diff,
            status=ProposalStatus.PENDING.value,
            source=source,
            origin=dict(origin or {}),
            chat_session_id=chat_session_id,
            chat_message_id=chat_message_id,
            ai_generation_id=ai_generation_id,
        )
        self.db.add(proposal)
        await self.db.commit()
        await self.db.refresh(proposal)
        return proposal

    async def create_from_ops(
        self,
        user_id: uuid.UUID,
        ops: list[dict],
        *,
        grounding: set[str],
        chat_session_id: uuid.UUID | None = None,
        chat_message_id: uuid.UUID | None = None,
        ai_generation_id: uuid.UUID | None = None,
    ) -> tuple[list[ProfileProposal], list[dict]]:
        """Best-effort batch creation: ops fail per-item with a reason.

        ``grounding`` is the plan-99 read-before-edit set —
        ``read:{kind}:{id-or-section}`` keys for every entity whose full
        content the model has seen this turn (or freshly cached). Ops
        editing unread targets are dropped with ``unread_target``, never
        silently applied.
        """
        resolved_ops, dropped = await resolve_ops(self.db, user_id, ops, grounding)
        created: list[ProfileProposal] = []
        for resolved in resolved_ops:
            try:
                created.append(
                    await self.create(
                        user_id,
                        chat_session_id=chat_session_id,
                        chat_message_id=chat_message_id,
                        ai_generation_id=ai_generation_id,
                        **resolved,
                    )
                )
            except (
                DomainError,
                PydanticValidationError,
                ValueError,
                KeyError,
            ) as exc:
                logger.warning(
                    "Profile op dropped (kind=%r action=%r): %s",
                    resolved.get("kind"),
                    resolved.get("action"),
                    str(exc)[:500],
                )
                dropped.append({"op": resolved, "reason": str(exc)})
        return created, dropped

    # ------------------------------------------------------------ queries

    async def list_(
        self,
        user_id: uuid.UUID,
        status: str | None = None,
        limit: int = 50,
    ) -> list[ProfileProposal]:
        query = select(ProfileProposal).where(ProfileProposal.user_id == user_id)
        if status is not None:
            query = query.where(ProfileProposal.status == status)
        query = query.order_by(
            (ProfileProposal.status == ProposalStatus.PENDING.value).desc(),
            ProfileProposal.created_at.desc(),
        ).limit(limit)
        rows = await self.db.execute(query)
        return list(rows.scalars().all())

    async def pending_count(self, user_id: uuid.UUID) -> int:
        rows = await self.db.execute(
            select(ProfileProposal.id).where(
                ProfileProposal.user_id == user_id,
                ProfileProposal.status == ProposalStatus.PENDING.value,
            )
        )
        return len(rows.scalars().all())

    # ------------------------------------------------------------ resolve

    async def approve(
        self,
        user_id: uuid.UUID,
        proposal_id: uuid.UUID,
        option_keys: list[str] | None = None,
    ) -> tuple[ProfileProposal, dict | None, bool]:
        """Apply a pending proposal; idempotent once approved.

        ``cv_choice`` cards (plan 108) fan out: each selected option
        materializes as a standard pending child proposal through the
        normal create() pipeline — the choice card is a picker, not an
        executor, so approving it never writes any entity directly.
        """
        proposal = await self.get(user_id, proposal_id)
        if proposal.status == ProposalStatus.APPROVED.value:
            return proposal, None, True
        if proposal.status != ProposalStatus.PENDING.value:
            raise ValidationError(f"Cannot approve a {proposal.status} proposal")
        if proposal.kind == ProposalKind.CV_CHOICE.value and not option_keys:
            raise ValidationError("select at least one option to proceed")
        if proposal.kind == ProposalKind.CV_CHOICE.value:
            # Pre-terminal client-error validation: wrong keys or bounds
            # reject with a clean validation error and leave the card
            # pending — never burn the terminal-first commit on them.
            choice = CvChoiceOpPayload.model_validate(dict(proposal.payload_json or {}))
            known = {option.key for option in choice.options}
            unknown = [key for key in option_keys if key not in known]
            if unknown:
                raise ValidationError(f"unknown option keys: {', '.join(unknown)}")
            unique = list(dict.fromkeys(option_keys))
            if len(unique) < choice.min_select:
                raise ValidationError(f"select at least {choice.min_select} option(s)")
            if len(unique) > choice.max_select:
                raise ValidationError(f"select at most {choice.max_select} option(s)")
        # cv_synth apply drafts rows in a self-committing service (the
        # audit rule), so the card must reach its terminal state BEFORE
        # the apply — a crash mid-apply leaves an approved card with a
        # resolve_error, never a retryable pending one (a retry would
        # duplicate the whole batch). cv_choice children commit the same
        # way (each create() commits), so the parent terminalizes first.
        terminal_first = proposal.kind in (
            ProposalKind.CV_SYNTH.value,
            ProposalKind.CV_CHOICE.value,
            # A destructive tool execution runs AT MOST once: the card
            # reaches its terminal state BEFORE the handler runs, so a
            # crash mid-apply leaves an approved card with a
            # resolve_error — never a retryable pending card (a retry
            # would re-execute the confirmed call).
            ProposalKind.TOOL_EXECUTION.value,
        )
        if terminal_first:
            proposal.status = ProposalStatus.APPROVED.value
            proposal.resolved_at = datetime.now(UTC)
            await self.db.commit()
        try:
            if proposal.kind == ProposalKind.CV_CHOICE.value:
                applied = await self._materialize_choice(proposal, list(option_keys or []))
            else:
                applied = await self._apply_checked(proposal)
        except ConflictError:
            raise
        except NotFoundError:
            proposal.status = ProposalStatus.EXPIRED.value
            proposal.resolve_error = "Target no longer exists"
            proposal.resolved_at = datetime.now(UTC)
            await self.db.commit()
            raise
        except DomainError as exc:
            proposal.resolve_error = str(exc)[:400]
            await self.db.commit()
            raise
        proposal.status = ProposalStatus.APPROVED.value
        proposal.resolved_at = datetime.now(UTC)
        proposal.resolve_error = ""
        # Create ops link back to the created row only after apply —
        # revert of a create needs the id (plan 99 AD10).
        if (
            proposal.action == ProposalAction.CREATE.value
            and proposal.entity_id is None
            and applied is not None
            and applied.get("kind") == proposal.kind
            and applied.get("id")
        ):
            try:
                proposal.entity_id = uuid.UUID(str(applied["id"]))
            except ValueError:
                logger.warning("create proposal returned a non-UUID id")
        await self.db.commit()
        return proposal, applied, False

    async def _materialize_choice(self, proposal: ProfileProposal, option_keys: list[str]) -> dict:
        """Fan a cv_choice card out into child proposals (plan 108).

        Every selected option re-enters the normal create() pipeline
        (kind-specific validation, server-side grounding, live labels);
        invalid/stale options drop with a reason into the parent's
        payload record. Unknown keys are a hard error (a client bug),
        not a silent skip.
        """
        choice = CvChoiceOpPayload.model_validate(dict(proposal.payload_json or {}))
        known = {option.key: option for option in choice.options}
        unknown = [key for key in option_keys if key not in known]
        if unknown:
            raise ValidationError(f"unknown option keys: {', '.join(unknown)}")
        selected = [known[key] for key in dict.fromkeys(option_keys)]
        if len(selected) < choice.min_select:
            raise ValidationError(f"select at least {choice.min_select} option(s)")
        if len(selected) > choice.max_select:
            raise ValidationError(f"select at most {choice.max_select} option(s)")

        children: list[ProfileProposal] = []
        chosen_pairs: list[tuple[CvChoiceOption, ProfileProposal]] = []
        dropped: list[dict] = []
        for option in selected:
            try:
                child = await self.create(
                    proposal.user_id,
                    kind=option.kind,
                    action=option.action,
                    payload=option.payload,
                    entity_id=option.entity_id,
                    source=proposal.source or "chat",
                    chat_session_id=proposal.chat_session_id,
                    chat_message_id=proposal.chat_message_id,
                    ai_generation_id=proposal.ai_generation_id,
                )
                children.append(child)
                chosen_pairs.append((option, child))
            except (DomainError, PydanticValidationError, ValueError, KeyError) as exc:
                logger.warning(
                    "cv_choice option %r failed to materialize: %s",
                    option.key,
                    str(exc)[:300],
                )
                dropped.append({"key": option.key, "reason": str(exc)[:300]})
        if not children:
            raise DomainError("no selected option could be materialized")

        chose = dict(proposal.payload_json or {})
        chose["_resolved_options"] = {
            "keys": [option.key for option in selected],
            "children": [
                {"key": option.key, "child_id": str(child.id)} for option, child in chosen_pairs
            ],
            "dropped": dropped,
        }
        proposal.payload_json = chose
        return {"children": children, "dropped": dropped}

    async def reject(self, user_id: uuid.UUID, proposal_id: uuid.UUID) -> ProfileProposal:
        """Idempotent reject; applied proposals cannot be un-applied."""
        proposal = await self.get(user_id, proposal_id)
        if proposal.status == ProposalStatus.REJECTED.value:
            return proposal
        if proposal.status != ProposalStatus.PENDING.value:
            raise ValidationError(f"Cannot reject a {proposal.status} proposal")
        proposal.status = ProposalStatus.REJECTED.value
        proposal.resolved_at = datetime.now(UTC)
        await self.db.commit()
        return proposal

    async def sweep_expired(self) -> int:
        """Flip stale pending cards to expired (scheduler-driven)."""
        cutoff = datetime.now(UTC) - PROPOSAL_TTL
        result = await self.db.execute(
            update(ProfileProposal)
            .where(
                ProfileProposal.status == ProposalStatus.PENDING.value,
                ProfileProposal.created_at < cutoff,
            )
            .values(
                status=ProposalStatus.EXPIRED.value,
                resolved_at=datetime.now(UTC),
                resolve_error="Expired",
            )
        )
        await self.db.commit()
        return int(result.rowcount or 0)
