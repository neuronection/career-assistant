import { pickLanguages } from "@neuronection/assistant-ui/languages";
import type { EducationLevel, PhysicalActivity, Profile } from "@/types";

export const STAGE_OPTIONS = [
  { value: "student", labelKey: "profile.options.i_m_a_student" },
  { value: "early_career", labelKey: "profile.options.early_in_my_career" },
  { value: "experienced", labelKey: "profile.options.experienced_professional" },
  { value: "switching", labelKey: "profile.options.switching_fields" },
  { value: "returning", labelKey: "profile.options.returning_after_a_break" },
];

export const EDUCATION_OPTIONS: {
  value: EducationLevel;
  labelKey: string;
}[] = [
  { value: "no_formal", labelKey: "profile.options.no_formal_education" },
  { value: "middle_school", labelKey: "profile.options.middle_school" },
  { value: "high_school", labelKey: "profile.options.high_school" },
  { value: "vocational", labelKey: "profile.options.vocational_school" },
  { value: "bachelor", labelKey: "profile.options.bachelor_student" },
  { value: "master", labelKey: "profile.options.master_student" },
  { value: "doctorate", labelKey: "profile.options.doctorate" },
];

/** Education-entry level labels — plain level names,
 * unlike the basics select above which phrases them as current status. */
export const EDUCATION_LEVEL_OPTIONS: {
  value: EducationLevel;
  labelKey: string;
}[] =
  [
    { value: "no_formal", labelKey: "profile.options.no_formal" },
    { value: "middle_school", labelKey: "profile.options.middle_school" },
    { value: "high_school", labelKey: "profile.options.high_school" },
    { value: "vocational", labelKey: "profile.options.vocational" },
    { value: "bachelor", labelKey: "profile.options.bachelor" },
    { value: "master", labelKey: "profile.options.master" },
    { value: "doctorate", labelKey: "profile.options.doctorate" },
  ];

export const EDUCATION_LEVEL_LABEL_KEY: Record<string, string> = Object.fromEntries(
  EDUCATION_LEVEL_OPTIONS.map((o) => [o.value, o.labelKey])
);

/** Same order the backend ranks with (enums.EducationLevelOrder). */
export const EDUCATION_LEVEL_ORDER: EducationLevel[] = [
  "no_formal",
  "middle_school",
  "high_school",
  "vocational",
  "bachelor",
  "master",
  "doctorate",
];

export const GPA_BAND_OPTIONS: {
  value: string;
  labelKey: string;
}[] = [
  { value: "unknown", labelKey: "profile.options.prefer_not_to_say" },
  { value: "low", labelKey: "profile.options.low" },
  { value: "below_average", labelKey: "profile.options.below_average" },
  { value: "average", labelKey: "profile.options.average" },
  { value: "good", labelKey: "profile.options.good" },
  { value: "excellent", labelKey: "profile.options.excellent" },
];

export const COMMON_SUBJECTS = [
  "mathematics",
  "physics",
  "chemistry",
  "biology",
  "history",
  "literature",
  "art",
  "computer-science",
  "economics",
  "geography",
];

export const LANGUAGE_CODE_OPTIONS = pickLanguages([
  "el", "en", "de", "fr", "es", "it", "pt", "nl", "sv", "pl",
  "tr", "ru", "ar", "ja", "ko", "zh", "hi", "ur", "fa", "ro",
  "hu", "cs", "sk", "uk", "he", "bn", "id", "ms", "th", "vi",
]);

export const LANGUAGE_LEVELS: {
  value: string;
  labelKey: string;
}[] = [
  { value: "basic", labelKey: "profile.options.basic" },
  { value: "intermediate", labelKey: "profile.options.intermediate" },
  { value: "advanced", labelKey: "profile.options.advanced" },
  { value: "native", labelKey: "profile.options.native" },
];

export const PHYSICAL_ACTIVITY_OPTIONS: {
  value: PhysicalActivity;
  labelKey: string;
}[] = [
  { value: "sedentary", labelKey: "profile.options.sedentary" },
  { value: "light", labelKey: "profile.options.light" },
  { value: "moderate", labelKey: "profile.options.moderate" },
  { value: "active", labelKey: "profile.options.active" },
  { value: "physical_intense", labelKey: "profile.options.physically_intense" },
];

export const CONDITION_OPTIONS: {
  value: string;
  labelKey: string;
}[] = [
  { value: "none", labelKey: "profile.options.none" },
  { value: "mobility_limited", labelKey: "profile.options.mobility_limited" },
  { value: "hearing_impaired", labelKey: "profile.options.hearing_impaired" },
  { value: "vision_impaired", labelKey: "profile.options.vision_impaired" },
  { value: "chronic_fatigue", labelKey: "profile.options.chronic_fatigue" },
  { value: "other", labelKey: "profile.options.other" },
];

export const WORK_SCALES: {
  key: keyof Pick<
    Profile["work_preferences"],
    | "teamwork"
    | "environment"
    | "structure"
    | "pace"
    | "leadership"
    | "salary_priority"
    | "stability_priority"
    | "creativity_priority"
  >;
  labelKey: string;
  lowKey: string;
  highKey: string;
}[] = [
  { key: "teamwork", lowKey: "profile.options.solo", highKey: "profile.options.team", labelKey: "profile.options.teamwork" },
  { key: "environment", lowKey: "profile.options.indoors", highKey: "profile.options.outdoors", labelKey: "profile.options.environment" },
  { key: "structure", lowKey: "profile.options.routine", highKey: "profile.options.variety", labelKey: "profile.options.structure" },
  { key: "pace", lowKey: "profile.options.calm", highKey: "profile.options.fast", labelKey: "profile.options.pace" },
  { key: "leadership", lowKey: "profile.options.follow", highKey: "profile.options.lead", labelKey: "profile.options.leadership" },
  { key: "salary_priority", lowKey: "profile.options.low", highKey: "profile.options.high", labelKey: "profile.options.salary_priority" },
  { key: "stability_priority", lowKey: "profile.options.risky", highKey: "profile.options.secure", labelKey: "profile.options.stability_priority" },
  { key: "creativity_priority", lowKey: "profile.options.conventional", highKey: "profile.options.creative", labelKey: "profile.options.creativity_priority" },
];

export const FOCUS_AREAS = [
  {
    key: "people", labelKey: "profile.options.people",
    hintKey: "profile.options.teaching_hint",
  },
  {
    key: "things", labelKey: "profile.options.things",
    hintKey: "profile.options.tools_hint",
  },
  { key: "data", hintKey: "profile.options.numbers_hint", labelKey: "profile.options.data" },
  {
    key: "ideas", labelKey: "profile.options.ideas",
    hintKey: "profile.options.design_hint",
  },
] as const;

export const LINK_KIND_OPTIONS: {
  value: string;
  labelKey: string;
}[] = [
  { value: "linkedin", labelKey: "profile.options.linkedin" },
  { value: "github", labelKey: "profile.options.github" },
  { value: "portfolio", labelKey: "profile.options.portfolio" },
  { value: "other", labelKey: "profile.options.other" },
];
