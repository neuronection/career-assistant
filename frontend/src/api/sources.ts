import { api } from "./client";

// Tools → connectors → job sources (ADR-0033 domain tools.connectors,
// broadened by plan 32 Phase 1): posting-source connector instances —
// catalog-driven config from the extension registry, sealed secret slots,
// per-source probes through the polite runtime.

export type SecretHint = { set: boolean; hint: string | null };

export type PostingSource = {
  id: string;
  key: string;
  connector_key: string;
  config: Record<string, string | number | boolean>;
  secret_hints: Record<string, SecretHint>;
  enabled: boolean;
  last_run_at: string | null;
  sync_state: Record<string, unknown>;
  error: string;
};

export type ConnectorCatalogEntry = {
  key: string;
  title: string;
  docs_url: string;
  builtin: boolean;
  secret_fields: string[];
  config_schema: {
    type: "object";
    properties: Record<string, ConfigFieldSchema>;
    required?: string[];
  };
  manifest: {
    id: string;
    capabilities: string[];
    domains?: string[];
    supportsIncremental: boolean;
  };
};

export type ConfigFieldSchema = {
  type: "string" | "number" | "boolean" | "array";
  title?: string;
  enum?: string[];
  default?: string | number | boolean;
  "x-secret"?: boolean;
  maxLength?: number;
  minLength?: number;
};

export type SourceProbe = {
  ok: boolean;
  items?: number;
  error?: { code: string; detail: string; retryable: string } | null;
  latency_ms?: number;
};

export async function fetchAdminSources(): Promise<PostingSource[]> {
  const response = await api.get<PostingSource[]>("/admin/postings/sources");
  return response.data;
}

export async function fetchConnectorCatalog(): Promise<ConnectorCatalogEntry[]> {
  const response = await api.get<ConnectorCatalogEntry[]>("/admin/postings/connectors");
  return response.data;
}

export async function createSource(payload: {
  key: string;
  connector_key: string;
  config: Record<string, string | number | boolean>;
  secrets?: Record<string, string>;
}): Promise<{ id: string; key: string; connector_key: string }> {
  const response = await api.post("/admin/postings/sources", payload);
  return response.data;
}

export async function updateSource(
  id: string,
  payload: {
    config?: Record<string, string | number | boolean>;
    secrets?: Record<string, string>;
    enabled?: boolean;
  },
): Promise<PostingSource> {
  const response = await api.put(`/admin/postings/sources/${id}`, payload);
  return response.data;
}

export async function probeSource(id: string): Promise<SourceProbe> {
  const response = await api.post(`/admin/postings/sources/${id}/probe`);
  return response.data;
}

export async function syncSource(id: string): Promise<{ job_id: string; status: string }> {
  const response = await api.post(`/admin/postings/sources/${id}/sync`);
  return response.data;
}
