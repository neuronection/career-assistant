import { api } from "./client";
import type {
  Candidate,
  Job,
  JobMatchDetail,
  MatchInsight,
  MatchStatus,
  RankedJob,
} from "@/types";

export async function fetchCandidates(params: Record<string, unknown> = {}): Promise<Candidate[]> {
  const { data } = await api.get<Candidate[]>("/match/candidates", { params });
  return data;
}

export async function scoreJobs(body: {
  job_id?: string;
  family_key?: string;
  all_candidates?: boolean;
  limit?: number;
  force?: boolean;
}): Promise<MatchInsight[] | { job_id: string; status: string }> {
  const { data } = await api.post<MatchInsight[] | { job_id: string; status: string }>(
    "/match/score",
    body,
  );
  return data;
}

export async function fetchInsights(status?: MatchStatus): Promise<MatchInsight[]> {
  const { data } = await api.get<MatchInsight[]>("/match/insights", { params: { status } });
  return data;
}

export async function rateJob(body: {
  job_id: string;
  user_score?: number;
  status?: MatchStatus;
  notes?: string;
}): Promise<MatchInsight> {
  const { data } = await api.put<MatchInsight>("/match/rate", body);
  return data;
}

export async function fetchRankings(params: Record<string, unknown> = {}): Promise<{ items: RankedJob[]; total: number }> {
  const { data } = await api.get<{ items: RankedJob[]; total: number }>("/rankings", { params });
  return data;
}

export async function fetchJobMatchDetail(ref: string): Promise<JobMatchDetail> {
  const { data } = await api.get<JobMatchDetail>(`/jobs/${ref}/match`);
  return data;
}

export async function scoreJobForMe(job: Job): Promise<MatchInsight | null> {
  const result = await scoreJobs({ job_id: job.id });
  return Array.isArray(result) ? (result[0] ?? null) : null;
}

export async function saveScoringWeights(weights: {
  skills: number;
  location: number;
  experience: number;
  education: number;
  interests: number;
}): Promise<{ scoring_weights: typeof weights; refitted: number }> {
  const { data } = await api.put("/me/preferences/scoring", weights);
  return data;
}

export async function refitFit(body: { job_id?: string; all?: boolean }): Promise<{
  job_id?: string;
  fit_score?: number;
  breakdown?: unknown;
}> {
  const { data } = await api.post("/match/fit", body);
  return data;
}
