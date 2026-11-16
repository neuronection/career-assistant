"""The feature map: extraction feature → consumer, declared
once.

One code-referenced registry binds every PostingExtract field to the
consumers that actually read it — adding a metric later means a registry
entry (38) + a feature-map row + optional formula; the extraction schema
and the AI extraction prompts stay decoupled because the prompt is
GENERATED from this map (rows carrying `prompt_hint`). Unmapped fields
(see `inert`) are still stored in posting_facts and simply do nothing
until they gain a binding. Consumers are a closed vocabulary — a row
binding an unknown consumer is a registry error, not a silent no-op.
"""

from typing import Literal

CONSUMERS: dict[str, str] = {
    "column_write": "Normalize onto a typed job_postings column",
    "facts_write": "Store in posting_facts (auditable, inert storage)",
    "posting_skills_write": "Fill posting_skills levels/priority",
    "fit_gates": " lifestyle gates (flagged, never hidden)",
    "fit_skills_dimension": "Posting-fit skills dimension",
    "prereq_gates": "Posting-fit prereqs dimension",
    "posting_fit_delta": "Posting-fit seniority/other deltas",
    "skill_search": "Skill-level posting search",
}

ConsumerKey = Literal[
    "column_write",
    "facts_write",
    "posting_skills_write",
    "fit_gates",
    "fit_skills_dimension",
    "prereq_gates",
    "posting_fit_delta",
    "skill_search",
]


class FeatureRow:
    """One binding: extract field → consumers (+ prompt contribution)."""

    def __init__(
        self,
        key: str,
        label: str,
        consumers: tuple[str, ...],
        prompt_hint: str = "",
        inert: bool = False,
    ):
        self.key = key
        self.label = label
        self.consumers = consumers
        self.prompt_hint = prompt_hint
        self.inert = inert or not consumers
        for consumer in consumers:
            if consumer not in CONSUMERS:
                raise ValueError(f"Unknown consumer {consumer!r} on {key}")

    @property
    def extracts(self) -> bool:
        """Features with a prompt hint are part of the generated brief."""
        return bool(self.prompt_hint)


FEATURE_MAP: dict[str, FeatureRow] = {
    row.key: row
    for row in (
        FeatureRow(
            "title_norm",
            "Cleaned posting title",
            (),
            prompt_hint=(
                'title_norm: the BARE role title — no "Job Title:" chrome, '
                "no seniority/level qualifiers (those go to `seniority`), no "
                "location, no company name."
            ),
        ),
        FeatureRow(
            "description_clean",
            "Role description with board chrome removed",
            (),
            prompt_hint=(
                "description_clean: the role description with all job-board "
                "chrome removed (premium upsells, applicant counts, recruiter "
                "blocks, company marketing, job alerts) and no section "
                'scaffolding ("Job Title:" / "Job Location:" / "Main '
                'Responsibilities:" headers, location/visa/apply blocks) — '
                "only what describes the role itself, preserving language "
                "and structure."
            ),
        ),
        FeatureRow(
            "catalog_summary",
            "Role summary in the catalog's canonical language",
            (),
            prompt_hint=(
                "catalog_summary: the role distilled to 2-3 self-contained "
                "sentences of plain prose, written in the target language "
                "named in the instructions — no headers, lists or "
                "formatting. Standardizes the catalog-side surface across "
                "postings of any language."
            ),
        ),
        FeatureRow(
            "employment_type",
            "Employment type (fast signal)",
            ("column_write",),
            prompt_hint="employment_type: full_time/part_time/contract/temporary/internship.",
        ),
        FeatureRow(
            "location",
            "Posting location",
            ("column_write",),
            prompt_hint="location: city + country when stated.",
        ),
        FeatureRow(
            "skills",
            "Required skills with level + priority",
            ("posting_skills_write", "fit_skills_dimension", "skill_search"),
            prompt_hint=(
                "skills: every skill mention verbatim as raw_label (the "
                "posting's own wording) with required_level 1-10, priority "
                "and a verbatim evidence_quote; never resolve onto "
                "taxonomy keys — a later pass matches the labels."
            ),
        ),
        FeatureRow(
            "education",
            "Education requirement",
            ("column_write", "prereq_gates"),
            prompt_hint=("education: stated level + field, only when the text says so."),
        ),
        FeatureRow(
            "language_requirements",
            "Spoken-language requirements with level",
            ("facts_write",),
            prompt_hint=(
                "language_requirements: each required spoken language as "
                "an ISO 639-1 two-letter code (en, de, el…) + level "
                "(basic/intermediate/advanced/native) with a verbatim "
                "evidence_quote — only when the posting states the "
                "language and its level cue."
            ),
        ),
        FeatureRow(
            "work_authorization",
            "Work-authorization / sponsorship signal",
            ("facts_write",),
            prompt_hint=(
                "work_authorization: status none (cannot sponsor), sponsors, "
                "case_by_case, or citizens_only + a verbatim evidence_quote; "
                "omit it when the posting does not say."
            ),
        ),
        FeatureRow(
            "grade_requirement",
            "Academic-grade cutoff",
            ("facts_write",),
            prompt_hint=(
                "grade_requirement: scale (uk_honours/gpa_4/gpa_10/de_note/"
                "percentage/other) + the raw numeric value + a verbatim "
                "evidence_quote; never convert between scales."
            ),
        ),
        FeatureRow(
            "opportunity_type",
            "Student opportunity type",
            ("facts_write",),
            prompt_hint=(
                "opportunity_type: internship/placement_year/apprenticeship/"
                "graduate_scheme/insight_programme/part_time/full_time/"
                "contract/unknown when the posting makes the programme type "
                "explicit; distinct from employment_type."
            ),
        ),
        FeatureRow(
            "application_deadline",
            "Explicit application deadline",
            ("facts_write",),
            prompt_hint=(
                "application_deadline: an explicit calendar date only "
                "(YYYY-MM-DD) taken from the posting's own words; omit "
                'relative phrases like "apply by Friday". No separate '
                "evidence_quote field — the date must be stated verbatim."
            ),
        ),
        FeatureRow(
            "prerequisites",
            "Stated prerequisites",
            ("prereq_gates",),
            prompt_hint=(
                "prerequisites: typed requirement rows outside the skill "
                "axis — kind ∈ degree|certificate|license|language|other, "
                "a short label, and the verbatim evidence quote (e.g. "
                '"BSc in Computer Science", "PMP certificate", '
                '"valid driver\'s license"). The education LEVEL itself '
                "still goes to `education`."
            ),
        ),
        FeatureRow(
            "salary",
            "Salary range",
            ("column_write",),
            prompt_hint=(
                "salary: min/max + currency + period when stated; set basis "
                'to "gross" or "net" only when the posting says so '
                '("brutto"/"netto" count) — omit it otherwise.'
            ),
        ),
        FeatureRow(
            "seniority",
            "Seniority band",
            ("column_write", "posting_fit_delta"),
            prompt_hint="seniority: intern..principal.",
        ),
        FeatureRow(
            "responsibilities",
            "Responsibilities with time splits",
            ("facts_write",),
            prompt_hint="responsibilities: with time_pct when stated.",
        ),
        FeatureRow(
            "remote_policy",
            "Remote policy (fast signal)",
            ("column_write",),
            prompt_hint="remote_policy: onsite/hybrid/remote.",
        ),
        FeatureRow(
            "contract_type",
            "Contract type",
            ("facts_write",),
            prompt_hint=(
                "contract_type: permanent/temporary/contract/freelance/b2b/"
                "internship/apprenticeship with evidence_quote."
            ),
        ),
        FeatureRow(
            "work_hours",
            "Work-hours pattern + weekly range",
            ("facts_write", "fit_gates"),
            prompt_hint=(
                "work_hours: full_time/part_time + hours_per_week range with evidence_quote."
            ),
        ),
        FeatureRow(
            "schedule_cues",
            "Schedule signals",
            ("facts_write", "fit_gates"),
            prompt_hint=(
                "schedule_cues: shift_work/on_call/nights/weekends/flexible, "
                "each with its own evidence_quote."
            ),
        ),
        FeatureRow(
            "travel_required",
            "Travel demand",
            ("facts_write", "fit_gates"),
            prompt_hint=(
                "travel_required: none/occasional/frequent + days_per_month "
                "when stated, with evidence_quote."
            ),
        ),
        FeatureRow(
            "onsite_policy",
            "Onsite refinement (office days)",
            ("facts_write",),
            prompt_hint=(
                "onsite_policy: refines remote_policy — office_days_per_week "
                "for hybrid, with evidence_quote."
            ),
        ),
        FeatureRow(
            "benefits",
            "Typed benefits",
            ("facts_write",),
            prompt_hint=(
                "benefits: typed kind (healthcare/pension/leave/remote_budget/"
                "learning/equity/meals/transport/other) + raw wording."
            ),
        ),
        FeatureRow(
            "values_cues",
            "Culture/values wording (informational)",
            ("facts_write",),
            prompt_hint=(
                "values_cues: short culture signals ('fast-paced', "
                "mission-driven') — informational only."
            ),
        ),
    )
}

# Fields the generated prompt must cover: every extractable feature with
# a hint. Prompt and schema cannot drift — a new PostingExtract field
# without a map row simply never reaches the model brief.
PROMPT_FEATURES: tuple[str, ...] = tuple(key for key, row in FEATURE_MAP.items() if row.extracts)


def generated_feature_instructions() -> str:
    """The extraction brief section generated from the map (39.3)."""
    lines = ["FEATURES TO EXTRACT (only these; unsupported ⇒ low confidence):"]
    lines.extend(f"- {key}: {FEATURE_MAP[key].prompt_hint}" for key in PROMPT_FEATURES)
    return "\n".join(lines)


def unmapped_features() -> list[str]:
    """Stored-but-inert features (registry drift alarm for admins)."""
    return sorted(key for key, row in FEATURE_MAP.items() if row.inert)
