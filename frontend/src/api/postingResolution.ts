import { api } from "@/api/client";

export interface ResolutionThresholds {
  candidate_trigram_floor: number;
  candidate_cosine_floor: number;
  candidate_top_k: number;
  dedup_trigram_bar: number;
  dedup_cosine_bar: number;
  corroboration_min_postings: number;
  corroboration_cap: number;
}

export interface ResolutionRunSummary {
  job_id: string | null;
  status: string | null;
  created_at: string | null;
  finished_at: string | null;
  labels: number;
  exact_hits: number;
  pass2_matches: number;
  new_proposals: number;
  gate_blocks: number;
  degraded: boolean;
  replay: boolean;
}

export interface ResolutionRolling {
  window: string;
  runs: number;
  replay_runs: number;
  degraded_runs: number;
  labels: number;
  exact_hits: number;
  pass2_matches: number;
  new_proposals: number;
  gate_blocks: number;
  match_rate: number;
  new_rate: number;
  block_rate: number;
  replay_rate: number;
  degrade_rate: number;
}

export interface ResolutionStats {
  last_run: ResolutionRunSummary;
  rolling: ResolutionRolling;
  failing_schedules: number;
}

export interface ResolutionReplayReport {
  queued: number;
  skipped: number;
  missing: string[];
  requested: number;
}

export interface ReconcileQueuedReport {
  job_id: string;
  job_type: string;
  status: string;
}

export async function fetchResolutionThresholds(): Promise<ResolutionThresholds> {
  const { data } = await api.get<ResolutionThresholds>(
    "/admin/taxonomy/resolution/thresholds",
  );
  return data;
}

export async function saveResolutionThresholds(
  thresholds: ResolutionThresholds,
): Promise<ResolutionThresholds> {
  const { data } = await api.put<ResolutionThresholds>(
    "/admin/taxonomy/resolution/thresholds",
    thresholds,
  );
  return data;
}

export async function fetchResolutionStats(
  window: string,
): Promise<ResolutionStats> {
  const { data } = await api.get<ResolutionStats>("/admin/taxonomy/resolution/stats", {
    params: { window },
  });
  return data;
}

export async function replayPostingResolution(
  postingIds: string[],
): Promise<ResolutionReplayReport> {
  const { data } = await api.post<ResolutionReplayReport>("/admin/postings/replay", {
    posting_ids: postingIds,
  });
  return data;
}

/** Enqueue the store-wide reconcile for the skill documents (plan 50 P1d);
 * the worker embeds and reports through the job row, never inline. */
export async function reconcileSkillEmbeddings(
  limit: number,
): Promise<ReconcileQueuedReport> {
  const { data } = await api.post<ReconcileQueuedReport>("/admin/retrieval/reconcile", {
    kinds: ["skill"],
    limit,
  });
  return data;
}
