"""Plan 225 S5a: the published reference-banks pack reproduces the app banks.

The pack is the source of truth after S5b; until the code banks and their
seeders are deleted, this suite proves the released bytes reproduce them: the
same counts, the same stored fields, a second apply is a no-op, and a database
already seeded by the code lands on the pack rows without duplicates or
re-created ids.
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
from app.seeds.assessment import BANK_QUESTIONS
from app.seeds.bank_keys import QUESTION_KEYS
from app.seeds.bank_stamp import stamp_bank_identities
from app.seeds.cv_templates import BANK_TEMPLATES
from app.seeds.metrics import (
    CATEGORY_RIASEC,
    DIMENSIONS,
    seed_metric_dimensions,
    seed_metric_templates,
)
from app.seeds.skill_packs import BANK_PACKS
from app.services.seeds.applier import SeedApplyService
from app.services.seeds.banks import template_content_hash
from tests.seed_pack_fixture import BANK_PACK_DIR, apply_bank_pack

MODELS = {
    "assessment_question": AssessmentQuestion,
    "assessment_template": AssessmentTemplate,
    "cv_template": CvTemplate,
    "metric_dimension": MetricDimension,
    "metric_category_anchor": MetricCategoryAnchor,
    "skill_pack": AISkillPack,
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


async def test_the_pack_reproduces_today_s_banks(db, tmp_path):
    await apply_bank_pack(db, tmp_path)
    payloads = pack_payloads()

    assert await _counts(db) == {
        "assessment_question": len(BANK_QUESTIONS),
        "assessment_template": 2,
        "cv_template": len(BANK_TEMPLATES),
        "metric_dimension": len(DIMENSIONS),
        "metric_category_anchor": len(CATEGORY_RIASEC),
        "skill_pack": len(BANK_PACKS),
    }

    question = await db.scalar(
        select(AssessmentQuestion).where(
            AssessmentQuestion.seed_key == "assessment-question:charity-event-role"
        )
    )
    assert question is not None
    source = BANK_QUESTIONS[0]
    assert QUESTION_KEYS[source["prompt"]] == "charity-event-role"
    payload = payloads["assessment-question:charity-event-role"]
    assert question.prompt == source["prompt"]
    assert question.help == source["help"]
    assert question.phase == source["phase"]
    assert question.kind == source["kind"]
    assert question.sort_index == source["sort_index"]
    assert question.audience_stages == source.get("audience_stages", [])
    assert question.time_split == source.get("time_split")
    assert question.options == payload["options"]

    battery = await db.scalar(
        select(AssessmentTemplate).where(
            AssessmentTemplate.seed_key == "assessment-template:riasec-interest-battery/v1"
        )
    )
    assert battery is not None
    payload = payloads["assessment-template:riasec-interest-battery/v1"]
    assert battery.title == "RIASEC interest battery"
    assert battery.version == 1
    assert battery.content == payload["content"]
    assert battery.content_hash == template_content_hash(payload)
    assert len(battery.content["phases"][0]["questions"]) == 6

    cv_template = await db.scalar(
        select(CvTemplate).where(CvTemplate.seed_key == "cv-template:modern-two-column/v4")
    )
    assert cv_template is not None
    source = next(spec for spec in BANK_TEMPLATES if spec["key"] == "modern-two-column")
    payload = payloads["cv-template:modern-two-column/v4"]
    assert cv_template.title == source["title"]
    assert cv_template.description == source["description"]
    assert cv_template.version == source["version"] == 4
    assert cv_template.ats_safe is False
    assert cv_template.content == payload["content"]

    dimension = await db.scalar(
        select(MetricDimension).where(
            MetricDimension.seed_key == "metric-dimension:values.autonomy"
        )
    )
    assert dimension is not None
    source = next(spec for spec in DIMENSIONS if spec["key"] == "values.autonomy")
    assert (dimension.label, dimension.group) == (source["label"], source["group"])
    assert dimension.description == source["description"]
    assert dimension.sources == source["sources"]
    assert dimension.consumers == source["consumers"]

    anchor = await db.scalar(
        select(MetricCategoryAnchor).where(
            MetricCategoryAnchor.seed_key == "interest-category:science"
        )
    )
    assert anchor is not None
    assert anchor.category == "science"
    assert anchor.letter == CATEGORY_RIASEC["science"]

    skill_pack = await db.scalar(
        select(AISkillPack).where(AISkillPack.seed_key == "skill-pack:cover-letter-voice/v1")
    )
    assert skill_pack is not None
    source = next(spec for spec in BANK_PACKS if spec["key"] == "cover-letter-voice")
    assert skill_pack.title == source["title"]
    assert skill_pack.task == source["task"]
    assert skill_pack.instructions == source["instructions"]
    assert skill_pack.status == "draft"


async def test_a_second_apply_is_a_noop(db, tmp_path):
    fixture = await apply_bank_pack(db, tmp_path)
    before = await _ids_by_seed_key(db)
    assert before

    again = await SeedApplyService(db, packs=fixture.store, side_effects=False).apply(
        fixture.source, fixture.version
    )

    assert again.status == "noop", again.as_dict()
    assert await _ids_by_seed_key(db) == before


async def test_the_pack_adopts_a_code_seeded_bank_without_duplicates(db, tmp_path):
    from app.seeds.assessment import seed_assessment_bank
    from app.seeds.cv_templates import seed_cv_template_bank
    from app.seeds.skill_packs import seed_skill_packs

    await seed_assessment_bank(db)
    await seed_cv_template_bank(db)
    await seed_metric_dimensions(db)
    await seed_metric_templates(db)
    await seed_skill_packs(db)
    await stamp_bank_identities(db)
    await db.commit()

    before_ids = await _ids_by_seed_key(db)
    before_counts = await _counts(db)
    assert len(before_ids) == sum(before_counts.values())
    assert before_counts["assessment_question"] == len(BANK_QUESTIONS)
    assert before_counts["metric_category_anchor"] == len(CATEGORY_RIASEC)

    fixture = await apply_bank_pack(db, tmp_path)

    after = await _ids_by_seed_key(db)
    assert after == before_ids
    assert await _counts(db) == before_counts

    again = await SeedApplyService(db, packs=fixture.store, side_effects=False).apply(
        fixture.source, fixture.version
    )
    assert again.status == "noop", again.as_dict()
    assert await _ids_by_seed_key(db) == before_ids
