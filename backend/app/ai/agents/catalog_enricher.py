"""Catalog enricher: proposes the v2 lifestyle vocabulary for
archetypes that predate it. One audited CATALOG_ENRICH call per job; the
patch covers ONLY the v2 fields — salary bands and education stay
human-owned (moderation applies or rejects; nothing auto-merges)."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.ai.agents.context import context_json, parse_context
from app.ai.gateway import ainvoke_structured, register_mock_fixture
from app.models.enums import AITaskType


class EnrichmentPatch(BaseModel):
    """v2-only proposal; absent = nothing proposed for that field."""

    contract_type: Optional[
        Literal[
            "permanent",
            "temporary",
            "contract",
            "freelance",
            "b2b",
            "internship",
            "apprenticeship",
        ]
    ] = None
    work_hours: Optional[dict] = Field(default=None)
    schedule_cues: list[
        Literal["shift_work", "on_call", "nights", "weekends", "flexible"]
    ] = Field(default_factory=list, max_length=5)
    travel_required: Optional[dict] = Field(default=None)
    benefits_kinds: list[
        Literal[
            "healthcare",
            "pension",
            "leave",
            "remote_budget",
            "learning",
            "equity",
            "meals",
            "transport",
            "other",
        ]
    ] = Field(default_factory=list, max_length=9)
    note: str = Field(default="", max_length=500)

    def non_empty(self) -> bool:
        return bool(
            self.contract_type
            or self.work_hours
            or self.schedule_cues
            or self.travel_required
            or self.benefits_kinds
        )


def _mock_patch(schema: type, user_prompt: str) -> dict:
    """Deterministic v2 cues from the archetype text (offline path)."""
    ctx = parse_context(user_prompt)
    text = " ".join(
        str(part)
        for part in (
            ctx.get("title") or "",
            ctx.get("description") or "",
        )
    ).lower()
    attrs = ctx.get("attributes") or {}
    environments = [str(env) for env in attrs.get("environments") or []]
    work_style = attrs.get("work_style") or {}

    patch: dict = {"note": "Mock enrichment — review before applying."}
    if "intern" in text:
        patch["contract_type"] = "internship"
    elif "freelance" in text:
        patch["contract_type"] = "freelance"
    else:
        patch["contract_type"] = "permanent"
    if "field" in environments or "vehicle" in environments:
        patch["travel_required"] = {"level": "occasional", "days_per_month": None}
    elif "remote" in environments:
        patch["work_hours"] = {
            "pattern": "full_time",
            "hours_per_week_min": 35,
            "hours_per_week_max": 40,
        }
        patch["schedule_cues"] = ["flexible"]
    benefits: list[str] = []
    if int(work_style.get("structure") or 3) <= 2:
        benefits.append("pension")
    if work_style.get("pace") == 3:
        benefits.append("learning")
    if benefits:
        patch["benefits_kinds"] = benefits
    return patch


def compose_system() -> str:
    return (
        "You propose v2 lifestyle attributes for a job-catalog archetype "
        "from its structured attributes and description. Propose ONLY the "
        "v2 fields (contract_type, work_hours, schedule_cues, "
        "travel_required, benefits_kinds) and only what the archetype "
        "realistically implies — never salary, education or any other "
        "human-owned field. Use the note to say what you based it on."
    )


async def propose_enrichment(
    db,
    user_id,
    *,
    title: str,
    description: str,
    attributes: dict,
) -> EnrichmentPatch:
    """One audited CATALOG_ENRICH call."""
    return await ainvoke_structured(
        db,
        AITaskType.CATALOG_ENRICH,
        EnrichmentPatch,
        system=compose_system(),
        user=context_json(
            {
                "title": title,
                "description": (description or "")[:2000],
                "attributes": attributes,
            }
        ),
        user_id=user_id,
    )


register_mock_fixture(AITaskType.CATALOG_ENRICH, _mock_patch)
