"""Plan 225 S5: the published reference-banks pack is the bank source of truth.

The app bundles no bank content after the cutover; this suite pins the
released pack's shape and proves applying it installs every bank, with a
second apply a no-op and the stored rows matching the packed payloads.
"""

from __future__ import annotations

from functools import cache

from sqlalchemy import select

from app.core.seed_pack.export import read_pack_dir
from app.core.seed_pack.manifest import parse_pack
from app.models.assessment_model import AssessmentQuestion
from app.models.assessment_template_model import AssessmentTemplate
from app.models.cv_template_model import CvTemplate
from app.models.metric_model import MetricCategoryAnchor, MetricDimension
from app.models.skill_pack_model import AISkillPack
from app.services.seeds.applier import SeedApplyService
from app.services.seeds.banks import template_content_hash
from tests.seed_pack_fixture import BANK_PACK_DIR, apply_bank_pack, bank_items

MODELS = {
    "assessment_question": AssessmentQuestion,
    "assessment_template": AssessmentTemplate,
    "cv_template": CvTemplate,
    "metric_dimension": MetricDimension,
    "metric_category_anchor": MetricCategoryAnchor,
    "skill_pack": AISkillPack,
}

BANK_COUNTS = {
    "assessment_question": 8,
    "assessment_template": 2,
    "cv_template": 10,
    "metric_dimension": 19,
    "metric_category_anchor": 14,
    "skill_pack": 3,
}

PACK_ITEM_COUNTS = {
    "assessment_questions": 8,
    "assessment_templates": 2,
    "cv_templates": 10,
    "metric_dimensions": 19,
    "metric_category_anchors": 14,
    "skill_packs": 3,
}


@cache
def pack_payloads() -> dict[str, dict]:
    """The pack's parsed item payloads by seed key (the canonical shape)."""
    parsed = parse_pack(read_pack_dir(BANK_PACK_DIR))
    return {item.seed_key: item.payload for item in parsed.items}


async def _rows(db, model) -> list:
    return list((await db.execute(select(model))).scalars().all())


async def _counts(db) -> dict[str, int]:
    return {name: len(await _rows(db, model)) for name, model in MODELS.items()}


async def _ids_by_seed_key(db) -> dict[str, object]:
    ids: dict[str, object] = {}
    for model in MODELS.values():
        for row in await _rows(db, model):
            if row.seed_key is not None:
                ids[row.seed_key] = row.id
    return ids


def test_the_pack_carries_every_bank_item_type():
    assert {name: len(bank_items(name)) for name in PACK_ITEM_COUNTS} == PACK_ITEM_COUNTS
    assert pack_payloads()


async def test_applying_the_pack_installs_every_bank(db, tmp_path):
    await apply_bank_pack(db)

    assert await _counts(db) == BANK_COUNTS

    question = await db.scalar(
        select(AssessmentQuestion).where(
            AssessmentQuestion.seed_key == "assessment-question:charity-event-role"
        )
    )
    assert question is not None
    payload = pack_payloads()["assessment-question:charity-event-role"]
    assert question.prompt == payload["prompt"]
    assert question.help == payload["help"]
    assert question.phase == payload["phase"]
    assert question.kind == payload["kind"]
    assert question.sort_index == payload["sort_index"]
    assert question.audience_stages == payload.get("audience_stages", [])
    assert question.time_split == payload.get("time_split")
    assert question.options == payload["options"]

    battery = await db.scalar(
        select(AssessmentTemplate).where(
            AssessmentTemplate.seed_key == "assessment-template:riasec-interest-battery/v1"
        )
    )
    assert battery is not None
    payload = pack_payloads()["assessment-template:riasec-interest-battery/v1"]
    assert battery.title == "RIASEC interest battery"
    assert battery.version == 1
    assert battery.content == payload["content"]
    assert battery.content_hash == template_content_hash(payload)
    assert len(battery.content["phases"][0]["questions"]) == 6

    cv_template = await db.scalar(
        select(CvTemplate).where(CvTemplate.seed_key == "cv-template:modern-two-column/v4")
    )
    assert cv_template is not None
    payload = pack_payloads()["cv-template:modern-two-column/v4"]
    assert cv_template.title == "Modern Two-Column"
    assert cv_template.version == 4
    assert cv_template.ats_safe is False
    assert cv_template.content == payload["content"]

    dimension = await db.scalar(
        select(MetricDimension).where(
            MetricDimension.seed_key == "metric-dimension:values.autonomy"
        )
    )
    assert dimension is not None
    payload = pack_payloads()["metric-dimension:values.autonomy"]
    assert (dimension.label, dimension.group) == (payload["label"], payload["group"])
    assert dimension.description == payload["description"]
    assert dimension.sources == payload["sources"]
    assert dimension.consumers == payload["consumers"]

    anchor = await db.scalar(
        select(MetricCategoryAnchor).where(
            MetricCategoryAnchor.seed_key == "interest-category:science"
        )
    )
    assert anchor is not None
    assert anchor.category == "science"
    assert anchor.letter == "investigative"

    skill_pack = await db.scalar(
        select(AISkillPack).where(AISkillPack.seed_key == "skill-pack:cover-letter-voice/v1")
    )
    assert skill_pack is not None
    payload = pack_payloads()["skill-pack:cover-letter-voice/v1"]
    assert skill_pack.title == payload["title"]
    assert skill_pack.task == payload["task"]
    assert skill_pack.instructions == payload["instructions"]
    assert skill_pack.status == "draft"


async def test_a_second_apply_is_a_noop(db, tmp_path):
    fixture = await apply_bank_pack(db)
    before = await _ids_by_seed_key(db)
    assert before

    again = await SeedApplyService(db, packs=fixture.store, side_effects=False).apply(
        fixture.source, fixture.version
    )

    assert again.status == "noop", again.as_dict()
    assert await _ids_by_seed_key(db) == before
