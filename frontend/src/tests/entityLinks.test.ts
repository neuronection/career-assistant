import { describe, expect, it } from "vitest";

import {
  APPLIED_ENTITY_LINKS,
  CONTEXT_SOURCE_LINKS,
  contextSourceLink,
} from "@/lib/entityLinks";

describe("entityLinks", () => {
  it("keeps the intake landed-links URLs stable", () => {
    expect(APPLIED_ENTITY_LINKS).toMatchObject({
      basics: "/profile",
      skills: "/profile#skills",
      experience_items: "/profile/experience",
      education_items: "/profile/education",
      certifications: "/profile/education",
      profile_achievements: "/profile/education",
      user_interest: "/profile#interests",
    });
  });

  it("covers every CV context source with a profile home", () => {
    for (const key of [
      "basics",
      "summary",
      "experience",
      "projects",
      "volunteer",
      "education",
      "certifications",
      "achievements",
      "skills",
      "languages",
      "interests",
    ]) {
      expect(CONTEXT_SOURCE_LINKS[key], key).toBeDefined();
    }
  });

  it("marks entity workspaces focusable and card sections link-only", () => {
    for (const key of [
      "experience",
      "projects",
      "volunteer",
      "education",
      "certifications",
      "achievements",
    ]) {
      expect(CONTEXT_SOURCE_LINKS[key].focusable, key).toBe(true);
    }
    for (const key of ["skills", "languages", "interests", "basics", "summary"]) {
      expect(CONTEXT_SOURCE_LINKS[key].focusable, key).toBeUndefined();
    }
  });

  it("builds focused deep links for experience kinds", () => {
    expect(contextSourceLink("experience", "e1")).toBe(
      "/profile/experience?focus=e1"
    );
    expect(contextSourceLink("projects", "e7")).toBe(
      "/profile/experience?focus=e7"
    );
    expect(contextSourceLink("volunteer", null)).toBe("/profile/experience");
  });

  it("routes education sub-entities through the education workspace", () => {
    expect(contextSourceLink("education", "ed1")).toBe(
      "/profile/education?focus=ed1"
    );
    expect(contextSourceLink("certifications", "c1")).toBe(
      "/profile/education?entity=certifications&focus=c1"
    );
    expect(contextSourceLink("achievements", "a1")).toBe(
      "/profile/education?entity=achievements&focus=a1"
    );
    expect(contextSourceLink("certifications", null)).toBe(
      "/profile/education"
    );
  });

  it("returns the plain section route for card-backed sources", () => {
    expect(contextSourceLink("skills", "s1")).toBe("/profile#skills");
    expect(contextSourceLink("languages")).toBe("/profile#academics");
    expect(contextSourceLink("interests", "i1")).toBe("/profile#interests");
    expect(contextSourceLink("basics")).toBe("/profile");
    expect(contextSourceLink("summary")).toBe("/profile#aspirations");
  });

  it("falls back to the profile for unknown sources", () => {
    expect(contextSourceLink("unknown", "x1")).toBe("/profile");
  });
});
