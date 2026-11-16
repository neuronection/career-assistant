import axios from "axios";

import { api, apiDetail } from "@/api/client";

export type MappingFunnelState =
  | "mapped"
  | "ignored"
  | "detail_failed"
  | "no_description"
  | "detail_not_fetched"
  | "extract_failed"
  | "not_extracted"
  | "needs_review"
  | "semantic_unavailable"
  | "semantic_pending"
  | "no_skills"
  | "below_threshold"
  | "no_candidate"
  | "unmapped_by_admin"
  | "unknown";

export interface MappingOverview {
  active: number;
  described: number;
  extracted: number;
  mapped: number;
  accounted: { mapped: number; machine_terminal: number; human_terminal: number; total: number };
  states: Partial<Record<MappingFunnelState, number>>;
  gate: { floor: number; rate: number; pass: boolean };
  methods: Record<string, number>;
  reasons: Record<string, number>;
  proposals_pending: number;
  last_remap: {
    job_id: string;
    status: string;
    created_at: string | null;
    error: string | null;
  } | null;
  health: unknown;
}

export interface MappingCandidate {
  job_id: string;
  job_code: string;
  job_title?: string | null;
  deterministic: number | null;
  semantic: number | null;
  blend: number | null;
  shared_skills: string[];
}

export interface MappingQueueItem {
  id: string;
  ref: string;
  title: string;
  org: string;
  source_id: string;
  state: MappingFunnelState;
  outcome_reason: string | null;
  needs_review: boolean;
  detail_fetched: boolean;
  extract_version: number | null;
  mapped: boolean;
  catalog_job_id: string | null;
  mapping_margin: number | null;
  weak: boolean;
  top_candidate: MappingCandidate | null;
  proposal_state: string | null;
  review: { state: string; reason: string | null; note: string | null } | null;
  created_at: string | null;
}

export interface MappingQueueResponse {
  items: MappingQueueItem[];
  total: number;
  states: Partial<Record<MappingFunnelState, number>>;
  next_cursor?: string;
}

export interface MappingQueueFilters {
  state?: MappingFunnelState | "";
  source?: string;
  needs_review?: boolean | "";
  detail_state?: "" | "missing" | "fetched";
  weak?: boolean | "";
  q?: string;
  cursor?: string;
  limit?: number;
}

export interface MappingTrace {
  posting: {
    id: string;
    ref: string;
    title: string;
    org: string;
    status: string;
    state: MappingFunnelState;
    created_at: string | null;
    catalog_job_id?: string | null;
  };
  outcome: {
    state: string | null;
    reason: string | null;
    method: string | null;
    confidence: number | null;
    reason_prose: string | null;
  };
  signals: Record<string, unknown>;
  features: {
    mapping_version: number | null;
    space_key: string | null;
    degraded: string | null;
    policy: Record<string, unknown> | null;
    candidates: MappingCandidate[];
  };
  proposal: {
    action: string | null;
    existing_job_code: string | null;
    proposal_version: number | null;
    needs_edit: boolean;
    job_type: string | null;
  } | null;
  proposal_state: string | null;
  proposal_failure: { reason: string; at: string | null } | null;
  last_extract: {
    status: string;
    at: string | null;
    error: string | null;
    pending: boolean;
  } | null;
  review: {
    state: string;
    reason: string | null;
    note: string | null;
    actor: string | null;
    at: string | null;
  } | null;
  review_row: { id: string; kind: string; status: string } | null;
  extract_version: number | null;
  needs_review: boolean;
  detail_fetched_at: string | null;
  journal: {
    id: string;
    actor_kind: string;
    operation: Record<string, unknown> | null;
    created_at: string | null;
  }[];
  ai_generation_ids: string[];
}

export interface MappingBulkResult {
  affected?: number;
  missing?: string[];
  ignored?: string[];
  unignored?: string[];
  unmapped?: string[];
  reviewed?: string[];
  mapped?: string[];
  already?: string[];
  blocked?: Record<string, string>;
  queued?: number;
  skipped?: number;
  requested?: number;
}

export interface MappingDetailNowResult {
  posting_id: string;
  fetched: number;
  changed: boolean;
  extract_requeued?: boolean;
  errors?: Array<Record<string, unknown>>;
}

export interface MappingReproposeResult {
  queued: boolean;
  job_id: string;
}

export async function fetchMappingsQueue(
  filters: MappingQueueFilters = {},
): Promise<MappingQueueResponse> {
  const params: Record<string, unknown> = { ...filters };
  for (const key of Object.keys(params)) {
    const value = params[key];
    if (value === "" || value === undefined || value === null) delete params[key];
  }
  const { data } = await api.get<MappingQueueResponse>("/admin/mappings/unmapped", { params });
  return data;
}

export async function fetchMappingsTrace(postingId: string): Promise<MappingTrace> {
  const { data } = await api.get<MappingTrace>(`/admin/mappings/postings/${postingId}/trace`);
  return data;
}

async function bulk(
  path: string,
  postingIds: string[],
  extra: Record<string, unknown> = {},
): Promise<MappingBulkResult> {
  const { data } = await api.post<MappingBulkResult>(path, {
    posting_ids: postingIds,
    ...extra,
  });
  return data;
}

export const mappingsIgnore = (ids: string[], reason: string, note: string) =>
  bulk("/admin/mappings/ignore", ids, { reason, note });

export const mappingsUnignore = (ids: string[]) =>
  bulk("/admin/mappings/unignore", ids);

export const mappingsUnmap = (ids: string[]) => bulk("/admin/mappings/unmap", ids);

export const mappingsReview = (ids: string[], note: string) =>
  bulk("/admin/mappings/review", ids, { note });

export const mappingsExtract = (ids: string[]) => bulk("/admin/mappings/extract", ids);

export const mappingsRedecide = (ids: string[]) => bulk("/admin/mappings/redecide", ids);

export async function mappingsFetchDetail(id: string): Promise<MappingDetailNowResult> {
  const { data } = await api.post<MappingDetailNowResult>(
    `/admin/mappings/postings/${id}/detail`,
  );
  return data;
}

export async function mappingsRepropose(id: string): Promise<MappingReproposeResult> {
  const { data } = await api.post<MappingReproposeResult>(
    `/admin/mappings/postings/${id}/repropose`,
  );
  return data;
}

export async function mappingsMapBulk(
  postingIds: string[],
  jobId: string,
): Promise<MappingBulkResult> {
  const { data } = await api.post<MappingBulkResult>("/admin/mappings/map-bulk", {
    posting_ids: postingIds,
    job_id: jobId,
  });
  return data;
}

export type MappingRedecideScope = "stale" | "all";

export async function mappingsRedecideAll(
  scope: MappingRedecideScope = "stale",
): Promise<{
  queued: boolean;
  job_id: string;
  scope: MappingRedecideScope;
  active: number;
}> {
  const { data } = await api.post<{
    queued: boolean;
    job_id: string;
    scope: MappingRedecideScope;
    active: number;
  }>("/admin/mappings/redecide-all", { scope });
  return data;
}

export async function mappingsMap(
  postingId: string,
  jobId: string,
): Promise<{ id: string; status: string; mapping_method: string | null; catalog_job_id: string }> {
  const { data } = await api.post("/admin/mappings/map", {
    posting_id: postingId,
    job_id: jobId,
  });
  return data;
}

export function mappingActionError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      return String((detail as { message: unknown }).message);
    }
  }
  return apiDetail(error);
}

export interface SourceBreakdown {
  source_id: string;
  key: string;
  title: string;
  kind: string;
  detail_mode: string;
  paused: boolean;
  active: number;
  described: number;
  extracted: number;
  mapped: number;
  accounted: number;
  states: Partial<Record<MappingFunnelState, number>>;
  reasons: Record<string, number>;
  last_run_at: string | null;
}

export interface JobTypeRow {
  job_id: string;
  code: string;
  title: string;
  family: string | null;
  mapped_postings: number;
  open_roles: number;
  zero_postings: boolean;
}

export interface JobTypesBreakdown {
  items: JobTypeRow[];
  proposal_clusters: { job_type: string; postings: number }[];
}

export async function fetchSourcesBreakdown(): Promise<{ items: SourceBreakdown[] }> {
  const { data } = await api.get<{ items: SourceBreakdown[] }>("/admin/mappings/sources");
  return data;
}

export async function fetchJobTypesBreakdown(): Promise<JobTypesBreakdown> {
  const { data } = await api.get<JobTypesBreakdown>("/admin/mappings/job-types");
  return data;
}

export interface MappingSwitches {
  job_proposals: boolean;
  semantic_rescue: boolean;
  semantic_rerank: boolean;
}

export interface MappingOverviewWithSwitches extends MappingOverview {
  switches: MappingSwitches;
}

export async function fetchMappingsOverview(): Promise<MappingOverviewWithSwitches> {
  const { data } = await api.get<MappingOverviewWithSwitches>("/admin/mappings/overview");
  return data;
}

export interface MappingQualityMetrics {
  resolved: number;
  precision: number | null;
  recall: number | null;
  agreement: number | null;
}

export interface MappingQuality {
  golden: MappingQualityMetrics;
  sample: MappingQualityMetrics;
  confusion: { predicted: string; expected: string; count: number }[];
  weak: {
    count: number;
    margin_floor: number;
    semantic_floor: number;
    empty_until_sweep: boolean;
  };
  gate: {
    min_golden: number;
    precision_floor: number;
    pass: boolean;
    state: "pass" | "fail" | "no-golden";
  };
  pending: {
    id: string;
    kind: string;
    status: string;
    expected_job_id: string | null;
    note: string;
    posting: {
      id: string;
      ref: string;
      title: string;
      state_kind: string | null;
      catalog_job_id: string | null;
    };
    created_at: string | null;
  }[];
}

export async function fetchMappingsQuality(): Promise<MappingQuality> {
  const { data } = await api.get<MappingQuality>("/admin/mappings/quality");
  return data;
}

export async function mappingsGolden(
  postingId: string,
  expectedJobId: string | null,
  note = "",
): Promise<{ id: string; kind: string; status: string }> {
  const { data } = await api.post("/admin/mappings/quality/golden", {
    posting_id: postingId,
    expected_job_id: expectedJobId,
    note,
  });
  return data;
}

export async function mappingsSample(
  count: number,
): Promise<{ created: number; ids: string[] }> {
  const { data } = await api.post("/admin/mappings/quality/sample", { count });
  return data;
}

export async function mappingsResolve(
  reviewId: string,
  correct: boolean,
  note = "",
): Promise<{ id: string; status: string }> {
  const { data } = await api.post(`/admin/mappings/quality/reviews/${reviewId}/resolve`, {
    correct,
    note,
  });
  return data;
}

export interface MappingPolicy {
  tau_job: number;
  delta: number;
  semantic_threshold: number;
  semantic_min_shared_skills: number;
  blend_deterministic: number;
  blend_semantic: number;
  k: number;
  policy_hash: string;
}

export interface MappingPolicyDraft {
  tau_job?: number | null;
  delta?: number | null;
  semantic_threshold?: number | null;
  semantic_min_shared_skills?: number | null;
}

export interface MappingDryRunResult {
  policy: MappingPolicyDraft;
  policy_hash: string;
  degraded_semantic: boolean;
  scanned: number;
  results: {
    posting_id: string;
    before: { state: string | null; reason: string | null };
    after: {
      state: string;
      reason: string | null;
      confidence: number | null;
      catalog_job_id: string | null;
    };
    changed: boolean;
  }[];
}

export async function fetchMappingsPolicy(): Promise<MappingPolicy> {
  const { data } = await api.get<MappingPolicy>("/admin/mappings/policy");
  return data;
}

export async function saveMappingsPolicy(
  draft: MappingPolicyDraft,
): Promise<{ policy_hash: string }> {
  const { data } = await api.put("/admin/mappings/policy", draft);
  return data;
}

export async function dryRunMappingsPolicy(
  draft: MappingPolicyDraft,
  postingIds: string[],
): Promise<MappingDryRunResult> {
  const { data } = await api.post("/admin/mappings/policy/dry-run", {
    ...draft,
    posting_ids: postingIds,
  });
  return data;
}

export interface MappingTrendPoint {
  captured_at: string | null;
  basis: string;
  total: number;
  described: number;
  extracted: number;
  mapped: number;
  accounted: number;
  machine_terminal: number;
  human_terminal: number;
  reasons: Record<string, number>;
  policy_hash: string | null;
}

export async function fetchMappingsTrend(limit = 30): Promise<{ items: MappingTrendPoint[] }> {
  const { data } = await api.get<{ items: MappingTrendPoint[] }>("/admin/mappings/trend", {
    params: { limit },
  });
  return data;
}

export async function mappingsCaptureSnapshot(): Promise<{
  snapshot_id: string;
  total: number;
  accounted: number;
}> {
  const { data } = await api.post("/admin/mappings/snapshot");
  return data;
}

export interface MappingAlerts {
  coverage_floor: number;
}

export async function fetchMappingsAlerts(): Promise<MappingAlerts> {
  const { data } = await api.get<MappingAlerts>("/admin/mappings/alerts");
  return data;
}

export async function saveMappingsAlerts(coverageFloor: number): Promise<MappingAlerts> {
  const { data } = await api.put<MappingAlerts>("/admin/mappings/alerts", {
    coverage_floor: coverageFloor,
  });
  return data;
}
