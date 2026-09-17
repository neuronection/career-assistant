"""Non-callable HITL capability entries for the tools catalog (ADR-0015).

Class-B detached proposals are emitted through the chat reply
(``profile_ops``), not through tool calls — these rows exist so the
"tools the assistant can use" surface tells users the assistant can
*propose* profile edits. Nothing here is executable.
"""

from pydantic import BaseModel

from app.ai.tools.base import AITool, ToolScope


class _NoArguments(BaseModel):
    """Capabilities take no arguments and never execute."""


BUILTIN_CAPABILITIES: list[AITool] = [
    AITool(
        key="propose_profile_edits",
        title="Propose profile edits",
        description=(
            "Ask the assistant in chat to add, update or remove your"
            " experience items, skills, education, certifications or"
            " profile sections. Every edit arrives as a review card you"
            " approve, edit or reject first — nothing is written without"
            " your confirmation."
        ),
        input_model=_NoArguments,
        handler=None,
        scope=ToolScope.WRITE,
        requires_user=True,
        kind="capability",
        hitl=True,
    ),
]
