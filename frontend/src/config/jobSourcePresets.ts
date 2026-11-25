/**
 * Static job-source *display* index (plan 176, trimmed by plan 218).
 *
 * The catalog itself no longer ships with the app: presets come from applied
 * seed packs (Git/index/upload). This file only supplies display metadata for
 * a source whose preset is not loaded — its label, country lens, provider and
 * logo slug — so existing sources keep grouping and labelling correctly.
 * Content fields (config, openings, verification dates) live in the pack.
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
  countries?: string[];
  worldwide?: boolean;
  logo: string;
  /** Live-verified opening count (a dated snapshot, not live data). */
  openings?: number;
  /** When the tenant's feed was last probe-verified. */
  verifiedAt?: string;
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
  country?: string;
  countries?: string[];
  worldwide?: boolean;
  logo?: string;
};

export const JOB_SOURCE_PRESETS: JobSourcePreset[] = (raw.presets as RawPreset[]).map((preset) => ({
  ...preset,
  config: {},
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

/** Sentinel key for presets without a country (worldwide/remote boards). */
export const WORLDWIDE_KEY = "WW";

/** App language → the country chip to preselect on dialog open (only
 * when the catalog actually carries that country). */
const LOCALE_COUNTRY: Record<string, string> = { el: "GR", de: "DE" };

export interface PresetCountryLens {
  /** ISO 3166 alpha-2, or `WORLDWIDE_KEY`. */
  key: string;
  label: string;
  count: number;
}

export function presetCountryLenses(
  presets: JobSourcePreset[],
  nameFor: (key: string) => string,
): PresetCountryLens[] {
  const counts = new Map<string, number>();
  for (const preset of presets) {
    const key = preset.country ?? WORLDWIDE_KEY;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([key, count]) => ({ key, label: nameFor(key), count }))
    .sort((a, b) => {
      if (a.key === WORLDWIDE_KEY) return 1;
      if (b.key === WORLDWIDE_KEY) return -1;
      return a.label.localeCompare(b.label);
    });
}

export function preselectCountries(language: string): string[] {
  const country = LOCALE_COUNTRY[language];
  if (!country) return [];
  const has = JOB_SOURCE_PRESETS.some((preset) => preset.country === country);
  return has ? [country] : [];
}
