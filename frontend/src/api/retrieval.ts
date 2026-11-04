import axios from "axios";

import { api, apiDetail } from "@/api/client";

export type RetrievalWindow = "24h" | "7d" | "30d" | "90d";
export type RetrievalGate = "pass" | "fail" | "unknown";
export type RetrievalRunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";
export type RetrievalSpaceStatus = "active" | "building" | "retired";

export interface RetrievalBackend {
  name: string;
  label: string;
  dialect: string;
  semantic_available: boolean;
}

export type RetrievalTokenizerSource =
  | "provider"
  | "curated"
  | "admin"
  | "fallback";

export interface RetrievalSpaceTokenizer {
  kind: "tiktoken" | "hf_tokenizers" | "sentencepiece" | "heuristic";
  identifier: string;
  revision: string | null;
  artifact_sha256: string | null;
  exact: boolean;
  max_input_tokens: number;
  source: RetrievalTokenizerSource | null;
}

export interface RetrievalSpaceChunk {
  max_chunk_tokens: number;
  overlap_tokens: number;
  max_chars: number;
}

export interface RetrievalSpace {
  space_id: string;
  name: string;
  status: RetrievalSpaceStatus;
  provider: string;
  model: string;
  dim: number;
  backend: string;
  metric: string;
  index_table: string | null;
  documents: number;
  records: number;
  coverage: number | null;
  stale: number | null;
  failed: number | null;
  created_at: string | null;
  activated_at: string | null;
  retired_at: string | null;
  last_reindex_at: string | null;
  last_error: string | null;
  gate: RetrievalGate;
  as_of: string | null;
  token_aware: boolean;
  tokenizer: RetrievalSpaceTokenizer | null;
  chunk: RetrievalSpaceChunk | null;
}

export interface RetrievalSpacesResponse {
  state: "ok" | "empty";
  count: number;
  spaces: RetrievalSpace[];
  backend: RetrievalBackend;
}

export type RetrievalDocumentState =
  | "current"
  | "stale"
  | "missing"
  | "incomplete"
  | "off";

export interface RetrievalDocumentStatus {
  source_id: string;
  state: RetrievalDocumentState;
  reason: string | null;
  records: number;
  indexed_at: string | null;
}

export interface RetrievalDocumentSpace {
  space_id: string;
  name: string;
  status: RetrievalSpaceStatus;
  backend: string;
  model: string;
  dim: number;
}

export interface RetrievalDocumentStatusResponse {
  kind: string;
  space: RetrievalDocumentSpace | null;
  documents: RetrievalDocumentStatus[];
}

export interface RetrievalHealthSpace {
  space_id: string;
  name: string;
  status: RetrievalSpaceStatus;
  backend: string;
  index_table: string | null;
  differs_from_process_backend: boolean;
  ok: boolean;
  detail: string;
}

export interface RetrievalHealth {
  ok: boolean;
  dialect: string;
  backend: string;
  semantic_available: boolean;
  extension: Record<string, unknown> | null;
  capabilities: {
    ann: boolean;
    max_dim: number;
    max_recommended_rows: number;
    scope_enforcement: string;
  };
  spaces: RetrievalHealthSpace[];
  detail: string;
}

export interface RetrievalTokenizerSample {
  language: string;
  label: string;
  chars: number;
  tokens: number;
  chars_per_token: number;
}

export interface RetrievalTokenizerBucket {
  documents: number;
  records: number;
  chars: number;
  tokens: number;
  chars_per_token: number;
  max_record_tokens: number;
  records_over_limit: number;
  failed_documents: number;
}

export interface RetrievalModelProfile {
  provider_class: string;
  model: string;
  source: "curated" | "admin" | "fallback";
  exact: boolean;
  override: boolean;
  identity: string;
  counted_identity: string;
  tokenizer_available: boolean;
  tokenizer_kind: "tiktoken" | "hf_tokenizers" | "sentencepiece" | "heuristic";
  tokenizer_identifier: string;
  tokenizer_revision: string | null;
  tokenizer_artifact_sha256: string | null;
  max_input_tokens: number;
  max_input_assumed: boolean;
  degraded_reason: string | null;
  family: string | null;
  license: string | null;
  source_url: string | null;
  repository: string | null;
  preset_revision: string | null;
  usable: boolean;
  usable_reason: string | null;
  batch_max_items: number;
  batch_max_tokens: number;
  chunk: {
    max_chunk_tokens: number;
    overlap_tokens: number;
    max_chars: number;
  };
  updated_by: string | null;
  updated_at: string | null;
}

export interface RetrievalUnavailablePreset {
  family: string;
  repository: string;
  revision: string;
  license: string;
  source_url: string;
  max_input_tokens: number;
  models: string[];
  usable: boolean;
  usable_reason: string | null;
}

export interface RetrievalModelProfileBounds {
  max_provider_class_length: number;
  max_model_length: number;
  max_identifier_length: number;
  max_revision_length: number;
  max_input_tokens: number;
  max_batch_items: number;
  max_batch_tokens: number;
  max_chunk_tokens: number;
  max_chunk_chars: number;
  supported_kinds: string[];
  supported_tiktoken_identifiers: string[];
  hf_tokenizer_filename: string;
  max_tokenizer_json_bytes: number;
  requires_pinned_revision: boolean;
}

export interface RetrievalModelProfilesResponse {
  state: "ok";
  requested: { provider_class: string; model: string } | null;
  assigned: { provider: string; model: string } | null;
  resolution: RetrievalModelProfile;
  curated: RetrievalModelProfile[];
  unavailable_presets: RetrievalUnavailablePreset[];
  overrides: RetrievalModelProfile[];
  bounds: RetrievalModelProfileBounds;
  token_aware_writes: boolean;
}

export interface RetrievalTokenizerFetchPayload {
  repository: string;
  revision: string;
  files?: string[];
  expected_sha256?: string;
}

export interface RetrievalTokenizerFetch {
  state: "ok";
  job_id: string;
  job_type: string;
  status: RetrievalRunStatus;
  progress: number;
  stage: string | null;
  requested: RetrievalTokenizerFetchPayload;
  deduplicated: boolean;
  idempotency_key: string | null;
}

export interface RetrievalTokenizerFetchStatus {
  state: "ok";
  job_id: string;
  status: RetrievalRunStatus;
  progress: number;
  stage: string | null;
  heartbeat_at: string | null;
  error: string | null;
  result: {
    repository: string;
    revision: string;
    filename: string;
    sha256: string;
    size_bytes: number;
    cached: boolean;
    files: Record<string, number>;
  } | null;
  requested: RetrievalTokenizerFetchPayload;
  created_at: string | null;
  finished_at: string | null;
}

export interface RetrievalModelProfilePayload {
  provider_class: string;
  model: string;
  tokenizer_kind: string;
  tokenizer_identifier: string;
  tokenizer_revision?: string;
  tokenizer_artifact_sha256?: string;
  max_input_tokens: number;
  batch_max_items: number;
  batch_max_tokens: number;
  chunk_max_tokens: number;
  chunk_overlap_tokens: number;
  chunk_max_chars: number;
}

export interface RetrievalModelProfileSaveResponse {
  state: "ok";
  profile: RetrievalModelProfile;
  token_aware_writes: boolean;
}

export interface RetrievalModelProfileDeleteResponse {
  state: "ok";
  deleted: boolean;
  resolution: RetrievalModelProfile;
  token_aware_writes: boolean;
}

export interface RetrievalTokenizerReport {
  state: "ok" | "unconfigured";
  model: {
    provider: string;
    model: string;
    max_input_assumed: boolean;
  };
  tokenizer: {
    kind: "tiktoken" | "hf_tokenizers" | "sentencepiece" | "heuristic";
    identifier: string;
    revision: string | null;
    artifact_sha256: string | null;
    exact: boolean;
    source: "provider" | "curated" | "admin" | "fallback";
    identity: string;
    max_input_tokens: number;
    max_input_assumed: boolean;
    degraded_reason: string | null;
  };
  profile: RetrievalModelProfile;
  chunking: {
    view: string;
    max_chunk_chars: number;
    overlap_chars: number | null;
    chunker_version: string;
    composer_version: string;
    token_aware: boolean;
    max_chunk_tokens: number | null;
    overlap_tokens: number | null;
    tokenizer_source: RetrievalTokenizerSource | null;
  };
  reference: {
    state: "ok" | "empty";
    samples: RetrievalTokenizerSample[];
    total_chars: number;
    total_tokens: number;
    chars_per_token: number;
    exact: boolean;
    degraded_reason: string | null;
  };
  corpus: RetrievalTokenizerBucket & {
    state: "ok" | "empty";
    limit_per_kind: number;
    kinds: (RetrievalTokenizerBucket & { kind: string })[];
    exact: boolean;
  };
  shadow: { writes: false };
}

export interface RetrievalCoverageStats {
  space_id: string;
  as_of: string | null;
  total: number;
  missing: number;
  stale: number;
  failed: number;
  embedded: number;
  coverage: number | null;
  gate: RetrievalGate;
  ann_recall: number | null;
  ann_recall_k: number | null;
  probe_size: number | null;
}

export interface RetrievalCoverage {
  state: "never_reconciled" | "ok";
  space_id: string;
  name: string;
  coverage: RetrievalCoverageStats;
  kinds: { kind: string; coverage: RetrievalCoverageStats }[];
  document_kinds: string[];
  missing_kinds: string[];
  ann_sampled: boolean;
  as_of: string | null;
}

export interface RetrievalQualityQueryResult {
  query_id: string;
  expected_document_ids: string[];
  retrieved_document_ids: string[];
  recall_at_k: number;
  precision_at_k: number;
  missing_document_ids: string[];
  passed: boolean;
}

export interface RetrievalQualityBlock {
  space_id: string;
  set_version: number;
  k: number;
  recall_at_k: number;
  precision_at_k: number;
  passed: boolean;
  queries: RetrievalQualityQueryResult[];
  floor_recall: number;
  floor_precision: number;
  generated_at: string | null;
}

export interface RetrievalQualitySet {
  space_id: string;
  set_version: number;
  k: number;
  floor_recall: number;
  floor_precision: number;
  query_count: number;
  query_ids: string[];
  revision_key: string;
}

export interface RetrievalQualityCompare {
  old_space_id: string;
  new_space_id: string;
  set_version: number;
  k: number;
  old_recall_at_k: number;
  old_precision_at_k: number;
  new_recall_at_k: number;
  new_precision_at_k: number;
  passed: boolean;
  floor_recall: number;
  floor_precision: number;
  required_for_activation: boolean;
  queries: RetrievalQualityQueryResult[];
  generated_at: string | null;
}

export interface RetrievalQuality {
  state: "ok" | "sampled" | "stale_compare" | "not_sampled" | "no_golden_set";
  space_id: string;
  name: string;
  sampled: boolean;
  set: RetrievalQualitySet | null;
  quality: RetrievalQualityBlock | null;
  compare?: RetrievalQualityCompare;
  activation_gate?: RetrievalGate;
  compare_run_id?: string;
  compare_set_version?: number;
  reason?: string;
  window: { preset: RetrievalWindow; start: string; end: string };
}

export interface RetrievalRunScope {
  kind: string | null;
  view: string | null;
  since: string | null;
}

export interface RetrievalRunProgress {
  phase: "queued" | "scanning" | "embedding" | "writing" | "done";
  processed_documents: number;
  total_documents: number;
  processed_chunks: number;
  pending_chunks: number;
  total_chunks: number | null;
  chunks_estimated: boolean;
  embedded_chunks: number;
  skipped_chunks: number;
  failed_chunks: number;
  embedded_documents: number;
  skipped_documents: number;
  failed_documents: number;
  tokens: number | null;
  tokens_estimated: boolean;
  embed_calls: number;
  exact_tokenizer: boolean;
  done: boolean;
}

export interface RetrievalRun {
  run_id: string;
  space_id: string;
  job_type: "VECTOR_REINDEX" | "VECTOR_CUTOVER" | "VECTOR_MAINTENANCE";
  status: RetrievalRunStatus;
  progress: number;
  stage: string | null;
  scope: RetrievalRunScope;
  budget_tokens: number | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  heartbeat_at: string | null;
  error: string | null;
  cancel_requested: boolean;
  idempotency_key: string | null;
  lock_key: string | null;
  progress_detail?: RetrievalRunProgress | null;
  token_aware: boolean;
  tokenizer: RetrievalSpaceTokenizer | null;
  chunk: RetrievalSpaceChunk | null;
}

export interface RetrievalRunsResponse {
  state: "ok" | "empty";
  window: { preset: RetrievalWindow; start: string; end: string };
  total: number;
  limit: number;
  offset: number;
  unattributed_runs: number;
  scan_truncated: boolean;
  runs: RetrievalRun[];
}

export interface RetrievalCoverageSnapshot {
  state: "never_reconciled" | "snapshot";
  coverage: number | null;
  total: number;
  embedded: number;
  stale: number | null;
  failed: number | null;
  as_of: string | null;
  ann_sampled: boolean;
}

export interface RetrievalOverview {
  state: "ok" | "empty";
  window: { preset: RetrievalWindow; start: string; end: string };
  spaces: { total: number; active: number; building: number; retired: number };
  backend: RetrievalBackend;
  documents: number;
  records: number;
  coverage: RetrievalCoverageSnapshot;
  queries: {
    count: number;
    p50_ms: number | null;
    p95_ms: number | null;
    zero_result_rate: number | null;
    degraded_rate: number | null;
    ann_sampled: boolean;
    latency_percentiles: string;
  };
  embed: { calls: number; errors: number; tokens_in: number; tokens_out: number };
  runs: {
    total: number;
    active: number;
    unattributed: number;
    scan_truncated: boolean;
    last_reindex_at: string | null;
    last_status: string | null;
  };
  changes: {
    state: "ok" | "empty";
    reason: string | null;
    count: number;
    recent: {
      action: string;
      actor: string;
      resource: string;
      outcome: string;
      created_at: string | null;
    }[];
  };
  window_end: string | null;
}

export interface RetrievalRunResult {
  scanned: number;
  embedded: number;
  skipped: number;
  failed: number;
  failed_ids: string[];
  failed_ids_truncated: boolean;
  gate: RetrievalGate;
}

export interface RetrievalActivationGate {
  space_id: string;
  coverage: RetrievalGate;
  quality: RetrievalGate;
  allowed: boolean;
  reasons: string[];
}

export interface RetrievalRunDetail {
  run: RetrievalRun;
  result: RetrievalRunResult | null;
  duration_seconds: number | null;
  action?: string;
  activation_gate?: RetrievalActivationGate | null;
  quality?: RetrievalQualityCompare | null;
}

export interface RetrievalRunDetailResponse {
  state: "ok" | "degraded";
  detail: RetrievalRunDetail;
  result_state: "ok" | "absent" | "invalid";
  failed_ids_limit: number;
}

export interface RetrievalQueryHealth {
  space_id: string;
  window_start: string;
  window_end: string;
  p50_ms: number | null;
  p95_ms: number | null;
  candidate_p50: number | null;
  candidate_p95: number | null;
  zero_result_rate: number | null;
  degraded_rate: number | null;
  degraded_reasons: Record<string, number>;
  per_view_hits: Record<string, number>;
  ann_recall: number | null;
  ann_recall_k: number | null;
  probe_size: number | null;
  sampled: boolean;
  sample_size: number;
  query_count: number;
}

export interface RetrievalQueryHealthResponse {
  state: "ok" | "empty" | "not_sampled";
  reason?: string | null;
  window: { preset: RetrievalWindow; start: string; end: string };
  query_health: RetrievalQueryHealth | null;
  candidates_avg: number | null;
  candidate_percentiles: "unavailable" | "not_sampled";
  latency_percentiles: "histogram_bucket_upper_bound" | "not_sampled";
}

export type RetrievalFailureKind =
  | "embed_provider"
  | "indexing"
  | "cutover_gate"
  | "maintenance";

export interface RetrievalFailureGroup {
  kind: RetrievalFailureKind;
  space_id: string;
  count: number;
  last_seen: string | null;
  document_ids: string[];
  reason: string | null;
  retryable: boolean;
  run_id: string | null;
}

export interface RetrievalFailuresResponse {
  state: "ok" | "empty";
  window: { preset: RetrievalWindow; start: string; end: string };
  groups: RetrievalFailureGroup[];
  truncated: boolean;
}

export interface RetrievalUsageRow {
  day: string;
  space_id: string;
  kind: string;
  calls: number;
  tokens_in: number;
  tokens_out: number;
  reindex_calls: number;
}

export interface RetrievalBudget {
  window: string;
  max_tokens: number;
  used_tokens: number;
}

export interface RetrievalUsage {
  window_start: string;
  window_end: string;
  rows: RetrievalUsageRow[];
  budget: RetrievalBudget | null;
}

export interface RetrievalUsageResponse {
  state: "ok" | "empty";
  window: { preset: RetrievalWindow; start: string; end: string };
  usage: RetrievalUsage;
  untagged_calls: number;
  groups_truncated: boolean;
  budget: { name: string; exhausted: boolean } | null;
  units: string;
}

export interface RetrievalActionResponse {
  action: string;
  accepted: boolean;
  audit_event: string;
  http_status: number;
  deduplicated: boolean;
  run_id: string | null;
  status: RetrievalRunStatus | null;
  idempotency_key: string | null;
  message: string;
  space_id?: string | null;
  target_run_id?: string;
  target_status?: RetrievalRunStatus;
  cancel_requested?: boolean;
  retry_of?: string;
  dry_run?: boolean;
  retry_count?: number;
  failed_ids_truncated?: boolean;
  source_run_id?: string;
  maintenance_action?: string;
  space?: Record<string, unknown>;
  quality?: RetrievalQualityCompare;
  baseline_space_id?: string;
  gate?: RetrievalGate;
  activation_gate?: {
    space_id: string;
    coverage: RetrievalGate;
    quality: RetrievalGate;
    allowed: boolean;
    reasons: string[];
  };
  coverage?: RetrievalCoverageStats;
  already_active?: boolean;
}

export interface RetrievalRefusal {
  action: string;
  accepted: false;
  audit_event: string;
  http_status: number;
  deduplicated: boolean;
  run_id: string | null;
  status: RetrievalRunStatus | null;
  idempotency_key: string | null;
  message: string;
  activation_gate?: RetrievalActionResponse["activation_gate"];
  quality?: RetrievalQualityCompare;
  coverage?: RetrievalCoverageStats;
}

export interface RetrievalActionErrorInfo {
  status: number;
  detail: string;
  payload: RetrievalRefusal | null;
}

export interface ReindexPayload {
  space: string;
  kind?: string;
  view?: string;
  since?: string;
  budget?: number;
  limit?: number;
  batch_size?: number;
  scan_limit?: number;
  force?: boolean;
  auto_continue?: boolean;
}

export interface BuildTokenizerPayload {
  kind: RetrievalSpaceTokenizer["kind"];
  identifier: string;
  revision?: string;
  artifact_sha256?: string;
  exact?: boolean;
  max_input_tokens: number;
  source?: RetrievalTokenizerSource;
}

export interface BuildChunkPayload {
  max_chunk_tokens: number;
  overlap_tokens?: number;
  max_chars: number;
}

export interface BuildSpacePayload {
  name: string;
  provider: string;
  model: string;
  dim: number;
  metric?: string;
  normalize?: boolean;
  query_prefix?: string;
  document_prefix?: string;
  tokenizer?: BuildTokenizerPayload;
  chunk?: BuildChunkPayload;
  tokenizer_profile?: { provider: string; model: string };
}

export type MaintenanceAction =
  | "index-rebuild"
  | "vacuum"
  | "orphan-sweep"
  | "retry-failed";

export interface MaintenancePayload {
  space: string;
  action: MaintenanceAction;
  dry_run?: boolean;
  limit?: number;
}

export interface QualityComparePayload {
  space: string;
  compare_space: string;
}

const IDEMPOTENT_HEADER = "Idempotency-Key";

/** A client-generated replay key for one mutating action. */
function newIdempotencyKey(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `retrieval-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function idempotentConfig(): { headers: Record<string, string> } {
  return { headers: { [IDEMPOTENT_HEADER]: newIdempotencyKey() } };
}

/** A 409 gate/state refusal carries the structured action payload; other
 * failures only carry `{detail}`. */
export function retrievalActionError(error: unknown): RetrievalActionErrorInfo {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status ?? 0;
    const data = error.response?.data;
    if (data && typeof data === "object" && "accepted" in data && "message" in data) {
      const payload = data as RetrievalRefusal;
      return { status, detail: payload.message, payload };
    }
    return { status, detail: apiDetail(error), payload: null };
  }
  return { status: 0, detail: String(error), payload: null };
}

export async function fetchRetrievalOverview(
  window: RetrievalWindow = "24h",
): Promise<RetrievalOverview> {
  const { data } = await api.get<RetrievalOverview>("/admin/retrieval/overview", {
    params: { window },
  });
  return data;
}

export async function fetchRetrievalSpaces(): Promise<RetrievalSpacesResponse> {
  const { data } = await api.get<RetrievalSpacesResponse>("/admin/retrieval/spaces");
  return data;
}

export async function fetchDocumentStatuses(
  kind: string,
  sourceIds: string[],
): Promise<RetrievalDocumentStatusResponse> {
  const { data } = await api.get<RetrievalDocumentStatusResponse>(
    "/admin/retrieval/documents/status",
    { params: { kind, source_ids: sourceIds.join(",") } },
  );
  return data;
}

export async function fetchRetrievalHealth(): Promise<RetrievalHealth> {
  const { data } = await api.get<RetrievalHealth>("/admin/retrieval/health");
  return data;
}

export async function fetchRetrievalTokenizer(): Promise<RetrievalTokenizerReport> {
  const { data } = await api.get<RetrievalTokenizerReport>(
    "/admin/retrieval/tokenizer",
  );
  return data;
}

export async function fetchRetrievalModelProfiles(
  params: { provider?: string; model?: string } = {},
): Promise<RetrievalModelProfilesResponse> {
  const { data } = await api.get<RetrievalModelProfilesResponse>(
    "/admin/retrieval/model-profiles",
    { params },
  );
  return data;
}

export async function saveRetrievalModelProfile(
  payload: RetrievalModelProfilePayload,
): Promise<RetrievalModelProfileSaveResponse> {
  const { data } = await api.put<RetrievalModelProfileSaveResponse>(
    "/admin/retrieval/model-profiles",
    payload,
  );
  return data;
}

export async function deleteRetrievalModelProfile(
  provider: string,
  model: string,
): Promise<RetrievalModelProfileDeleteResponse> {
  const { data } = await api.delete<RetrievalModelProfileDeleteResponse>(
    "/admin/retrieval/model-profiles",
    { params: { provider, model } },
  );
  return data;
}

export async function startRetrievalTokenizerFetch(
  payload: RetrievalTokenizerFetchPayload,
): Promise<RetrievalTokenizerFetch> {
  const { data } = await api.post<RetrievalTokenizerFetch>(
    "/admin/retrieval/tokenizer/fetch",
    payload,
    idempotentConfig(),
  );
  return data;
}

export async function fetchRetrievalTokenizerFetch(
  jobId: string,
): Promise<RetrievalTokenizerFetchStatus> {
  const { data } = await api.get<RetrievalTokenizerFetchStatus>(
    `/admin/retrieval/tokenizer/fetch/${jobId}`,
  );
  return data;
}

export async function fetchRetrievalCoverage(
  space: string,
): Promise<RetrievalCoverage> {
  const { data } = await api.get<RetrievalCoverage>("/admin/retrieval/coverage", {
    params: { space },
  });
  return data;
}

export async function fetchRetrievalQuality(
  space?: string,
  window?: RetrievalWindow,
): Promise<RetrievalQuality> {
  const { data } = await api.get<RetrievalQuality>("/admin/retrieval/quality", {
    params: { ...(space ? { space } : {}), ...(window ? { window } : {}) },
  });
  return data;
}

export async function fetchRetrievalRuns(
  params: {
    space?: string;
    kind?: string;
    status?: RetrievalRunStatus;
    limit?: number;
    offset?: number;
    window?: RetrievalWindow;
  } = {},
): Promise<RetrievalRunsResponse> {
  const { data } = await api.get<RetrievalRunsResponse>("/admin/retrieval/runs", {
    params,
  });
  return data;
}

export async function fetchRetrievalRun(
  runId: string,
): Promise<RetrievalRunDetailResponse> {
  const { data } = await api.get<RetrievalRunDetailResponse>(
    `/admin/retrieval/runs/${runId}`,
  );
  return data;
}

export async function fetchRetrievalQueryHealth(
  params: { space?: string; kind?: string; window?: RetrievalWindow } = {},
): Promise<RetrievalQueryHealthResponse> {
  const { data } = await api.get<RetrievalQueryHealthResponse>(
    "/admin/retrieval/query-health",
    { params },
  );
  return data;
}

export async function fetchRetrievalFailures(
  params: {
    space?: string;
    kind?: RetrievalFailureKind;
    window?: RetrievalWindow;
  } = {},
): Promise<RetrievalFailuresResponse> {
  const { data } = await api.get<RetrievalFailuresResponse>(
    "/admin/retrieval/failures",
    { params },
  );
  return data;
}

export async function fetchRetrievalUsage(
  params: { space?: string; kind?: string; window?: RetrievalWindow } = {},
): Promise<RetrievalUsageResponse> {
  const { data } = await api.get<RetrievalUsageResponse>("/admin/retrieval/usage", {
    params,
  });
  return data;
}

export async function reindexRetrievalSpace(
  payload: ReindexPayload,
): Promise<RetrievalActionResponse> {
  const { data } = await api.post<RetrievalActionResponse>(
    "/admin/retrieval/reindex",
    payload,
    idempotentConfig(),
  );
  return data;
}

export async function cancelRetrievalRun(
  runId: string,
): Promise<RetrievalActionResponse> {
  const { data } = await api.post<RetrievalActionResponse>(
    `/admin/retrieval/runs/${runId}/cancel`,
    {},
    idempotentConfig(),
  );
  return data;
}

export async function retryRetrievalRun(
  runId: string,
): Promise<RetrievalActionResponse> {
  const { data } = await api.post<RetrievalActionResponse>(
    `/admin/retrieval/runs/${runId}/retry`,
    {},
    idempotentConfig(),
  );
  return data;
}

export async function buildRetrievalSpace(
  payload: BuildSpacePayload,
): Promise<RetrievalActionResponse> {
  const { data } = await api.post<RetrievalActionResponse>(
    "/admin/retrieval/spaces",
    payload,
    idempotentConfig(),
  );
  return data;
}

export async function activateRetrievalSpace(
  spaceId: string,
): Promise<RetrievalActionResponse> {
  const { data } = await api.post<RetrievalActionResponse>(
    `/admin/retrieval/spaces/${spaceId}/activate`,
    {},
    idempotentConfig(),
  );
  return data;
}

export async function retireRetrievalSpace(
  spaceId: string,
  confirmSpaceName: string,
): Promise<RetrievalActionResponse> {
  const { data } = await api.post<RetrievalActionResponse>(
    `/admin/retrieval/spaces/${spaceId}/retire`,
    { confirm_space_name: confirmSpaceName },
    idempotentConfig(),
  );
  return data;
}

export async function dropRetrievalSpace(
  spaceId: string,
  confirmSpaceName: string,
  force = false,
): Promise<RetrievalActionResponse> {
  const { data } = await api.post<RetrievalActionResponse>(
    `/admin/retrieval/spaces/${spaceId}/drop`,
    { confirm_space_name: confirmSpaceName, force },
    idempotentConfig(),
  );
  return data;
}

export async function runRetrievalMaintenance(
  payload: MaintenancePayload,
): Promise<RetrievalActionResponse> {
  const { data } = await api.post<RetrievalActionResponse>(
    "/admin/retrieval/maintenance",
    payload,
    idempotentConfig(),
  );
  return data;
}

export async function compareRetrievalQuality(
  payload: QualityComparePayload,
): Promise<RetrievalActionResponse> {
  const { data } = await api.post<RetrievalActionResponse>(
    "/admin/retrieval/quality/compare",
    payload,
    idempotentConfig(),
  );
  return data;
}
