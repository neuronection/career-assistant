import type { CvAppliedEntity } from "@/types/cvIntake";

/** Where each CV-import entity type landed in the profile — stable
 * section slugs to workspace/hashed-section URLs. Plan 105: the one
 * deep-link source shared by provenance surfaces and CV Studio. */
export const APPLIED_ENTITY_LINKS: Partial<Record<CvAppliedEntity["entity_type"], string>> = {
  basics: "/profile",
  skills: "/profile#skills",
  experience_items: "/profile/experience",
  education_items: "/profile/education",
  certifications: "/profile/education",
  profile_achievements: "/profile/education",
  user_interest: "/profile#interests",
};

export type EntityEditorKind =
  | "experience"
  | "education"
  | "certification"
  | "achievement"
  | "skills";

export interface ContextSourceLink {
  route: string;
  editor: EntityEditorKind | null;
  /** Education-workspace entity toggle for sources living there. */
  entity?: "certifications" | "achievements";
  /** The workspace accepts `?focus=<id>` to open the item. */
  focusable?: boolean;
}

/** CV context source key → its profile home. Editors are the workspace
 * components; `null` means the source is a profile card section
 * (link-only from the Studio). */
export const CONTEXT_SOURCE_LINKS: Record<string, ContextSourceLink> = {
  experience: { route: "/profile/experience", editor: "experience", focusable: true },
  projects: { route: "/profile/experience", editor: "experience", focusable: true },
  volunteer: { route: "/profile/experience", editor: "experience", focusable: true },
  education: { route: "/profile/education", editor: "education", focusable: true },
  certifications: {
    route: "/profile/education",
    editor: "certification",
    entity: "certifications",
    focusable: true,
  },
  achievements: {
    route: "/profile/education",
    editor: "achievement",
    entity: "achievements",
    focusable: true,
  },
  skills: { route: "/profile#skills", editor: "skills" },
  languages: { route: "/profile#academics", editor: null },
  interests: { route: "/profile#interests", editor: null },
  basics: { route: "/profile", editor: null },
  summary: { route: "/profile#aspirations", editor: null },
};

/** Deep link to a context item's home — focused when the workspace
 * supports it, plain route/section otherwise. */
export function contextSourceLink(sourceKey: string, itemId?: string | null): string {
  const info = CONTEXT_SOURCE_LINKS[sourceKey];
  if (!info) return "/profile";
  if (!itemId || !info.focusable) return info.route;
  const params = new URLSearchParams();
  if (info.entity) params.set("entity", info.entity);
  params.set("focus", itemId);
  return `${info.route}?${params.toString()}`;
}
