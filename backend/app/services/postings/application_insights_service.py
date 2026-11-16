"""Quality coaching from the application pipeline (plan 212 S2.7).

Descriptive math over one user's own applications: tailored vs untailored
response rates, with `n` disclosed and suppression below 10 per group.
No cross-user comparison, no causal claim, no score.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application_model import Application, ApplicationEvent
from app.models.enums import ApplicationStage

SUPPRESS_BELOW = 10
RESPONSE_STAGES = {
    ApplicationStage.SCREENING.value,
    ApplicationStage.INTERVIEW.value,
    ApplicationStage.OFFER.value,
    ApplicationStage.ACCEPTED.value,
    ApplicationStage.REJECTED.value,
}


async def application_insights(db: AsyncSession, user_id: uuid.UUID) -> dict:
    applications = (
        (await db.execute(select(Application).where(Application.user_id == user_id)))
        .scalars()
        .all()
    )
    events = (
        (
            await db.execute(
                select(ApplicationEvent)
                .join(Application, Application.id == ApplicationEvent.application_id)
                .where(Application.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    responded_ids = {event.application_id for event in events if event.stage_to in RESPONSE_STAGES}
    cohorts: dict[str, dict] = {
        "tailored": {"n": 0, "responses": 0},
        "untailored": {"n": 0, "responses": 0},
    }
    for application in applications:
        cohort = (
            "tailored"
            if application.cv_id is not None or application.cover_letter_id is not None
            else "untailored"
        )
        cohorts[cohort]["n"] += 1
        if application.id in responded_ids or application.stage in RESPONSE_STAGES:
            cohorts[cohort]["responses"] += 1

    tailored = cohorts["tailored"]
    untailored = cohorts["untailored"]
    suppressed = tailored["n"] < SUPPRESS_BELOW or untailored["n"] < SUPPRESS_BELOW
    result = {
        "tailored": {
            **tailored,
            "rate": (
                (tailored["responses"] / tailored["n"])
                if tailored["n"] and not suppressed
                else None
            ),
        },
        "untailored": {
            **untailored,
            "rate": (
                (untailored["responses"] / untailored["n"])
                if untailored["n"] and not suppressed
                else None
            ),
        },
        "suppressed": suppressed,
        "floor": SUPPRESS_BELOW,
        "caveat": (
            "Association only: one person's applications, not a controlled study. "
            "No cross-user comparison and no causal claim."
        ),
        "next_action": _next_action(tailored, untailored, suppressed),
    }
    return result


def _next_action(tailored: dict, untailored: dict, suppressed: bool) -> str:
    if suppressed:
        return (
            f"Keep applying: each group needs at least {SUPPRESS_BELOW} applications "
            "before these rates can be shown."
        )
    tailored_rate = tailored["responses"] / tailored["n"]
    untailored_rate = untailored["responses"] / untailored["n"]
    if tailored_rate > untailored_rate:
        return "Tailored applications are associated with more responses here; tailor the next one."
    return "No clear association yet — keep applying and revisit after the next batch."
