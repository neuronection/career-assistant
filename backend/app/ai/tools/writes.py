"""MCP write tools (plan 119.4): opt-in, proposal-backed.

Every tool here is a registry entry, so chat and MCP share one surface.
Nothing mutates user data directly:

* ``profile_update`` emits a real ADR-0015 Class-B proposal (the same
  Tier-2 card the profile pipeline renders, with its server-computed
  diff) and returns only the card reference.
* ``application_transition`` and ``cv_ops`` are destructive registry
  tools: the registry funnel turns every call into a ``tool_execution``
  card, and their handlers run exactly once through that card's approve
  path — through the same application/CV services as REST.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.ai.tools.base import AITool, ToolContext, ToolRiskClass, ToolScope


class ProfileUpdateInput(BaseModel):
    """One profile mutation, expressed in the REST/proposal vocabulary."""

    kind: Literal[
        "experience_item",
        "education_item",
        "certification",
        "profile_achievement",
        "user_skill",
        "profile_section",
    ]
    action: Literal["create", "update", "delete"]
    entity_id: str | None = Field(default=None, max_length=64)
    payload: dict = Field(default_factory=dict)


class ApplicationTransitionInput(BaseModel):
    """Move one application's stage and/or append one timeline note."""

    application_id: str = Field(min_length=8, max_length=64)
    stage: (
        Literal["applied", "screening", "interview", "offer", "accepted", "rejected", "withdrawn"]
        | None
    ) = None
    note: str = Field(default="", max_length=4000)


class CvOpsInput(BaseModel):
    """Two proposal-backed CV operations: bullet rewrite and template."""

    cv_id: str = Field(min_length=8, max_length=64)
    op: Literal["set_bullets", "set_template"]
    source_key: Literal["experience", "projects", "volunteer"] | None = None
    item_id: str | None = Field(default=None, max_length=64)
    bullets: list[str] | None = Field(default=None, max_length=12)
    template_id: str | None = Field(default=None, max_length=64)


async def _profile_update(db, ctx: ToolContext, args: ProfileUpdateInput):
    """Emit the Class-B profile card; no user data is written here."""
    import uuid as uuid_mod

    from app.core.errors import ValidationError
    from app.models.enums import ProposalAction
    from app.services.profile_proposal_service import (
        ProfileProposalService,
        notify_proposals,
    )

    assert ctx.user_id is not None, "profile_update requires a user"
    entity_id = None
    if args.entity_id:
        try:
            entity_id = uuid_mod.UUID(args.entity_id)
        except ValueError as exc:
            raise ValidationError("entity_id must be a UUID") from exc
    if args.action != ProposalAction.CREATE.value and entity_id is None:
        raise ValidationError(f"{args.action} ops require entity_id")
    proposal = await ProfileProposalService(db).create(
        ctx.user_id,
        kind=args.kind,
        action=args.action,
        payload=dict(args.payload or {}),
        entity_id=entity_id,
        source=ctx.source,
        origin=dict(ctx.origin or {}),
    )
    await notify_proposals(db, ctx.user_id, [proposal], None)
    return {
        "status": "awaiting_approval",
        "proposal_id": str(proposal.id),
        "kind": proposal.kind,
        "title": proposal.entity_label or proposal.kind,
        "detail": (
            "Nothing was written. This change is an approval card; it applies "
            "only if the user approves it."
        ),
    }


async def _application_transition(db, ctx: ToolContext, args: ApplicationTransitionInput):
    """Apply one stage move / note (executes only through its card)."""
    import uuid as uuid_mod

    from app.core.errors import ValidationError
    from app.models.enums import ApplicationActor
    from app.services.postings.applications_service import ApplicationService

    assert ctx.user_id is not None, "application_transition requires a user"
    if args.stage is None and not args.note.strip():
        raise ValidationError("application_transition needs a stage or a note")
    service = ApplicationService(db)
    application_id = uuid_mod.UUID(args.application_id)
    result: dict = {"application_id": str(application_id)}
    if args.stage is not None:
        application = await service.transition(
            ctx.user_id,
            application_id,
            to_stage=args.stage,
            actor=ApplicationActor.ASSISTANT,
            body=args.note,
        )
        result["stage"] = application.stage
    if args.note.strip():
        event = await service.add_note(
            ctx.user_id,
            application_id,
            args.note,
            actor=ApplicationActor.ASSISTANT,
        )
        result["event_id"] = str(event.id)
    return result


async def _cv_ops(db, ctx: ToolContext, args: CvOpsInput):
    """Apply one CV operation (executes only through its card)."""
    from app.ai.tools.cv_builder import SetBulletsInput, SetTemplateInput
    from app.ai.tools.registry import get_tool
    from app.core.errors import ValidationError

    if args.op == "set_bullets":
        if args.source_key is None or args.item_id is None or args.bullets is None:
            raise ValidationError("set_bullets needs source_key, item_id and bullets")
        tool = get_tool("cv_set_bullets")
        handler = tool.handler
        assert handler is not None
        return await handler(
            db,
            ctx,
            SetBulletsInput(
                cv_id=args.cv_id,
                source_key=args.source_key,
                item_id=args.item_id,
                bullets=args.bullets,
            ),
        )
    if args.template_id is None:
        raise ValidationError("set_template needs template_id")
    tool = get_tool("cv_set_template")
    handler = tool.handler
    assert handler is not None
    return await handler(db, ctx, SetTemplateInput(cv_id=args.cv_id, template_id=args.template_id))


WRITE_TOOLS: list[AITool] = [
    AITool(
        key="profile_update",
        title="Propose a profile change",
        description=(
            "Propose ONE profile mutation (experience, education,"
            " certification, achievement, skill or section) as an approval"
            " card. entity_id is required for update/delete. Nothing is"
            " written until the user approves the card."
        ),
        input_model=ProfileUpdateInput,
        handler=_profile_update,
        scope=ToolScope.WRITE,
        risk_class=ToolRiskClass.STATE_CHANGING,
        cost_hint="cheap",
        requires_user=True,
        hitl=True,
    ),
    AITool(
        key="application_transition",
        title="Move an application or add a note",
        description=(
            "Move ONE application's stage and/or append a timeline note. The"
            " user must approve a confirmation card before anything runs."
        ),
        input_model=ApplicationTransitionInput,
        handler=_application_transition,
        scope=ToolScope.WRITE,
        risk_class=ToolRiskClass.DESTRUCTIVE,
        cost_hint="cheap",
        requires_user=True,
    ),
    AITool(
        key="cv_ops",
        title="Change a CV",
        description=(
            "Rewrite one item's bullets (set_bullets) or switch the CV's"
            " template (set_template). The user must approve a confirmation"
            " card before anything runs."
        ),
        input_model=CvOpsInput,
        handler=_cv_ops,
        scope=ToolScope.WRITE,
        risk_class=ToolRiskClass.DESTRUCTIVE,
        cost_hint="cheap",
        requires_user=True,
    ),
]
