import { describe, expect, it } from "vitest";

import { JOB_SOURCE_PRESETS, PRESET_CONNECTOR_KEYS } from "@/config/jobSourcePresets";
import {
  FEATURED_CATALOGS,
  mergeCatalogs,
  shortContentHash,
  validateCatalog,
  type SourcesCatalog,
} from "@/config/sourcesCatalogs";

import liveDocument from "./fixtures/ats-catalog-greece.json";

const CANONICAL_URL = "https://neuronection.com/api/v1/career/ats-catalogs/greece.json";
const CONTENT_HASH =
  "sha256:7007ba75b97b5b20c8f7120397e4888ed6e6d312367bf969765be68c16643d23";

const FEATURED = FEATURED_CATALOGS[0]!;

const parsedLive = validateCatalog(liveDocument);
if (!parsedLive.ok) throw new Error(parsedLive.error);
const live = parsedLive.document;

const storedCatalog: SourcesCatalog = {
  id: "neuronection-greece",
  kind: "url",
  url: CANONICAL_URL,
  name: live.name,
  license: live.license ?? null,
  tier: "operator",
  fetchedAt: "2026-11-23T00:00:00Z",
  updatedAt: live.updatedAt,
  revision: live.revision,
  contentHash: live.contentHash,
  etag: null,
  lastModified: null,
  presets: live.presets,
  providers: live.providers,
};

describe("published Greece catalog", () => {
  it("parses with the strict validator", () => {
    const result = validateCatalog(liveDocument);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.document.name).toBe("Neuronection verified — Greece");
    expect(result.document.license).toBe("CC-BY-4.0");
    expect(result.document.revision).toBe(2);
    expect(result.document.contentHash).toBe(CONTENT_HASH);
    expect(result.document.presets).toHaveLength(17);
    expect(result.document.providers).toEqual([]);
    for (const preset of result.document.presets) {
      expect(preset.country).toBe("GR");
      expect(preset.category).toBe("ats");
      expect(PRESET_CONNECTOR_KEYS).toContain(preset.connectorKey);
      expect(preset).not.toHaveProperty("logo");
    }
  });

  it("is the document the featured operator tile points at", () => {
    expect(FEATURED.id).toBe("neuronection-greece");
    expect(FEATURED.name).toBe(live.name);
    expect(FEATURED.tier).toBe("operator");
    expect(FEATURED.country).toBe("GR");
    expect(FEATURED.url).toBe(CANONICAL_URL);
  });

  it("rejects unknown fields and connector keys", () => {
    expect(validateCatalog({ ...liveDocument, surprise: true }).ok).toBe(false);
    const badKey = structuredClone(liveDocument);
    badKey.presets[0]!.connectorKey = "retired-connector";
    expect(validateCatalog(badKey).ok).toBe(false);
  });
});

describe("mergeCatalogs", () => {
  it("lets the imported operator catalog override bundled entries by slug", () => {
    const merged = mergeCatalogs(JOB_SOURCE_PRESETS, [storedCatalog]);
    expect(merged.presets).toHaveLength(JOB_SOURCE_PRESETS.length);
    expect(merged.provenance.get("affideagreece")).toMatchObject({
      tier: "operator",
      catalogId: "neuronection-greece",
      catalogName: liveDocument.name,
    });
    const overridden = merged.presets.find((preset) => preset.slug === "affideagreece");
    expect(overridden?.logo).toBe("");
    expect(merged.provenance.get("jobicy")?.tier).toBe("bundled");
    expect(merged.providers).toEqual([]);
  });
});

describe("shortContentHash", () => {
  it("keeps the algorithm and eight digest characters", () => {
    expect(shortContentHash(CONTENT_HASH)).toBe("sha256:7007ba75…");
    expect(shortContentHash("short")).toBe("short");
  });
});
