import { describe, expect, it } from "vitest";
import type {
  SearchProvider,
  SearchProviderCatalog,
  SearchProviderProbe,
} from "@/api/ai";
import {
  defaultProviderName,
  providerSaveBody,
  searchExtraFields,
  toCardView,
  toCatalogType,
  toProbeView,
  toSearchProviderCatalog,
} from "@/components/settings/searchProviderViews";

const catalog: SearchProviderCatalog = {
  providerOrder: ["searxng", "tavily", "google-pse"],
  providers: {
    searxng: {
      label: "SearXNG",
      requiresKey: false,
      keyUrl: null,
      baseUrl: null,
      baseUrlRequired: true,
    },
    tavily: {
      label: "Tavily",
      requiresKey: true,
      keyUrl: "https://app.tavily.com/app/api-key",
      baseUrl: "https://api.tavily.com",
      baseUrlRequired: false,
    },
    "google-pse": {
      label: "Google Programmable Search",
      requiresKey: true,
      keyUrl: null,
      baseUrl: "https://www.googleapis.com/customsearch/v1",
      baseUrlRequired: false,
      fields: [{ id: "google_cx", label: "Engine id (cx)", required: true }],
    },
  },
  limits: {
    maxResults: { default: 5, min: 1, max: 10 },
    timeoutMs: { default: 8000, min: 500, max: 30000 },
  },
};

describe("searchProviderViews mapping", () => {
  it("projects the wire catalog onto the library view model", () => {
    const view = toSearchProviderCatalog(catalog);
    expect(view.order).toEqual(["searxng", "tavily", "google-pse"]);
    expect(view.entries.tavily.label).toBe("Tavily");
    expect(view.entries["google-pse"].fields?.[0].id).toBe("google_cx");
  });

  it("maps stored underscore type keys onto the hyphenated catalog keys", () => {
    expect(toCatalogType("google_pse")).toBe("google-pse");
    expect(toCatalogType("searxng")).toBe("searxng");
  });

  it("maps a stored provider row onto the card view", () => {
    const row: SearchProvider = {
      id: "p1",
      name: "Google",
      type: "google_pse",
      enabled: false,
      base_url: "https://www.googleapis.com/customsearch/v1/",
      google_cx: "cx-123",
      key_hint: "••••cret",
      max_results: 5,
      timeout_ms: 8000,
      key_set: true,
    };
    expect(toCardView(row)).toEqual({
      id: "p1",
      name: "Google",
      type: "google-pse",
      enabled: false,
      baseUrl: "https://www.googleapis.com/customsearch/v1/",
      googleCx: "cx-123",
      keyHint: "••••cret",
      keySet: true,
    });
  });

  it("maps a probe onto the probe view", () => {
    const probe: SearchProviderProbe = {
      status: "ok",
      latency_ms: 234,
      result_count: 5,
      error: null,
    };
    expect(toProbeView(probe)).toEqual({ status: "ok", latencyMs: 234, error: null });
  });

  it("declares the tuning fields as advanced number fields from the contract limits", () => {
    const fields = searchExtraFields(catalog.limits, {
      timeout: "Timeout (ms)",
      maxResults: "Default result count",
    });
    expect(fields).toEqual([
      {
        id: "timeout_ms",
        label: "Timeout (ms)",
        required: false,
        type: "number",
        advanced: true,
        hint: "500–30000",
        placeholder: "8000",
      },
      {
        id: "max_results",
        label: "Default result count",
        required: false,
        type: "number",
        advanced: true,
        hint: "1–10",
        placeholder: "5",
      },
    ]);
    const bare = searchExtraFields(undefined, { timeout: "t", maxResults: "m" });
    expect(bare[0].placeholder).toBeUndefined();
    expect(bare[0].hint).toBeUndefined();
  });

  it("drops the catalog-default base URL and keeps a deviation", () => {
    const entry = catalog.providers.tavily;
    const kept = providerSaveBody(
      { type: "tavily", name: "Tavily", baseUrl: "https://api.tavily.com", apiKey: null },
      entry,
    );
    expect(kept.base_url).toBeNull();
    const deviating = providerSaveBody(
      {
        type: "tavily",
        name: "Proxy",
        baseUrl: "https://tavily.internal.example",
        apiKey: null,
      },
      entry,
    );
    expect(deviating.base_url).toBe("https://tavily.internal.example");
  });

  it("sends the engine id from the fields bag and trims the key", () => {
    const body = providerSaveBody(
      {
        type: "google-pse",
        name: "  Google  ",
        baseUrl: "https://www.googleapis.com/customsearch/v1",
        googleCx: " cx-9 ",
        apiKey: " AIza-secret ",
        fields: { google_cx: "cx-9", timeout_ms: "2500", max_results: "" },
      },
      catalog.providers["google-pse"],
    );
    expect(body).toEqual({
      type: "google-pse",
      name: "Google",
      base_url: null,
      google_cx: "cx-9",
      max_results: null,
      timeout_ms: 2500,
      api_key: "AIza-secret",
    });
  });

  it("keeps the stored key and tuning fields via null", () => {
    const body = providerSaveBody(
      { type: "searxng", name: null, baseUrl: "  ", apiKey: "", fields: {} },
      catalog.providers.searxng,
    );
    expect(body.api_key).toBeNull();
    expect(body.base_url).toBeNull();
    expect(body.max_results).toBeNull();
    expect(body.timeout_ms).toBeNull();
  });

  it("sends a stored override edit verbatim so the default can be restored", () => {
    const reverted = providerSaveBody(
      {
        id: "p1",
        type: "tavily",
        name: "Proxy",
        baseUrl: "https://api.tavily.com",
        apiKey: null,
      },
      catalog.providers.tavily,
    );
    expect(reverted.base_url).toBe("https://api.tavily.com");
    const slashed = providerSaveBody(
      { type: "tavily", name: null, baseUrl: "https://api.tavily.com/", apiKey: null },
      catalog.providers.tavily,
    );
    expect(slashed.base_url).toBeNull();
  });

  it("seeds the connection name from the catalog label, numbered when taken", () => {
    const row = (name: string): SearchProvider => ({
      id: name,
      name,
      type: "tavily",
      enabled: true,
      base_url: "https://api.tavily.com",
      google_cx: null,
      key_hint: null,
      max_results: 5,
      timeout_ms: 8000,
      key_set: false,
    });
    expect(defaultProviderName("tavily", catalog, [])).toBe("Tavily");
    expect(defaultProviderName("tavily", catalog, [row("SearXNG")])).toBe("Tavily");
    expect(defaultProviderName("tavily", catalog, [row("Tavily")])).toBe("Tavily 2");
    expect(defaultProviderName("tavily", catalog, [row("Tavily"), row("Tavily 2")])).toBe(
      "Tavily 3",
    );
  });
});
