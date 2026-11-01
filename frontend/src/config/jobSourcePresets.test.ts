import { describe, expect, it } from "vitest";
import { findCountry } from "@neuronection/assistant-ui/countries";

import {
  JOB_SOURCE_PRESETS,
  PRESET_CONNECTOR_KEYS,
  presetGroups,
} from "@/config/jobSourcePresets";

describe("job-source preset catalog", () => {
  it("carries the fields the gallery and the wizard need", () => {
    for (const preset of JOB_SOURCE_PRESETS) {
      expect(preset.slug).toMatch(/^[a-z0-9][a-z0-9-]*$/);
      expect(preset.name.trim()).not.toBe("");
      expect(preset.provider.trim()).not.toBe("");
      expect(["ats", "remote"]).toContain(preset.category);
      expect(preset.logo).toBe(`/presets/${preset.slug}.svg`);
      for (const value of Object.values(preset.config)) {
        expect(typeof value).toBe("string");
      }
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

  it("carries the connector field each provider's API requires", () => {
    const required: Record<string, string> = {
      recruitee: "company",
      teamtailor: "company",
    };
    for (const preset of JOB_SOURCE_PRESETS) {
      const field = required[preset.connectorKey];
      if (field) {
        expect(preset.config[field]?.trim()).toBeTruthy();
      }
    }
  });
});
