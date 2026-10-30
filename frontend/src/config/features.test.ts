import { describe, expect, it } from "vitest";
import { FEATURES, betaFeatures, featureFor, isVisible } from "@/config/features";

describe("feature registry", () => {
  it("resolves a route to its longest matching prefix", () => {
    expect(featureFor("/postings")?.key).toBe("/postings");
    expect(featureFor("/postings/search")?.key).toBe("/postings");
    expect(featureFor("/catalog")?.state).toBeUndefined();
    expect(featureFor("/catalog")).toBeNull();
  });

  it("hides only explicit hidden entries", () => {
    expect(FEATURES.every((feature) => isVisible(feature.key))).toBe(true);
    expect(isVisible("/catalog")).toBe(true);
  });

  it("pins the un-gate decision of 2026-10-21", () => {
    // postings + companies graduate to shipped on 2026-10-30
    expect(betaFeatures().map((feature) => feature.key)).toEqual([
      "/autopilot",
      "/interviews",
      "/growth",
      "/paths",
    ]);
  });

  it("carries a documentation page for every entry", () => {
    for (const feature of FEATURES) {
      expect(feature.docs).toMatch(/^docs\/(user|dev)\/.+\.md$/);
      expect(feature.since).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
  });
});
