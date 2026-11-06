"""Proposal kind registry: payload schemas + diff vocabulary per kind (plan 123.1)."""

from dataclasses import dataclass
from datetime import timedelta

from pydantic import BaseModel

from app.core.errors import ValidationError
from app.models.enums import ProposalAction, ProposalKind
from app.models.experience_model import ExperienceItem
from app.models.profile_entities_model import (
    Certification,
    EducationItem,
    ProfileAchievement,
)
from app.models.user_model import Profile, UserSkill
from app.schemas.experience import ExperienceItemIn, ExperienceItemUpdate
from app.schemas.profile import (
    AcademicsSection,
    BasicSection,
    ConstraintsSection,
    PreferencesSection,
    WorkPreferencesSection,
)
from app.schemas.profile_entities import (
    CertificationIn,
    CertificationPatch,
    EducationItemIn,
    EducationItemPatch,
    ProfileAchievementIn,
    ProfileAchievementPatch,
)
from app.schemas.profile_proposal import (
    CvChoiceOpPayload,
    ProfileSectionPatchIn,
    UserSkillAddIn,
    UserSkillPatchIn,
)

PROPOSAL_TTL = timedelta(days=14)
# 2000, not 200 (plan 99): the diff must distinguish an anchored edit
# inside a long description — capped-at-200 before/after strings compare
# equal and the change row silently vanishes. TextDiffView folds
# unchanged lines, so the card stays readable.
DIFF_VALUE_CAP = 2000

#: Same-DB clock tolerance for the revert guard (plan 99 AD10): an
#: update bumped ``entity.updated_at`` at most this much after
#: ``resolved_at`` still counts as the apply itself, not a later edit.
#: Pinned by ``test_revert_guard_tolerance``.
_REVERT_TOLERANCE = timedelta(seconds=2)

#: Kinds whose update/delete ops require the target's full content to
#: have been read in the same turn (plan 99.1 read-before-edit gate).
#: ``user_skill`` rows are fully visible in the my_skills digest (a
#: scalar update has no silent-loss surface) and ``cv_synth`` is not an
#: entity edit — both are exempt, as are create ops (nothing to
#: overwrite). The grounding set carries ``read:{kind}:{id-or-section}``
#: keys for every entity whose full content the model has seen.
GROUNDED_KINDS = frozenset(
    {
        ProposalKind.EXPERIENCE_ITEM.value,
        ProposalKind.EDUCATION_ITEM.value,
        ProposalKind.CERTIFICATION.value,
        ProposalKind.PROFILE_ACHIEVEMENT.value,
    }
)
SECTION_NAMES = ("basics", "academics", "work_preferences", "constraints")

#: Entity kinds whose rendered card/CV heading already prints the item's
#: subject (title/program/name) and issuer (org/institution/issuer) —
#: model prose must not restate them. Kind → (subject attr, issuer attr).
_HEADING_ECHO_KINDS: dict[str, tuple[str, str]] = {
    ProposalKind.EXPERIENCE_ITEM.value: ("title", "org_name"),
    ProposalKind.EDUCATION_ITEM.value: ("program", "institution"),
    ProposalKind.CERTIFICATION.value: ("name", "issuer"),
}


#: Per-kind prose fields an anchored ``text_edit`` may target (plan 99.2).
TEXT_FIELDS: dict[str, tuple[str, ...]] = {
    ProposalKind.EXPERIENCE_ITEM.value: ("description",),
    ProposalKind.EDUCATION_ITEM.value: ("description",),
    ProposalKind.PROFILE_ACHIEVEMENT.value: ("detail",),
}


ACTION_VERBS = {
    ProposalAction.CREATE.value: "Add",
    ProposalAction.UPDATE.value: "Update",
    ProposalAction.DELETE.value: "Delete",
}

_SECTION_MODELS: dict[str, type[BaseModel]] = {
    "basics": BasicSection,
    "academics": AcademicsSection,
    "work_preferences": WorkPreferencesSection,
    "preferences": PreferencesSection,
    "constraints": ConstraintsSection,
}


@dataclass(frozen=True)
class KindSpec:
    """Registry entry: payload schemas + diff field vocabulary per kind."""

    label: str
    model: type | None
    create_model: type[BaseModel] | None
    update_model: type[BaseModel] | None
    fields: tuple[tuple[str, str], ...]


KIND_SPECS: dict[str, KindSpec] = {
    ProposalKind.EXPERIENCE_ITEM.value: KindSpec(
        label="experience",
        model=ExperienceItem,
        create_model=ExperienceItemIn,
        update_model=ExperienceItemUpdate,
        fields=(
            ("title", "Title"),
            ("kind", "Type"),
            ("org_name", "Organization"),
            ("start", "Start date"),
            ("end", "End date"),
            ("open_ended", "Open-ended"),
            ("hours_per_week", "Hours per week"),
            ("onsite_policy", "On-site policy"),
            ("status", "Status"),
            ("description", "Description"),
        ),
    ),
    ProposalKind.EDUCATION_ITEM.value: KindSpec(
        label="education",
        model=EducationItem,
        create_model=EducationItemIn,
        update_model=EducationItemPatch,
        fields=(
            ("institution", "Institution"),
            ("program", "Program"),
            ("level", "Level"),
            ("start", "Start date"),
            ("end", "End date"),
            ("in_progress", "In progress"),
            ("description", "Description"),
            ("status", "Status"),
        ),
    ),
    ProposalKind.CERTIFICATION.value: KindSpec(
        label="certification",
        model=Certification,
        create_model=CertificationIn,
        update_model=CertificationPatch,
        fields=(
            ("name", "Name"),
            ("issuer", "Issuer"),
            ("issued", "Issued"),
            ("expires", "Expires"),
            ("credential_id", "Credential ID"),
            ("link", "Link"),
            ("status", "Status"),
        ),
    ),
    ProposalKind.PROFILE_ACHIEVEMENT.value: KindSpec(
        label="achievement",
        model=ProfileAchievement,
        create_model=ProfileAchievementIn,
        update_model=ProfileAchievementPatch,
        fields=(
            ("kind", "Type"),
            ("title", "Title"),
            ("issuer", "Issuer"),
            ("date", "Date"),
            ("detail", "Detail"),
            ("link", "Link"),
        ),
    ),
    ProposalKind.USER_SKILL.value: KindSpec(
        label="skill",
        model=UserSkill,
        create_model=UserSkillAddIn,
        update_model=UserSkillPatchIn,
        fields=(
            ("level", "Level (1-10)"),
            ("derive_enabled", "Derivation enabled"),
        ),
    ),
    ProposalKind.PROFILE_SECTION.value: KindSpec(
        label="profile section",
        model=Profile,
        create_model=None,
        update_model=ProfileSectionPatchIn,
        fields=(),
    ),
    ProposalKind.CV_SYNTH.value: KindSpec(
        label="CV variants",
        model=None,
        create_model=None,
        update_model=None,
        fields=(),
    ),
    ProposalKind.CV_SET_BULLETS.value: KindSpec(
        label="CV bullets",
        model=None,
        create_model=None,
        update_model=None,
        fields=(),
    ),
    ProposalKind.CV_CHOICE.value: KindSpec(
        label="CV options",
        model=None,
        create_model=None,
        update_model=None,
        fields=(),
    ),
    ProposalKind.TOOL_EXECUTION.value: KindSpec(
        label="destructive tool call",
        model=None,
        create_model=None,
        update_model=None,
        fields=(),
    ),
}


def _validate_choice_options(choice_payload: CvChoiceOpPayload) -> None:
    """Creation-time validation of a cv_choice payload (plan 108).

    Multi-hop untrusted input: each option's child payload is dry-run
    against the child kind's own schema HERE; the materialization path
    at approval re-runs the full create() pipeline, so a stale opener
    still resolves per-option with a dropped-reason, never silently.
    """

    for option in choice_payload.options:
        if option.action == ProposalAction.CREATE.value:
            if option.entity_id is not None:
                raise ValidationError("choice create options carry no entity_id")
            child_spec = KIND_SPECS.get(option.kind)
            if child_spec is not None and child_spec.create_model is not None:
                child_spec.create_model.model_validate(option.payload)
        else:
            if option.payload and not option.entity_id:
                raise ValidationError("choice update options need entity_id")
            child_spec = KIND_SPECS.get(option.kind)
            if child_spec is not None and child_spec.update_model is not None:
                child_spec.update_model.model_validate(option.payload)
