/**
 * Curated job-source presets (plan 176) — the DATA lives in
 * `jobSourcePresets.json` (editable without touching code, validated by
 * `jobSourcePresets.test.ts`); this module is the typed loader + the
 * grouping helper the UI consumes.
 *
 * Public connectors only — never private bundle ids. Countries are ISO
 * 3166 alpha-2 (the library `countries` catalog renders flag + name). A
 * preset's logo follows the `public/presets/<slug>.svg` convention unless
 * the JSON sets `logo`; a missing file degrades to the monogram fallback.
 */

import raw from "@/config/jobSourcePresets.json";

export type JobSourcePresetCategory = "ats" | "remote";

export interface JobSourcePreset {
  slug: string;
  name: string;
  connectorKey: string;
  provider: string;
  category: JobSourcePresetCategory;
  config: Record<string, string>;
  country?: string;
  logo: string;
}

/** Connector keys a preset may reference (public builtins only). */
export const PRESET_CONNECTOR_KEYS = [
  "recruitee",
  "teamtailor",
  "personio",
  "join_com",
  "workable",
  "jobicy",
  "remotive",
  "arbeitnow",
] as const;

type RawPreset = {
  slug: string;
  name: string;
  connectorKey: string;
  provider: string;
  category: JobSourcePresetCategory;
  config?: Record<string, string>;
  country?: string;
  logo?: string;
};

export const JOB_SOURCE_PRESETS: JobSourcePreset[] = (raw.presets as RawPreset[]).map((preset) => ({
  ...preset,
  config: preset.config ?? {},
  logo: preset.logo ?? `/presets/${preset.slug}.svg`,
}));

export function presetGroups(
  presets: JobSourcePreset[],
): { provider: string; presets: JobSourcePreset[] }[] {
  const order: string[] = [];
  const byProvider = new Map<string, JobSourcePreset[]>();
  for (const preset of presets) {
    if (!byProvider.has(preset.provider)) {
      order.push(preset.provider);
      byProvider.set(preset.provider, []);
    }
    byProvider.get(preset.provider)!.push(preset);
  }
  return order.map((provider) => ({ provider, presets: byProvider.get(provider)! }));
}
