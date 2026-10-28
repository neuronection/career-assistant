import { api } from "@/api/client";

// Tools → connectors → job sources (ADR-0033 domain tools.connectors,
// broadened by plan 32 Phase 1): posting-source connector instances —
// catalog-driven config from the extension registry, sealed secret slots,
// per-source probes through the polite runtime.

export type SecretHint = { set: boolean; hint: string | null };

export type SourceQueryInfo = {
  keywords: string;
  location: string;
  rotation: string;
  rotation_index: number;
  groups: { terms: string[]; keywords: string }[];
  provenance: Record<string, string[]>;
  group_terms: string[];
  curated: boolean;
  radar_ids: string[];
  computed_at: string | null;
};

export type PostingSource = {
  id: string;
  key: string;
  connector_key: string;
  kind: string;
  schedule_kind: string | null;
  config: Record<string, string | number | boolean>;
  query_mode: string;
  query_batch_size: number;
  query_info: SourceQueryInfo;
  posting_count?: number;
  managed?: boolean;
  tool_config_schema?: {
    type: "object";
    properties: Record<string, ConfigFieldSchema>;
    required?: string[];
  } | null;
  secret_hints: Record<string, SecretHint>;
  enabled: boolean;
  paused_at: string | null;
  last_status: string;
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
  capabilities?: { dynamic_queries?: boolean } & Record<string, unknown>;
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
    docs?: string;
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
  error?: { code: string; detail: { message?: string }; retryable: string } | null;
  latency_ms?: number;
};

export async function fetchSourceRuns(
  id: string,
  limit = 50,
): Promise<SourceRun[]> {
  const response = await api.get<SourceRun[]>(
    `/admin/postings/sources/${id}/runs?limit=${limit}`,
  );
  return response.data;
}

export type SourceRun = {
  id: string;
  trigger: "manual" | "scheduled";
  status: "ok" | "degraded" | "failed" | "skipped" | "running";
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number;
  items_synced: number;
  error: string;
  report?: {
    stage?: string;
    enriched?: number;
    detail_rows?: number;
    synced?: number;
    errors?: { code?: string; detail?: unknown }[];
  } | null;
};

export async function fetchAdminSources(): Promise<PostingSource[]> {
  const response = await api.get<PostingSource[]>("/admin/postings/sources");
  return response.data;
}

export async function deleteSource(
  id: string,
): Promise<{ id: string; key: string; deleted: boolean; postings_removed: number }> {
  const response = await api.delete(`/admin/postings/sources/${id}`);
  return response.data;
}

export async function fetchConnectorCatalog(): Promise<ConnectorCatalogEntry[]> {
  const response = await api.get<ConnectorCatalogEntry[]>("/admin/postings/connectors");
  return response.data;
}

export type ConnectorDocs = {
  markdown: string;
  tree: {
    version: number;
    categories: {
      category: string;
      title?: string;
      items: {
        id: string;
        file?: string;
        title?: string;
        description?: string;
        index?: boolean;
        audience?: "user" | "dev";
      }[];
    }[];
    i18n?: {
      defaultLocale?: string;
      locales?: Record<string, Record<string, string>>;
    };
  } | null;
};

export async function fetchConnectorDocs(
  key: string,
  file?: string,
): Promise<ConnectorDocs> {
  const params = file ? `?file=${encodeURIComponent(file)}` : "";
  const response = await api.get<ConnectorDocs>(
    `/admin/postings/connectors/${encodeURIComponent(key)}/documentation${params}`,
  );
  return response.data;
}

export async function createSource(payload: {
  key: string;
  connector_key: string;
  config: Record<string, string | number | boolean>;
  query_mode?: string;
  query_batch_size?: number;
  secrets?: Record<string, string>;
}): Promise<{ id: string; key: string; connector_key: string }> {
  const response = await api.post("/admin/postings/sources", payload);
  return response.data;
}

export async function updateSource(
  id: string,
  payload: {
    config?: Record<string, string | number | boolean>;
    query_mode?: string;
    query_batch_size?: number;
    secrets?: Record<string, string>;
    enabled?: boolean;
    paused?: boolean;
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
