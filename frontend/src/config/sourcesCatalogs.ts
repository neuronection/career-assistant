/**
 * ATS catalog import (plan 187): the catalog-document envelope plus the
 * client-side validation, merge and URL-fetch the gallery consumes.
 * Catalogs are pure DATA — the browser fetches (no SSRF surface on the
 * server), validates here for UX, and PUTs the parsed document; the
 * backend re-validates authoritatively (registry allowlist, caps).
 * Catalog `logo` is dropped on import: a catalog-supplied URL must never
 * become an external-origin image surface — presets render the monogram.
 */

import {
  PRESET_CONNECTOR_KEYS,
  type JobSourcePreset,
} from "@/config/jobSourcePresets";

export type CatalogTier = "operator" | "community" | "user";
export type ProvenanceTier = CatalogTier | "bundled";
export type CatalogKind = "url" | "file";
export type PresetCategory = "ats" | "remote";

export interface CatalogPreset {
  slug: string;
  name: string;
  connectorKey: string;
  provider: string;
  category: PresetCategory;
  config: Record<string, string>;
  country?: string;
  openings?: number;
  verifiedAt?: string;
}

export interface CatalogProvider {
  id: string;
  connectorKey: string;
  label: string;
  urlTemplate?: string | null;
  countries: string[];
  docsUrl?: string | null;
}

export interface CatalogDocument {
  schemaVersion: 1;
  kind: "career-ats-catalog";
  name: string;
  license?: string | null;
  updatedAt: string;
  revision: number;
  contentHash: string;
  signature: null;
  presets: CatalogPreset[];
  providers: CatalogProvider[];
}

/** One stored catalog (an AppSetting row entry, via the admin API) —
 * the import metadata + the document's content; the envelope keys
 * (`schemaVersion`/`kind`/`signature`) are validation-only and are not
 * persisted. */
export interface SourcesCatalog {
  id: string;
  kind: CatalogKind;
  url: string | null;
  name: string;
  license: string | null;
  tier: CatalogTier;
  fetchedAt: string;
  updatedAt: string;
  revision: number;
  contentHash: string;
  etag: string | null;
  lastModified: string | null;
  presets: CatalogPreset[];
  providers: CatalogProvider[];
}

export interface CatalogProvenance {
  tier: ProvenanceTier;
  catalogId: string;
  catalogName: string;
}

export const CATALOG_LIMITS = {
  presets: 300,
  providers: 50,
  bytes: 512 * 1024,
  catalogs: 8,
} as const;

const PRESET_KEYS = new Set<string>(PRESET_CONNECTOR_KEYS);
const PRESET_FIELDS = new Set([
  "slug",
  "name",
  "connectorKey",
  "provider",
  "category",
  "config",
  "country",
  "openings",
  "verifiedAt",
]);
const PROVIDER_FIELDS = new Set([
  "id",
  "connectorKey",
  "label",
  "urlTemplate",
  "countries",
  "docsUrl",
]);
const ENVELOPE_FIELDS = new Set([
  "schemaVersion",
  "kind",
  "name",
  "license",
  "updatedAt",
  "revision",
  "contentHash",
  "signature",
  "presets",
  "providers",
]);

export type CatalogParseResult =
  | { ok: true; document: CatalogDocument }
  | { ok: false; error: string };

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringConfig(value: unknown): Record<string, string> | null {
  if (!isPlainObject(value)) return null;
  const config: Record<string, string> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (typeof entry !== "string") return null;
    config[key] = entry;
  }
  return config;
}

function parsePreset(raw: unknown, seen: Set<string>): CatalogPreset | string {
  if (!isPlainObject(raw)) return "preset is not an object";
  for (const key of Object.keys(raw)) {
    if (!PRESET_FIELDS.has(key)) return `unknown preset field: ${key}`;
  }
  const slug = raw.slug;
  const name = raw.name;
  const connectorKey = raw.connectorKey;
  const provider = raw.provider;
  const category = raw.category;
  if (typeof slug !== "string" || !slug) return "preset slug missing";
  if (typeof name !== "string" || !name) return `preset ${slug}: name missing`;
  if (typeof connectorKey !== "string" || !connectorKey) {
    return `preset ${slug}: connectorKey missing`;
  }
  if (!PRESET_KEYS.has(connectorKey)) {
    return `preset ${slug}: unknown connector key ${connectorKey}`;
  }
  if (typeof provider !== "string" || !provider) {
    return `preset ${slug}: provider missing`;
  }
  if (category !== "ats" && category !== "remote") {
    return `preset ${slug}: category must be ats or remote`;
  }
  const config = stringConfig(raw.config ?? {});
  if (!config) return `preset ${slug}: config must map strings to strings`;
  if (seen.has(slug)) return `duplicate preset slug: ${slug}`;
  seen.add(slug);
  const country = raw.country;
  if (country !== undefined && (typeof country !== "string" || country.length !== 2)) {
    return `preset ${slug}: country must be an ISO alpha-2 code`;
  }
  const openings = raw.openings;
  if (openings !== undefined && typeof openings !== "number") {
    return `preset ${slug}: openings must be a number`;
  }
  const verifiedAt = raw.verifiedAt;
  if (verifiedAt !== undefined && typeof verifiedAt !== "string") {
    return `preset ${slug}: verifiedAt must be a string`;
  }
  return {
    slug,
    name,
    connectorKey,
    provider,
    category,
    config,
    country,
    openings,
    verifiedAt,
  };
}

function parseProvider(raw: unknown, seen: Set<string>): CatalogProvider | string {
  if (!isPlainObject(raw)) return "provider is not an object";
  for (const key of Object.keys(raw)) {
    if (!PROVIDER_FIELDS.has(key)) return `unknown provider field: ${key}`;
  }
  const id = raw.id;
  const connectorKey = raw.connectorKey;
  const label = raw.label;
  if (typeof id !== "string" || !id) return "provider id missing";
  if (typeof connectorKey !== "string" || !connectorKey) {
    return `provider ${id}: connectorKey missing`;
  }
  if (!PRESET_KEYS.has(connectorKey)) {
    return `provider ${id}: unknown connector key ${connectorKey}`;
  }
  if (typeof label !== "string" || !label) return `provider ${id}: label missing`;
  if (seen.has(id)) return `duplicate provider id: ${id}`;
  seen.add(id);
  const countries = raw.countries;
  if (countries !== undefined && !Array.isArray(countries)) {
    return `provider ${id}: countries must be a list`;
  }
  return {
    id,
    connectorKey,
    label,
    urlTemplate: typeof raw.urlTemplate === "string" ? raw.urlTemplate : null,
    countries: Array.isArray(countries) ? (countries as string[]) : [],
    docsUrl: typeof raw.docsUrl === "string" ? raw.docsUrl : null,
  };
}

/** Strict envelope validation — caps, slug uniqueness, connector-key
 * allowlist, `logo` dropped, unknown fields rejected. */
export function validateCatalog(raw: unknown): CatalogParseResult {
  let bytes = 0;
  try {
    bytes = new TextEncoder().encode(JSON.stringify(raw)).length;
  } catch {
    return { ok: false, error: "document is not JSON-serializable" };
  }
  if (bytes > CATALOG_LIMITS.bytes) {
    return {
      ok: false,
      error: `document exceeds the ${CATALOG_LIMITS.bytes}-byte cap`,
    };
  }
  if (!isPlainObject(raw)) return { ok: false, error: "document is not an object" };
  for (const key of Object.keys(raw)) {
    if (!ENVELOPE_FIELDS.has(key)) return { ok: false, error: `unknown field: ${key}` };
  }
  if (raw.schemaVersion !== 1) {
    return { ok: false, error: "schemaVersion must be 1" };
  }
  if (raw.kind !== "career-ats-catalog") {
    return { ok: false, error: "kind must be career-ats-catalog" };
  }
  if (raw.signature !== null && raw.signature !== undefined) {
    return { ok: false, error: "signature is reserved — must be null" };
  }
  const name = raw.name;
  if (typeof name !== "string" || !name) {
    return { ok: false, error: "name missing" };
  }
  const revision = raw.revision;
  if (typeof revision !== "number" || !Number.isInteger(revision) || revision < 0) {
    return { ok: false, error: "revision must be a non-negative integer" };
  }
  const contentHash = raw.contentHash;
  if (typeof contentHash !== "string" || contentHash.length < 8) {
    return { ok: false, error: "contentHash missing" };
  }
  if (!Array.isArray(raw.presets)) return { ok: false, error: "presets must be a list" };
  if (raw.presets.length > CATALOG_LIMITS.presets) {
    return {
      ok: false,
      error: `at most ${CATALOG_LIMITS.presets} presets per document`,
    };
  }
  if (!Array.isArray(raw.providers)) {
    return { ok: false, error: "providers must be a list" };
  }
  if (raw.providers.length > CATALOG_LIMITS.providers) {
    return {
      ok: false,
      error: `at most ${CATALOG_LIMITS.providers} providers per document`,
    };
  }
  const slugs = new Set<string>();
  const presets: CatalogPreset[] = [];
  for (const entry of raw.presets) {
    const parsed = parsePreset(entry, slugs);
    if (typeof parsed === "string") return { ok: false, error: parsed };
    presets.push(parsed);
  }
  const providerIds = new Set<string>();
  const providers: CatalogProvider[] = [];
  for (const entry of raw.providers) {
    const parsed = parseProvider(entry, providerIds);
    if (typeof parsed === "string") return { ok: false, error: parsed };
    providers.push(parsed);
  }
  return {
    ok: true,
    document: {
      schemaVersion: 1,
      kind: "career-ats-catalog",
      name,
      license: typeof raw.license === "string" ? raw.license : null,
      updatedAt:
        typeof raw.updatedAt === "string" ? raw.updatedAt : new Date().toISOString(),
      revision,
      contentHash,
      signature: null,
      presets,
      providers,
    },
  };
}

/** An https page must never fetch an http URL (mixed content). */
export function isMixedContent(pageUrl: string, target: string): boolean {
  try {
    return (
      new URL(pageUrl).protocol === "https:" && new URL(target).protocol === "http:"
    );
  } catch {
    return false;
  }
}

export type CatalogFetchOutcome =
  | { kind: "not-modified" }
  | { kind: "fetched"; raw: unknown; etag: string | null; lastModified: string | null }
  | { kind: "http-error"; status: number }
  | { kind: "fetch-failed"; detail: string }
  | { kind: "mixed-content" }
  | { kind: "non-json"; detail: string };

/** Browser-side conditional GET — the server stays out of the fetch path
 * entirely (no SSRF, no new limiter). Hosts without CORS headers surface
 * as `fetch-failed` (opaque network error). */
export async function fetchCatalogDocument(
  url: string,
  validators: { etag?: string | null; lastModified?: string | null } = {},
): Promise<CatalogFetchOutcome> {
  if (isMixedContent(window.location.href, url)) {
    return { kind: "mixed-content" };
  }
  const headers: Record<string, string> = {};
  if (validators.etag) headers["If-None-Match"] = validators.etag;
  if (validators.lastModified) headers["If-Modified-Since"] = validators.lastModified;
  let response: Response;
  try {
    response = await fetch(url, { headers, redirect: "follow" });
  } catch (err) {
    return {
      kind: "fetch-failed",
      detail: err instanceof Error ? err.message : String(err),
    };
  }
  if (response.status === 304) return { kind: "not-modified" };
  if (!response.ok) return { kind: "http-error", status: response.status };
  const text = await response.text();
  try {
    return {
      kind: "fetched",
      raw: JSON.parse(text),
      etag: response.headers.get("etag"),
      lastModified: response.headers.get("last-modified"),
    };
  } catch (err) {
    return {
      kind: "non-json",
      detail: err instanceof Error ? err.message : String(err),
    };
  }
}

export type CatalogChange =
  | { kind: "same" }
  | { kind: "revision-bump"; from: number; to: number }
  | { kind: "updated"; from: number; to: number; changedPresets: number };

function changedPresetCount(prev: CatalogPreset[], next: CatalogPreset[]): number {
  const before = new Map(prev.map((preset) => [preset.slug, JSON.stringify(preset)]));
  const after = new Map(next.map((preset) => [preset.slug, JSON.stringify(preset)]));
  let changed = 0;
  for (const [slug, value] of after) {
    if (before.get(slug) !== value) changed += 1;
  }
  for (const slug of before.keys()) {
    if (!after.has(slug)) changed += 1;
  }
  return changed;
}

/** Refresh comparison: same hash = at most a publisher revision bump;
 * a hash drift is an update even when the revision was forgotten. */
export function compareDocuments(
  prev: { revision?: number | null; contentHash?: string | null; presets?: CatalogPreset[] },
  next: CatalogDocument,
): CatalogChange {
  const from = prev.revision ?? 0;
  if (prev.contentHash != null && prev.contentHash === next.contentHash) {
    return next.revision > from
      ? { kind: "revision-bump", from, to: next.revision }
      : { kind: "same" };
  }
  return {
    kind: "updated",
    from,
    to: next.revision,
    changedPresets: changedPresetCount(prev.presets ?? [], next.presets),
  };
}

export interface MergedGallery {
  presets: JobSourcePreset[];
  provenance: Map<string, CatalogProvenance>;
  providers: CatalogProvider[];
}

/** Layered gallery data: bundled presets are the floor, imported catalog
 * entries override by slug (later catalogs win), provenance rides along. */
export function mergeCatalogs(
  bundled: JobSourcePreset[],
  catalogs: SourcesCatalog[],
): MergedGallery {
  const bySlug = new Map<string, JobSourcePreset>();
  const provenance = new Map<string, CatalogProvenance>();
  for (const preset of bundled) {
    bySlug.set(preset.slug, preset);
    provenance.set(preset.slug, {
      tier: "bundled",
      catalogId: "bundled",
      catalogName: "bundled",
    });
  }
  const providers = new Map<string, CatalogProvider>();
  for (const catalog of catalogs) {
    for (const preset of catalog.presets) {
      bySlug.set(preset.slug, {
        slug: preset.slug,
        name: preset.name,
        connectorKey: preset.connectorKey,
        provider: preset.provider,
        category: preset.category,
        config: { ...preset.config },
        country: preset.country,
        openings: preset.openings,
        verifiedAt: preset.verifiedAt,
        logo: "",
      });
      provenance.set(preset.slug, {
        tier: catalog.tier,
        catalogId: catalog.id,
        catalogName: catalog.name,
      });
    }
    for (const provider of catalog.providers) {
      if (!providers.has(provider.id)) providers.set(provider.id, provider);
    }
  }
  return {
    presets: [...bySlug.values()],
    provenance,
    providers: [...providers.values()],
  };
}
