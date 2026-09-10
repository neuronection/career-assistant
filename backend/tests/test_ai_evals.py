""": golden evals — blessed fixtures run on the mock provider.

Each case fails if (a) its prompt version was bumped without re-blessing
or (b) the mock-engine output stops satisfying the blessed content
assertions. Prompt bumps must land together with a fixture re-bless.
"""

import pytest
from sqlalchemy import select

from app.ai.evals import GOLDEN_CASES, GoldenCase
from app.ai.gateway import ainvoke_structured
from app.ai.prompt_versions import PROMPT_VERSIONS
from app.ai.tasks import TASKS_BY_NAME
from app.models.ai_model import AIGeneration
from app.models.enums import AITaskType


def test_prompt_versions_covers_every_task():
    for task in AITaskType:
        assert task.value in PROMPT_VERSIONS
        assert PROMPT_VERSIONS[task.value] >= 1


def test_golden_cases_pin_known_tasks():
    for case in GOLDEN_CASES:
        assert case.task in TASKS_BY_NAME
        assert case.prompt_version


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c.task)
async def test_golden_case(db, case: GoldenCase):
    assert PROMPT_VERSIONS[case.task] == int(case.prompt_version[1:]), (
        f"prompt for {case.task} was bumped — re-bless the golden fixture "
        "(verify the content assertions still hold, update prompt_version)"
    )
    result = await ainvoke_structured(
        db,
        AITaskType(case.task),
        case.schema,
        system=case.system,
        user=case.user,
    )
    case.check(result)

    row = (
        (
            await db.execute(
                select(AIGeneration)
                .where(AIGeneration.task_type == case.task)
                .order_by(AIGeneration.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    assert row is not None
    assert row.status == "ok"
    assert row.task_tier == TASKS_BY_NAME[case.task].tier
    assert row.prompt_version == case.prompt_version
