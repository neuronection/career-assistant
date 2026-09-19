import { Compass, FileText, Target, type LucideIcon } from "lucide-react";

export const PROFILE_SCOPE_KEYS = ["cv", "match", "guide"] as const;
export type ProfileScopeKey = (typeof PROFILE_SCOPE_KEYS)[number];

export interface ProfileScopeDef {
  key: ProfileScopeKey;
  labelKey: string;
  hintKey: string;
  icon: LucideIcon;
  dotClass: string;
  chipClass: string;
}

export const PROFILE_SCOPES: Record<ProfileScopeKey, ProfileScopeDef> = {
  cv: {
    key: "cv",
    labelKey: "profileScopes.cv.label",
    hintKey: "profileScopes.cv.hint",
    icon: FileText,
    dotClass: "bg-sky-500",
    chipClass: "border-sky-200 bg-sky-50 text-sky-700",
  },
  match: {
    key: "match",
    labelKey: "profileScopes.match.label",
    hintKey: "profileScopes.match.hint",
    icon: Target,
    dotClass: "bg-violet-500",
    chipClass: "border-violet-200 bg-violet-50 text-violet-700",
  },
  guide: {
    key: "guide",
    labelKey: "profileScopes.guide.label",
    hintKey: "profileScopes.guide.hint",
    icon: Compass,
    dotClass: "bg-emerald-500",
    chipClass: "border-emerald-200 bg-emerald-50 text-emerald-700",
  },
};

export const PROFILE_SECTION_IDS = [
  "photo",
  "basics",
  "academics",
  "languages",
  "interests",
  "tastes",
  "aspirations",
  "work-style",
  "constraints",
  "skills",
  "weights",
  "experience",
  "education",
  "assessment",
] as const;
export type ProfileSectionId = (typeof PROFILE_SECTION_IDS)[number];

export const SECTION_LABEL_KEYS: Record<ProfileSectionId, string> = {
  photo: "profileEdit.nav.photo",
  basics: "profileEdit.nav.basics",
  academics: "profileEdit.nav.academics",
  languages: "profileEdit.nav.languages",
  interests: "profileEdit.nav.interests",
  tastes: "profileEdit.nav.tastes",
  aspirations: "profileEdit.nav.aspirations",
  "work-style": "profileEdit.nav.workStyle",
  constraints: "profileEdit.nav.constraints",
  skills: "profileEdit.nav.skills",
  weights: "profileEdit.nav.weights",
  experience: "experience.title",
  education: "education.title",
  assessment: "profileEdit.nav.assessment",
};

/**
 * Which goal each profile section feeds. Grounded in the backend
 * consumers, not UI intuition: `cv` mirrors the CV context-source
 * registry (`cv_context_service.CV_CONTEXT_SOURCES`), `match` mirrors
 * the fit inputs (`fit/service.py` user_context + scoring weights +
 * values/riasec metrics), `guide` mirrors the AI ground tools
 * (`my_experience`, `my_skills`, `my_education`, the section reader
 * and the matching/explore recommendations they drive).
 */
export const SECTION_SCOPES: Record<ProfileSectionId, readonly ProfileScopeKey[]> = {
  photo: ["cv"],
  basics: ["cv", "match"],
  academics: ["guide"],
  languages: ["cv", "guide"],
  interests: ["cv", "match", "guide"],
  tastes: ["match", "guide"],
  aspirations: ["cv", "guide"],
  "work-style": ["match", "guide"],
  constraints: ["match", "guide"],
  skills: ["cv", "match", "guide"],
  weights: ["match"],
  experience: ["cv", "match", "guide"],
  education: ["cv", "match", "guide"],
  assessment: ["match"],
};

export function isProfileScopeKey(value: string | null): value is ProfileScopeKey {
  return value !== null && (PROFILE_SCOPE_KEYS as readonly string[]).includes(value);
}

export function scopesFor(sectionId: string): readonly ProfileScopeKey[] {
  return SECTION_SCOPES[sectionId as ProfileSectionId] ?? [];
}

export function sectionsForScope(scope: ProfileScopeKey): ProfileSectionId[] {
  return PROFILE_SECTION_IDS.filter((id) => SECTION_SCOPES[id].includes(scope));
}
