import { api } from "./client";

export interface AuditAiStats {
  calls: number;
  errors: number;
  error_rate: number;
  tokens_in: number;
  tokens_out: number;
  avg_latency_ms: number | null;
  max_latency_ms: number | null;
  prev_calls: number;
  prev_errors: number;
}

export interface AuditFailure {
  stream: "ai" | "job" | "auth";
  title: string;
  detail: string;
  occurred_at: string;
}

export interface AuditOverview {
  window: AuditWindow;
  ai: AuditAiStats;
  jobs: { failed: number; running: number; queued: number };
  schedules: { failing: number };
  auth: { events: number; denied: number };
  recent_failures: AuditFailure[];
}

export type AuditWindow = "24h" | "7d" | "30d";

export interface AuditPoint {
  bucket: string;
  calls: number;
  errors: number;
  tokens_in: number;
  tokens_out: number;
}

export interface AuditSeries {
  window: AuditWindow;
  bucket: "hour" | "day";
  points: AuditPoint[];
}

export interface AuditBreakdownRow {
  key: string;
  calls: number;
  errors: number;
  tokens_in: number;
  tokens_out: number;
  avg_latency_ms?: number | null;
}

export interface AuditBreakdown {
  dimension: "task" | "provider" | "model";
  window: AuditWindow;
  rows: AuditBreakdownRow[];
}

export interface AuditEventRow {
  id: string;
  action: string;
  actor: string;
  actor_email: string | null;
  resource: string;
  outcome: string;
  created_at: string;
}

export interface AIGenerationRow {
  id: string;
  task_type: string;
  provider: string;
  model: string;
  prompt: string;
  output: Record<string, unknown> | null;
  tokens_in: number | null;
  tokens_out: number | null;
  latency_ms: number | null;
  status: string;
  error: string;
  task_tier: string | null;
  prompt_version: string | null;
  pack_key: string | null;
  pack_version: number | null;
  run_id: string | null;
  run_stage: string | null;
  user_id: string | null;
  created_at: string;
}

export interface AuditRangeQuery {
  window?: AuditWindow;
  from?: string;
  to?: string;
}

export async function fetchAuditOverview(
  params: AuditRangeQuery = {},
): Promise<AuditOverview> {
  const { data } = await api.get<AuditOverview>("/admin/audit/overview", { params });
  return data;
}

export async function fetchAuditTimeseries(
  params: AuditRangeQuery = {},
): Promise<AuditSeries> {
  const { data } = await api.get<AuditSeries>("/admin/audit/timeseries", { params });
  return data;
}

export async function fetchAuditBreakdown(
  dimension: "task" | "provider" | "model",
  params: AuditRangeQuery & { limit?: number } = {},
): Promise<AuditBreakdown> {
  const { data } = await api.get<AuditBreakdown>("/admin/audit/breakdown", {
    params: { dimension, ...params },
  });
  return data;
}

export interface AuditEventsParams {
  group?: "all" | "auth" | "admin" | "vector";
  outcome?: string;
  actor?: string;
  window?: AuditWindow;
  from?: string;
  to?: string;
  limit?: number;
  offset?: number;
}

export async function fetchAuditEvents(
  params: AuditEventsParams = {},
): Promise<{ total: number; items: AuditEventRow[] }> {
  const { data } = await api.get<{ total: number; items: AuditEventRow[] }>(
    "/admin/audit/events",
    { params },
  );
  return data;
}

export interface GenerationParams {
  id?: string;
  task?: string;
  provider?: string;
  model?: string;
  status?: string;
  user_id?: string;
  run_id?: string;
  tier?: string;
  window?: AuditWindow;
  from?: string;
  to?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export async function fetchAuditGenerations(
  params: GenerationParams = {},
): Promise<{ total: number; items: AIGenerationRow[] }> {
  const { data } = await api.get<{ total: number; items: AIGenerationRow[] }>(
    "/admin/audit/ai/generations",
    { params },
  );
  return data;
}

export interface AuditJobRow {
  id: string;
  job_type: string;
  status: string;
  stage: string | null;
  progress: number | null;
  attempts: number;
  max_attempts: number;
  error: string;
  created_at: string;
  finished_at: string | null;
  user_id: string | null;
  user_email: string | null;
  payload: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
}

export interface AuditJobFacet {
  key: string;
  count: number;
}

export interface JobParams {
  status?: string;
  job_type?: string;
  user_id?: string;
  window?: AuditWindow;
  from?: string;
  to?: string;
  limit?: number;
  offset?: number;
}

export async function fetchAuditJobs(
  params: JobParams = {},
): Promise<{ total: number; items: AuditJobRow[] }> {
  const { data } = await api.get<{ total: number; items: AuditJobRow[] }>(
    "/admin/audit/jobs",
    { params },
  );
  return data;
}

export async function fetchAuditJobFacets(
  params: Pick<JobParams, "window" | "from" | "to"> = {},
): Promise<{ rows: AuditJobFacet[] }> {
  const { data } = await api.get<{ rows: AuditJobFacet[] }>(
    "/admin/audit/jobs/facets",
    { params },
  );
  return data;
}

export interface AuditFailureGroup {
  job_type: string;
  window_count: number;
  top_error: string;
  est_jobs: number;
  full_rerun: boolean;
  sweep: boolean;
}

export interface AuditFailuresPreview {
  groups: AuditFailureGroup[];
  cap: number;
  total_failed: number;
  truncated: number;
  skipped_dup_preview: number;
}

export interface AuditRequeueItem {
  job_id: string;
  outcome: string;
  new_job_id: string | null;
}

export interface AuditRequeueOutcome {
  requeued: number;
  skipped_dup: number;
  skipped_cap: number;
  collapsed: number;
  cap: number;
  items: AuditRequeueItem[];
}

export interface FailureParams {
  job_type?: string;
  user_id?: string;
  window?: AuditWindow;
  from?: string;
  to?: string;
}

export async function fetchAuditFailures(
  params: FailureParams = {},
): Promise<AuditFailuresPreview> {
  const { data } = await api.get<AuditFailuresPreview>(
    "/admin/audit/jobs/failures",
    { params },
  );
  return data;
}

export async function requeueAuditJobs(
  body: FailureParams & { job_ids?: string[]; confirm: boolean },
): Promise<AuditFailuresPreview | AuditRequeueOutcome> {
  const { data } = await api.post<
    AuditFailuresPreview | AuditRequeueOutcome
  >("/admin/audit/jobs/requeue", body);
  return data;
}

export interface AuditSourceRunRow {
  id: string;
  source_id: string;
  source_key: string | null;
  connector_key: string | null;
  trigger: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number;
  items_synced: number;
  error: string;
}

export async function fetchAuditSourceRuns(
  params: {
    status?: string;
    trigger?: string;
    window?: AuditWindow;
    from?: string;
    to?: string;
    limit?: number;
    offset?: number;
  } = {},
): Promise<{ total: number; items: AuditSourceRunRow[] }> {
  const { data } = await api.get<{ total: number; items: AuditSourceRunRow[] }>(
    "/admin/audit/source-runs",
    { params },
  );
  return data;
}

export interface AuditChangeRow {
  id: string;
  occurred_at: string;
  actor_kind: string;
  outcome?: string;
  event?: string;
  posting_id?: string;
  duration_ms?: number | null;
  skill_key?: string;
  skill_label?: string;
  actor_ref: Record<string, unknown> | null;
  operation?: Record<string, unknown> | null;
  diff?: Record<string, unknown> | null;
  detail?: Record<string, unknown> | null;
}

export async function fetchAuditChanges(
  params: {
    entity: "postings" | "skills";
    actor_kind?: string;
    outcome?: string;
    event?: string;
    window?: AuditWindow;
    from?: string;
    to?: string;
    limit?: number;
    offset?: number;
  },
): Promise<{ entity: string; total: number; items: AuditChangeRow[] }> {
  const { data } = await api.get<{
    entity: string;
    total: number;
    items: AuditChangeRow[];
  }>("/admin/audit/changes", { params });
  return data;
}

export interface AuditProduction {
  postings: {
    ingested: number;
    by_status: Record<string, number>;
    ingested_items: number;
    activity: Record<string, number>;
  };
  skills: Record<string, number>;
  companies: { created: number; by_source: Record<string, number> };
  catalog_jobs: {
    created: number;
    by_status: Record<string, number>;
    by_source: Record<string, number>;
  };
}

export async function fetchAuditProduction(
  params: AuditRangeQuery = {},
): Promise<AuditProduction> {
  const { data } = await api.get<AuditProduction>("/admin/audit/production", {
    params,
  });
  return data;
}

export async function exportAuditCsv(
  stream:
    | "ai"
    | "events"
    | "jobs"
    | "source_runs"
    | "changes",
  params: {
    window?: AuditWindow;
    from?: string;
    to?: string;
    task?: string;
    provider?: string;
    status?: string;
    q?: string;
    group?: "all" | "auth" | "admin";
    outcome?: string;
    actor?: string;
    job_type?: string;
    actor_kind?: string;
    trigger?: string;
    entity?: "postings" | "skills";
    event?: string;
  } = {},
): Promise<Blob> {
  const response = await api.get(`/admin/audit/export`, {
    params: { stream, ...params },
    responseType: "blob",
  });
  return response.data as Blob;
}
