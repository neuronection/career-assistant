import {
  Briefcase,
  Compass,
  FileText,
  Sofa,
  type LucideIcon,
} from "lucide-react";
import type { OnboardingPath } from "@/types";

export type OnboardingStepName =
  | "Import CV"
  | "Basics"
  | "Study preferences"
  | "Education"
  | "Interests"
  | "Aspirations";

export interface PathMeta {
  key: OnboardingPath;
  title: string;
  tagline: string;
  fills: string[];
  icon: LucideIcon;
}

export const PATHS: PathMeta[] = [
  {
    key: "explore",
    title: "Explore careers",
    tagline: "See what jobs exist, what they pay and which skills they need.",
    fills: ["Basics", "Interests"],
    icon: Compass,
  },
  {
    key: "target",
    title: "I know my target job",
    tagline: "2-minute express start — track one job family and get alerts.",
    fills: ["Target job", "City"],
    icon: Briefcase,
  },
  {
    key: "cv_import",
    title: "Start from my CV",
    tagline: "Upload a CV — we fill your profile and build your job search.",
    fills: ["CV upload", "Quick check"],
    icon: FileText,
  },
  {
    key: "browse",
    title: "Just looking around",
    tagline: "Skip the questions and jump straight into the catalog.",
    fills: [],
    icon: Sofa,
  },
];

/** i18n label keys for the path tiles — title/tagline stay
 * as the stable fallbacks. */
export const PATH_LABEL_KEYS: Record<
  OnboardingPath,
  { titleKey: string; taglineKey: string }
> = {
  explore: {
    titleKey: "onboarding.path.explore.title",
    taglineKey: "onboarding.path.explore.tagline",
  },
  target: {
    titleKey: "onboarding.path.target.title",
    taglineKey: "onboarding.path.target.tagline",
  },
  cv_import: {
    titleKey: "onboarding.path.cv_import.title",
    taglineKey: "onboarding.path.cv_import.tagline",
  },
  browse: {
    titleKey: "onboarding.path.browse.title",
    taglineKey: "onboarding.path.browse.tagline",
  },
};

export const FILL_LABEL_KEYS: Record<string, string> = {
  Basics: "onboarding.fill.basics",
  Interests: "onboarding.fill.interests",
  "Target job": "onboarding.fill.targetJob",
  City: "onboarding.fill.city",
  "CV upload": "onboarding.fill.cvUpload",
  "Quick check": "onboarding.fill.quickCheck",
};

export const STEP_LABEL_KEYS: Record<OnboardingStepName, string> = {
  "Import CV": "onboarding.step.importCv",
  Basics: "onboarding.step.basics",
  "Study preferences": "onboarding.step.studyPreferences",
  Education: "onboarding.step.education",
  Interests: "onboarding.step.interests",
  Aspirations: "onboarding.step.aspirations",
};

export interface StepCtx {
  educationStep: boolean;
}

export interface StepSpec {
  name: OnboardingStepName;
  when?: (ctx: StepCtx) => boolean;
}

/** Wizard step lists per path — the section cards stay the
 * steps; the registry only decides which of them a path shows, filtered
 * by the bootstrap feature flags. */
export const PATH_STEPS: Partial<Record<OnboardingPath, StepSpec[]>> = {
  explore: [
    { name: "Basics" },
    { name: "Interests" },
    { name: "Study preferences", when: ({ educationStep }) => educationStep },
    { name: "Education", when: ({ educationStep }) => educationStep },
  ],
  cv_import: [{ name: "Import CV" }, { name: "Basics" }],
};

export function stepsForPath(
  path: OnboardingPath | null | undefined,
  ctx: StepCtx
): StepSpec[] {
  const specs = PATH_STEPS[path ?? "browse"] ?? [];
  return specs.filter((spec) => (spec.when ? spec.when(ctx) : true));
}
