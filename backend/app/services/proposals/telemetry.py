"""Proposal card serialization + notification fanout (plan 123.1)."""

from app.models.enums import ProposalAction, ProposalKind
from app.models.profile_proposal_model import ProfileProposal
from app.services.proposals.kinds import ACTION_VERBS, KIND_SPECS


def proposal_title(proposal: ProfileProposal) -> str:
    """Card title: "Update experience · Siemens internship"."""
    if proposal.kind == ProposalKind.TOOL_EXECUTION.value:
        tool = str((proposal.payload_json or {}).get("tool") or proposal.entity_label)
        return f"Assistant action · {tool}"
    spec = KIND_SPECS.get(proposal.kind)
    noun = spec.label if spec is not None else proposal.kind
    verb = ACTION_VERBS.get(proposal.action, proposal.action.title())
    return f"{verb} {noun}" + (f" · {proposal.entity_label}" if proposal.entity_label else "")


def proposal_event(proposal: ProfileProposal) -> dict:
    """SSE/metadata card payload — the one serialization shared by the
    chat stream and the list endpoint (never drift between the two)."""
    event = {
        "id": str(proposal.id),
        "kind": proposal.kind,
        "action": proposal.action,
        "status": proposal.status,
        "title": proposal_title(proposal),
        "entity_id": str(proposal.entity_id) if proposal.entity_id else None,
        "entity_label": proposal.entity_label,
        "diff": proposal.diff_json or [],
        "destructive": (
            proposal.action == ProposalAction.DELETE.value
            or proposal.kind == ProposalKind.TOOL_EXECUTION.value
        ),
        "source": proposal.source,
        "origin": dict(proposal.origin or {}),
        "chat_session_id": (str(proposal.chat_session_id) if proposal.chat_session_id else None),
        "created_at": proposal.created_at.isoformat(),
    }
    if proposal.kind == ProposalKind.CV_CHOICE.value:
        # Picker cards render their body from the payload (options);
        # snapshot-backed kinds keep hydrate() as the full-data source.
        event["payload"] = proposal.payload_json or {}
    return event


async def notify_proposals(db, user_id, proposals, session_id) -> None:
    """ADR-0015 fanout: proposal cards outlive the chat window.

    Best-effort — a notification failure never breaks the chat turn.
    Kind-aware copy: destructive-tool confirmations name the tool and
    land on the chat surface, profile edits on the profile inbox."""
    import logging

    logger = logging.getLogger(__name__)
    try:
        from app.services.notification_service import NotificationService

        tool_cards = [p for p in proposals if p.kind == ProposalKind.TOOL_EXECUTION.value]
        if tool_cards and len(tool_cards) == len(proposals):
            plural = "s" if len(proposals) > 1 else ""
            summary = ", ".join(
                str(p.payload_json.get("tool") or p.entity_label) for p in proposals[:3]
            )
            if len(proposals) > 3:
                summary = f"{summary} +{len(proposals) - 3} more"
            await NotificationService(db).emit(
                "profile_proposal",
                [user_id],
                title=f"Destructive tool call{plural} waiting for confirmation",
                body=f"{summary} — nothing ran until you approve",
                payload={
                    "link": "/chat",
                    "proposal_ids": [str(p.id) for p in proposals],
                    "chat_session_id": str(session_id) if session_id else None,
                },
                source_ref={"chat_session_id": str(session_id)} if session_id else None,
                dedup_key=f"profile-proposal:{proposals[0].id}",
            )
            return
        titles = [p.entity_label or p.kind for p in proposals[:3]]
        summary = ", ".join(titles)
        if len(proposals) > 3:
            summary = f"{summary} +{len(proposals) - 3} more"
        plural = "s" if len(proposals) > 1 else ""
        await NotificationService(db).emit(
            "profile_proposal",
            [user_id],
            title=f"Profile edit proposal{plural} waiting for review",
            body=summary,
            payload={
                "link": "/profile",
                "proposal_ids": [str(p.id) for p in proposals],
                "chat_session_id": str(session_id),
            },
            source_ref={"chat_session_id": str(session_id)},
            dedup_key=f"profile-proposal:{proposals[0].id}",
        )
    except Exception:
        logger.warning("profile-proposal notification failed", exc_info=True)


def drop_code(reason: str) -> str:
    """Stable drop-reason token (``unread_target`` …) from a drop message
    — the telemetry bucket for ``profile_op_outcomes``."""
    return str(reason).split(":", 1)[0].strip()[:40]
