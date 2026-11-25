/**
 * Preset provenance vocabulary shared by the source surfaces.
 *
 * Presets themselves now come from applied seed packs (the API); this module
 * only carries the small display types the sources UI and the preset dialog
 * pass around (which provider a preset came from, and its trust tier).
 */

import type { JobSourcePreset } from "@/config/jobSourcePresets";

export type CatalogTier = "operator" | "community" | "user";
export type ProvenanceTier = CatalogTier | "local";

export interface CatalogProvider {
  id: string;
  connectorKey: string;
  label: string;
  urlTemplate?: string | null;
  countries: string[];
  docsUrl?: string | null;
}

export interface CatalogProvenance {
  tier: ProvenanceTier;
  catalogId: string;
  catalogName: string;
}

export interface MergedGallery {
  presets: JobSourcePreset[];
  provenance: Map<string, CatalogProvenance>;
  providers: CatalogProvider[];
}
