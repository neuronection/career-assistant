import { describe, expect, it } from "vitest";
import { FEATURES, betaFeatures, featureFor, isVisible } from "@/config/features";

describe("feature registry", () => {
  it("resolves a route to its longest matching prefix", () => {
    expect(featureFor("/postings")?.key).toBe("/postings");
    expect(featureFor("/postings/search")?.key).toBe("/postings");
    expect(featureFor("/catalog")?.key).toBe("/catalog");
    expect(featureFor("/catalog/graph")?.key).toBe("/catalog");
    expect(featureFor("/jobs/code-123")?.key).toBe("/jobs");
    expect(featureFor("/catalog/universities/42")?.key).toBe(
      "/catalog/universities",
    );
    expect(featureFor("/nowhere")).toBeNull();
  });

  it("hides only explicit hidden entries", () => {
    expect(FEATURES.every((feature) => isVisible(feature.key))).toBe(true);
    expect(isVisible("/catalog")).toBe(true);
  });

  it("pins the un-gate decision of 2026-10-21", () => {
    // postings + companies graduate to shipped on 2026-10-30;
    // market stats arrives beta (plan 170, 2026-10-31)
    expect(betaFeatures().map((feature) => feature.key)).toEqual([
      "/contacts",
      "/autopilot",
      "/interviews",
      "/growth",
      "/paths",
      "/postings/stats",
    ]);
  });

  it("carries a documentation page for every entry", () => {
    for (const feature of FEATURES) {
      expect(feature.docs).toMatch(/^docs\/(user|dev)\/.+\.md$/);
      expect(feature.since).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
  });
});
