import type {
  WebSearchProbeStatus,
  WebSearchProviderCatalog,
  WebSearchProviderCatalogField,
  WebSearchProviderProbeView,
  WebSearchProviderSaveInput,
  WebSearchProviderView,
} from "@neuronection/assistant-ui/web-search-providers";
import type {
  SearchProvider,
  SearchProviderCatalog,
  SearchProviderProbe,
  SearchProviderSaveBody,
} from "@/api/ai";

// The family "pure mapping module" rule (family-ui): wire types → library
// view-models in one place, never inline at call sites. Career's catalog
// arrives from the backend (the vendored family contract served by
// GET /ai/web/search-providers/catalog) and stores instance rows with
// underscore type keys (`google_pse`) while the catalog keys are hyphenated
// (`google-pse`) — the backend canonicalizes both directions.

export function toSearchProviderCatalog(
  raw: SearchProviderCatalog,
): WebSearchProviderCatalog {
  return {
    order: raw.providerOrder,
    entries: raw.providers as unknown as WebSearchProviderCatalog["entries"],
  };
}

export function toCatalogType(type: string): string {
  return type.replace(/_/g, "-");
}

export function toCardView(provider: SearchProvider): WebSearchProviderView {
  return {
    id: provider.id,
    name: provider.name,
    type: toCatalogType(provider.type),
    enabled: provider.enabled,
    baseUrl: provider.base_url || null,
    googleCx: provider.google_cx ?? null,
    keyHint: provider.key_hint ?? null,
    keySet: provider.key_set,
  };
}

export function toProbeView(probe: SearchProviderProbe): WebSearchProviderProbeView {
  return {
    status: probe.status as WebSearchProbeStatus,
    latencyMs: probe.latency_ms,
    error: probe.error ?? null,
  };
}

// App-declared per-instance tuning fields (backend `max_results` 1–10 and
// `timeout_ms` 500–30000) rendered by the form's Advanced disclosure;
// placeholders and bounds hints come from the contract limits. Labels ride
// i18n — they are app glue, not contract data.
export function searchExtraFields(
  limits: SearchProviderCatalog["limits"],
  labels: { timeout: string; maxResults: string },
): WebSearchProviderCatalogField[] {
  return [
    {
      id: "timeout_ms",
      label: labels.timeout,
      required: false,
      type: "number",
      advanced: true,
      hint: limits?.timeoutMs
        ? `${limits.timeoutMs.min}–${limits.timeoutMs.max}`
        : undefined,
      placeholder: limits?.timeoutMs ? String(limits.timeoutMs.default) : undefined,
    },
    {
      id: "max_results",
      label: labels.maxResults,
      required: false,
      type: "number",
      advanced: true,
      hint: limits?.maxResults
        ? `${limits.maxResults.min}–${limits.maxResults.max}`
        : undefined,
      placeholder: limits?.maxResults ? String(limits.maxResults.default) : undefined,
    },
  ];
}

// Library save payload → career wire body. `apiKey: null` keeps the stored
// key; empty tuning fields keep their stored values (the backend merge
// skips nulls). The base URL rides the same merge, so the two flows
// differ: on create `null` lets the backend fold in the catalog default,
// while on edit the typed URL is sent verbatim — a `null` could never
// revert a stored override, and storing the default string IS storing the
// default (the backend normalizes it).
export function providerSaveBody(
  input: WebSearchProviderSaveInput,
  entry?: { baseUrl?: string | null } | null,
): SearchProviderSaveBody {
  const fields = input.fields ?? {};
  const numberField = (id: string): number | null => {
    const raw = (fields[id] ?? "").trim();
    if (raw === "") return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const baseUrl = input.baseUrl?.trim() ?? "";
  const defaultBaseUrl = (entry?.baseUrl ?? "").replace(/\/$/, "");
  const isDefault = baseUrl.replace(/\/$/, "") === defaultBaseUrl;
  const base_url =
    baseUrl === "" || (input.id == null && isDefault) ? null : baseUrl;
  return {
    type: input.type,
    name: input.name?.trim() || null,
    base_url,
    google_cx: (input.googleCx ?? "").trim() || null,
    max_results: numberField("max_results"),
    timeout_ms: numberField("timeout_ms"),
    api_key: input.apiKey?.trim() ? input.apiKey.trim() : null,
  };
}

// The connection-name seed for the wizard's Advanced name field: the
// catalog label, numbered (`label 2`, `label 3`, …) once taken — the app
// owns the instances, so the dedupe is app-side.
export function defaultProviderName(
  type: string,
  catalog: SearchProviderCatalog,
  providers: SearchProvider[],
): string | null {
  const base = catalog.providers[type]?.label ?? type;
  const taken = new Set(providers.map((provider) => provider.name));
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(`${base} ${n}`)) n += 1;
  return `${base} ${n}`;
}
