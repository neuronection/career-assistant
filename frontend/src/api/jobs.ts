import { api } from "@/api/client";
import type {
  Job,
  JobGraph,
  JobPostings,
  JobsPage,
  Relation,
  SimilarJobs,
} from "@/types/wire";
import type { JobFamilyNode } from "@/types";

export async function fetchFamilyTree(): Promise<JobFamilyNode[]> {
  const { data } = await api.get<JobFamilyNode[]>("/jobs/tree");
  return data;
}

export async function fetchJobs(params: Record<string, unknown> = {}): Promise<JobsPage> {
  const { data } = await api.get<JobsPage>("/jobs", { params });
  return data;
}

export async function fetchJob(ref: string): Promise<Job> {
  const { data } = await api.get<Job>(`/jobs/${ref}`);
  return data;
}

export async function fetchJobRelations(ref: string): Promise<Relation[]> {
  const { data } = await api.get<Relation[]>(`/jobs/relations/${ref}`);
  return data;
}

interface MatchPageParams {
  limit?: number;
  offset?: number;
}

/** Published catalog jobs nearest this job (plan 50 §7.3). */
export async function fetchSimilarJobs(
  ref: string,
  params: MatchPageParams = {},
): Promise<SimilarJobs> {
  const { data } = await api.get<SimilarJobs>(`/jobs/${ref}/similar`, { params });
  return data;
}

/** Live postings ranked against this catalog job, visibility-filtered. */
export async function fetchJobLivePostings(
  ref: string,
  params: MatchPageParams = {},
): Promise<JobPostings> {
  const { data } = await api.get<JobPostings>(`/jobs/${ref}/postings`, { params });
  return data;
}

export async function fetchGraph(params: Record<string, unknown> = {}): Promise<JobGraph> {
  const { data } = await api.get<JobGraph>("/jobs/graph", { params });
  return data;
}

export async function generateJobs(body: {
  mode: string;
  prompt?: string;
  criteria?: Record<string, unknown>;
  count: number;
}): Promise<{ job_id: string; status: string }> {
  const { data } = await api.post("/jobs/generate", body);
  return data;
}

export async function publishJob(ref: string): Promise<Job> {
  const { data } = await api.post(`/jobs/${ref}/publish`);
  return data;
}
