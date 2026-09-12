import type { EducationLevel, PhysicalActivity, Profile } from "@/types";

export const STAGE_OPTIONS = [
  { value: "student", label: "I'm a student", labelKey: "profile.options.i_m_a_student" },
  { value: "early_career", label: "Early in my career", labelKey: "profile.options.early_in_my_career" },
  { value: "experienced", label: "Experienced professional", labelKey: "profile.options.experienced_professional" },
  { value: "switching", label: "Switching fields", labelKey: "profile.options.switching_fields" },
  { value: "returning", label: "Returning after a break", labelKey: "profile.options.returning_after_a_break" },
];

export const STAGE_SUBTITLE: Record<string, string> = {
  student: "Tell us about you",
  early_career: "Tell us about you — your experience counts from day one",
  experienced: "Tell us about you — your experience leads the way",
  switching: "Tell us about you — we'll focus on what transfers",
  returning: "Welcome back — let's rebuild from what you bring",
};

export const EDUCATION_OPTIONS: {
  value: EducationLevel;
  label: string;
  labelKey: string;
}[] = [
  { value: "no_formal", label: "No formal education", labelKey: "profile.options.no_formal_education" },
  { value: "middle_school", label: "Middle school", labelKey: "profile.options.middle_school" },
  { value: "high_school", label: "High school", labelKey: "profile.options.high_school" },
  { value: "vocational", label: "Vocational school", labelKey: "profile.options.vocational_school" },
  { value: "bachelor", label: "Bachelor student", labelKey: "profile.options.bachelor_student" },
  { value: "master", label: "Master student", labelKey: "profile.options.master_student" },
  { value: "doctorate", label: "Doctorate", labelKey: "profile.options.doctorate" },
];

/** Education-entry level labels — plain level names,
 * unlike the basics select above which phrases them as current status. */
export const EDUCATION_LEVEL_OPTIONS: {
  value: EducationLevel;
  label: string;
  labelKey: string;
}[] =
  [
    { value: "no_formal", label: "No formal", labelKey: "profile.options.no_formal" },
    { value: "middle_school", label: "Middle school", labelKey: "profile.options.middle_school" },
    { value: "high_school", label: "High school", labelKey: "profile.options.high_school" },
    { value: "vocational", label: "Vocational", labelKey: "profile.options.vocational" },
    { value: "bachelor", label: "Bachelor", labelKey: "profile.options.bachelor" },
    { value: "master", label: "Master", labelKey: "profile.options.master" },
    { value: "doctorate", label: "Doctorate", labelKey: "profile.options.doctorate" },
  ];

export const EDUCATION_LEVEL_LABEL: Record<string, string> = Object.fromEntries(
  EDUCATION_LEVEL_OPTIONS.map((o) => [o.value, o.label])
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
  label: string;
  labelKey: string;
}[] = [
  { value: "unknown", label: "Prefer not to say", labelKey: "profile.options.prefer_not_to_say" },
  { value: "low", label: "Low", labelKey: "profile.options.low" },
  { value: "below_average", label: "Below average", labelKey: "profile.options.below_average" },
  { value: "average", label: "Average", labelKey: "profile.options.average" },
  { value: "good", label: "Good", labelKey: "profile.options.good" },
  { value: "excellent", label: "Excellent", labelKey: "profile.options.excellent" },
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

export const LANGUAGE_CODE_OPTIONS: {
  value: string;
  label: string;
  labelKey: string;
}[] = [
  { value: "el", label: "Greek", labelKey: "profile.options.greek" },
  { value: "en", label: "English", labelKey: "profile.options.english" },
  { value: "de", label: "German", labelKey: "profile.options.german" },
  { value: "fr", label: "French", labelKey: "profile.options.french" },
  { value: "es", label: "Spanish", labelKey: "profile.options.spanish" },
  { value: "it", label: "Italian", labelKey: "profile.options.italian" },
  { value: "pt", label: "Portuguese", labelKey: "profile.options.portuguese" },
  { value: "nl", label: "Dutch", labelKey: "profile.options.dutch" },
  { value: "sv", label: "Swedish", labelKey: "profile.options.swedish" },
  { value: "pl", label: "Polish", labelKey: "profile.options.polish" },
  { value: "tr", label: "Turkish", labelKey: "profile.options.turkish" },
  { value: "ru", label: "Russian", labelKey: "profile.options.russian" },
  { value: "ar", label: "Arabic", labelKey: "profile.options.arabic" },
  { value: "ja", label: "Japanese", labelKey: "profile.options.japanese" },
  { value: "ko", label: "Korean", labelKey: "profile.options.korean" },
  { value: "zh", label: "Chinese", labelKey: "profile.options.chinese" },
  { value: "hi", label: "Hindi", labelKey: "profile.options.hindi" },
  { value: "ur", label: "Urdu", labelKey: "profile.options.urdu" },
  { value: "fa", label: "Persian", labelKey: "profile.options.persian" },
  { value: "ro", label: "Romanian", labelKey: "profile.options.romanian" },
  { value: "hu", label: "Hungarian", labelKey: "profile.options.hungarian" },
  { value: "cs", label: "Czech", labelKey: "profile.options.czech" },
  { value: "sk", label: "Slovak", labelKey: "profile.options.slovak" },
  { value: "uk", label: "Ukrainian", labelKey: "profile.options.ukrainian" },
  { value: "he", label: "Hebrew", labelKey: "profile.options.hebrew" },
  { value: "bn", label: "Bengali", labelKey: "profile.options.bengali" },
  { value: "id", label: "Indonesian", labelKey: "profile.options.indonesian" },
  { value: "ms", label: "Malay", labelKey: "profile.options.malay" },
  { value: "th", label: "Thai", labelKey: "profile.options.thai" },
  { value: "vi", label: "Vietnamese", labelKey: "profile.options.vietnamese" },];

export const LANGUAGE_LEVELS: {
  value: string;
  label: string;
  labelKey: string;
}[] = [
  { value: "basic", label: "Basic", labelKey: "profile.options.basic" },
  { value: "intermediate", label: "Intermediate", labelKey: "profile.options.intermediate" },
  { value: "advanced", label: "Advanced", labelKey: "profile.options.advanced" },
  { value: "native", label: "Native", labelKey: "profile.options.native" },
];

export const PHYSICAL_ACTIVITY_OPTIONS: {
  value: PhysicalActivity;
  label: string;
  labelKey: string;
}[] = [
  { value: "sedentary", label: "Sedentary", labelKey: "profile.options.sedentary" },
  { value: "light", label: "Light", labelKey: "profile.options.light" },
  { value: "moderate", label: "Moderate", labelKey: "profile.options.moderate" },
  { value: "active", label: "Active", labelKey: "profile.options.active" },
  { value: "physical_intense", label: "Physically intense", labelKey: "profile.options.physically_intense" },
];

export const CONDITION_OPTIONS: {
  value: string;
  label: string;
  labelKey: string;
}[] = [
  { value: "none", label: "None", labelKey: "profile.options.none" },
  { value: "mobility_limited", label: "Mobility limited", labelKey: "profile.options.mobility_limited" },
  { value: "hearing_impaired", label: "Hearing impaired", labelKey: "profile.options.hearing_impaired" },
  { value: "vision_impaired", label: "Vision impaired", labelKey: "profile.options.vision_impaired" },
  { value: "chronic_fatigue", label: "Chronic fatigue", labelKey: "profile.options.chronic_fatigue" },
  { value: "other", label: "Other", labelKey: "profile.options.other" },
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
  label: string;
  labelKey: string;
  low: string;
  lowKey: string;
  high: string;
  highKey: string;
}[] = [
  { key: "teamwork", label: "Teamwork", low: "solo", lowKey: "profile.options.solo", high: "team", highKey: "profile.options.team", labelKey: "profile.options.teamwork" },
  { key: "environment", label: "Environment", low: "indoors", lowKey: "profile.options.indoors", high: "outdoors", highKey: "profile.options.outdoors", labelKey: "profile.options.environment" },
  { key: "structure", label: "Structure", low: "routine", lowKey: "profile.options.routine", high: "variety", highKey: "profile.options.variety", labelKey: "profile.options.structure" },
  { key: "pace", label: "Pace", low: "calm", lowKey: "profile.options.calm", high: "fast", highKey: "profile.options.fast", labelKey: "profile.options.pace" },
  { key: "leadership", label: "Leadership", low: "follow", lowKey: "profile.options.follow", high: "lead", highKey: "profile.options.lead", labelKey: "profile.options.leadership" },
  { key: "salary_priority", label: "Salary priority", low: "low", lowKey: "profile.options.low", high: "high", highKey: "profile.options.high", labelKey: "profile.options.salary_priority" },
  { key: "stability_priority", label: "Stability priority", low: "risky", lowKey: "profile.options.risky", high: "secure", highKey: "profile.options.secure", labelKey: "profile.options.stability_priority" },
  { key: "creativity_priority", label: "Creativity priority", low: "conventional", lowKey: "profile.options.conventional", high: "creative", highKey: "profile.options.creative", labelKey: "profile.options.creativity_priority" },
];

export const FOCUS_AREAS = [
  {
    key: "people",
    label: "People", labelKey: "profile.options.people",
    hint: "teaching, selling, caring, leading teams",
  },
  {
    key: "things",
    label: "Things", labelKey: "profile.options.things",
    hint: "tools, machines, building and fixing",
  },
  { key: "data", label: "Data", hint: "numbers, code, patterns, analysis", labelKey: "profile.options.data" },
  {
    key: "ideas",
    label: "Ideas", labelKey: "profile.options.ideas",
    hint: "design, writing, inventing, storytelling",
  },
] as const;

export const LINK_KIND_OPTIONS: {
  value: string;
  label: string;
  labelKey: string;
}[] = [
  { value: "linkedin", label: "LinkedIn", labelKey: "profile.options.linkedin" },
  { value: "github", label: "GitHub", labelKey: "profile.options.github" },
  { value: "portfolio", label: "Portfolio", labelKey: "profile.options.portfolio" },
  { value: "other", label: "Other", labelKey: "profile.options.other" },
];
