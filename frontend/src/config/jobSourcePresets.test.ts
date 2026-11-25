import { describe, expect, it } from "vitest";
import { findCountry } from "@neuronection/assistant-ui/countries";

import {
  JOB_SOURCE_PRESETS,
  PRESET_CONNECTOR_KEYS,
  presetGroups,
} from "@/config/jobSourcePresets";

describe("job-source display index", () => {
  it("carries the fields the source list and the logo need", () => {
    for (const preset of JOB_SOURCE_PRESETS) {
      expect(preset.slug).toMatch(/^[a-z0-9][a-z0-9-]*$/);
      expect(preset.name.trim()).not.toBe("");
      expect(preset.provider.trim()).not.toBe("");
      expect(["ats", "remote"]).toContain(preset.category);
      expect(preset.logo).toBe(`/presets/${preset.slug}.svg`);
    }
  });

  it("ships no listing payload of its own", () => {
    for (const preset of JOB_SOURCE_PRESETS) {
      expect(preset.config).toEqual({});
      expect(preset.openings).toBeUndefined();
      expect(preset.verifiedAt).toBeUndefined();
    }
  });

  it("keeps slugs unique — the slug is also the source key", () => {
    const slugs = JOB_SOURCE_PRESETS.map((preset) => preset.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
  });

  it("references public connectors only", () => {
    for (const preset of JOB_SOURCE_PRESETS) {
      expect(PRESET_CONNECTOR_KEYS).toContain(preset.connectorKey);
    }
  });

  it("uses real ISO country codes where a country is set", () => {
    for (const preset of JOB_SOURCE_PRESETS) {
      if (preset.country) {
        expect(findCountry(preset.country)).toBeDefined();
      }
    }
    const remote = JOB_SOURCE_PRESETS.filter((preset) => preset.category === "remote");
    expect(remote.length).toBeGreaterThan(0);
  });

  it("groups in first-seen provider order and keeps every preset", () => {
    const groups = presetGroups(JOB_SOURCE_PRESETS);
    expect(groups.map((group) => group.provider)).toEqual([
      "Recruitee",
      "Teamtailor",
      "Workable",
      "Remote boards",
    ]);
    const flat = groups.flatMap((group) => group.presets);
    expect(flat).toHaveLength(JOB_SOURCE_PRESETS.length);
  });
});
