"""CV, experience and template vocabularies (plan 123.6 split)."""

from enum import StrEnum


class CvKind(StrEnum):
    """CV record kinds; cover letters land with 34.3."""

    RESUME = "resume"
    COVER_LETTER = "cover_letter"


class CvStatus(StrEnum):
    DRAFT = "draft"
    FINAL = "final"
    ARCHIVED = "archived"


class CvPageSize(StrEnum):
    A4 = "a4"
    LETTER = "letter"


class CvVersionCreator(StrEnum):
    """What produced an immutable cv_versions row."""

    USER_SAVE = "user_save"
    AI_APPLY = "ai_apply"
    EXPORT = "export"
    RESTORE = "restore"
    DUPLICATE = "duplicate"


class CvSynthStatus(StrEnum):
    """Lifecycle of a synthesized CV item (draft-then-approve)."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class CvSynthScope(StrEnum):
    """What a synthesized item replaces."""

    ITEM = "item"
    SUMMARY = "summary"


class CvSynthSource(StrEnum):
    """Who wrote the variant text."""

    AI = "ai"
    MANUAL = "manual"


class CvPageTextSource(StrEnum):
    """Where a source document page's text came from."""

    TEXT_LAYER = "text_layer"
    OCR_VISION = "ocr_vision"
    OCR_TESSERACT = "ocr_tesseract"


class CvTemplateSource(StrEnum):
    """Where a CV template came from."""

    BANK = "bank"
    AI = "ai"
    USER = "user"
    IMPORTED = "imported"
    DUPLICATED = "duplicated"


class CvTemplateVisibility(StrEnum):
    """Visibility ladder; `public` stays unreachable until community
    sharing ships."""

    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class CvTemplateStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class CvOverflowPolicy(StrEnum):
    """What the renderer does when content exceeds the page budget."""

    SHRINK = "shrink"
    TRUNCATE = "truncate"
    WARN = "warn"


class ExperienceKind(StrEnum):
    """Experience item kinds; legacy JSONB `part_time` maps to job."""

    JOB = "job"
    PROJECT = "project"
    INTERNSHIP = "internship"
    VOLUNTEER = "volunteer"
    FREELANCE = "freelance"


class ExperienceItemSource(StrEnum):
    SELF_REPORT = "self_report"
    CV_PARSE = "cv_parse"
    ASSESSMENT = "assessment"
    IMPORT = "import"


class ExperienceItemStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"


class RoleInItem(StrEnum):
    """The skill's role inside one experience item."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    EXPOSURE = "exposure"


class AchievementMetricKind(StrEnum):
    TIME_SAVED = "time_saved"
    SCALE = "scale"
    REVENUE = "revenue"
    QUALITY = "quality"


class TemplateSource(StrEnum):
    """Where a template came from."""

    BANK = "bank"
    AI = "ai"
    USER = "user"
    IMPORTED = "imported"


class TemplateVisibility(StrEnum):
    """Visibility ladder; `public` stays unreachable until community
    sharing ships."""

    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class TemplateStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"
