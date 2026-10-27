"""Skill/education/stage/path vocabularies (plan 123.6 split)."""

from enum import StrEnum
from typing import ClassVar


class EducationLevel(StrEnum):
    NO_FORMAL = "no_formal"
    MIDDLE_SCHOOL = "middle_school"
    HIGH_SCHOOL = "high_school"
    VOCATIONAL = "vocational"
    BACHELOR = "bachelor"
    MASTER = "master"
    DOCTORATE = "doctorate"


class EducationLevelOrder:
    """Ranking used to compare education requirements with what users have/want."""

    ORDER: ClassVar[dict[EducationLevel, int]] = {
        EducationLevel.NO_FORMAL: 0,
        EducationLevel.MIDDLE_SCHOOL: 1,
        EducationLevel.HIGH_SCHOOL: 2,
        EducationLevel.VOCATIONAL: 3,
        EducationLevel.BACHELOR: 4,
        EducationLevel.MASTER: 5,
        EducationLevel.DOCTORATE: 6,
    }

    @classmethod
    def at_least(cls, level: "EducationLevel", minimum: "EducationLevel") -> bool:
        """Return True when ``level`` meets or exceeds ``minimum``."""
        return cls.ORDER.get(level, 0) >= cls.ORDER.get(minimum, 0)


class SkillStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class SkillOrigin(StrEnum):
    BANK = "bank"
    AI = "ai"
    USER = "user"
    IMPORT = "import"
    CV_PARSE = "cv_parse"


class SkillRelationType(StrEnum):
    """Edge vocabulary for the skill relation graph (plan 138).

    is_a/part_of are directed (specific→general, component→whole);
    synonym/related_to are symmetric and stored canonically ordered.
    """

    IS_A = "is_a"
    SYNONYM = "synonym"
    PART_OF = "part_of"
    RELATED_TO = "related_to"


class SkillRelationStatus(StrEnum):
    """Review state of a skill edge; rejected is the negative edge."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class SkillRelationSource(StrEnum):
    """Who produced a skill edge."""

    LLM = "llm"
    MANUAL = "manual"
    IMPORT = "import"
    DERIVED = "derived"


class JobSkillImportance(StrEnum):
    CORE = "core"
    IMPORTANT = "important"
    BONUS = "bonus"


class UserSkillSource(StrEnum):
    SELF_REPORT = "self_report"
    ASSESSMENT = "assessment"
    EXPERIENCE = "experience"
    AI_INFERRED = "ai_inferred"
    DOCUMENT = "document"


class CareerStage(StrEnum):
    STUDENT = "student"
    EARLY_CAREER = "early_career"
    EXPERIENCED = "experienced"
    SWITCHING = "switching"
    RETURNING = "returning"


class InterestTagKind(StrEnum):
    TOPIC = "topic"
    INDUSTRY = "industry"


class TagSource(StrEnum):
    SELF = "self"
    AI = "ai"
    EXPRESS = "express"


class PathSource(StrEnum):
    SEED = "seed"
    AI = "ai"
    ADMIN = "admin"
    USER = "user"


class PathStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ACTIVE = "active"


class PathFlag(StrEnum):
    """A user's mark on a career path or one of its possibilities."""

    INTERESTED = "interested"
    DISMISSED = "dismissed"
    PINNED = "pinned"
