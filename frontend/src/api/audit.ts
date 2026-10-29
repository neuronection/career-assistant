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
}

export interface AuditBreakdown {
  dimension: "task" | "provider";
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

export async function fetchAuditOverview(window: AuditWindow): Promise<AuditOverview> {
  const { data } = await api.get<AuditOverview>("/admin/audit/overview", {
    params: { window },
  });
  return data;
}

export async function fetchAuditTimeseries(window: AuditWindow): Promise<AuditSeries> {
  const { data } = await api.get<AuditSeries>("/admin/audit/timeseries", {
    params: { window },
  });
  return data;
}

export async function fetchAuditBreakdown(
  dimension: "task" | "provider",
  window: AuditWindow,
): Promise<AuditBreakdown> {
  const { data } = await api.get<AuditBreakdown>("/admin/audit/breakdown", {
    params: { dimension, window },
  });
  return data;
}

export interface AuditEventsParams {
  group?: "all" | "auth" | "admin";
  outcome?: string;
  actor?: string;
  window?: AuditWindow;
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
  task?: string;
  provider?: string;
  model?: string;
  status?: string;
  user_id?: string;
  run_id?: string;
  tier?: string;
  window?: AuditWindow;
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
