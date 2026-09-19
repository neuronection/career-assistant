import { describe, expect, it } from "vitest";

import {
  PROFILE_SCOPES,
  PROFILE_SCOPE_KEYS,
  PROFILE_SECTION_IDS,
  SECTION_LABEL_KEYS,
  SECTION_SCOPES,
  isProfileScopeKey,
  scopesFor,
  sectionsForScope,
} from "@/config/profileScopes";

describe("profileScopes registry", () => {
  it("assigns at least one valid scope to every section", () => {
    for (const id of PROFILE_SECTION_IDS) {
      const scopes = SECTION_SCOPES[id];
      expect(scopes.length, id).toBeGreaterThan(0);
      for (const scope of scopes) {
        expect(PROFILE_SCOPE_KEYS).toContain(scope);
      }
    }
  });

  it("defines every scope with at least one section", () => {
    for (const key of PROFILE_SCOPE_KEYS) {
      expect(PROFILE_SCOPES[key].labelKey).toBeTruthy();
      expect(sectionsForScope(key).length, key).toBeGreaterThan(0);
    }
  });

  it("round-trips scopesFor through sectionsForScope", () => {
    for (const id of PROFILE_SECTION_IDS) {
      for (const scope of scopesFor(id)) {
        expect(sectionsForScope(scope)).toContain(id);
      }
    }
  });

  it("labels every section and treats unknown ids as scope-less", () => {
    for (const id of PROFILE_SECTION_IDS) {
      expect(SECTION_LABEL_KEYS[id], id).toBeTruthy();
    }
    expect(scopesFor("account")).toEqual([]);
    expect(isProfileScopeKey("cv")).toBe(true);
    expect(isProfileScopeKey("nope")).toBe(false);
    expect(isProfileScopeKey(null)).toBe(false);
  });

  it("keeps the CV mapping aligned with the CV context sources", () => {
    const cvSections = sectionsForScope("cv");
    for (const required of ["basics", "skills", "experience", "education", "interests"]) {
      expect(cvSections).toContain(required);
    }
    expect(cvSections).not.toContain("weights");
  });
});
