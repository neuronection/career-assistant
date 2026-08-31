import { api } from "./client";
import type { Job, JobFamilyNode, JobGraph, Relation } from "@/types";

export async function fetchFamilyTree(): Promise<JobFamilyNode[]> {
  const { data } = await api.get<JobFamilyNode[]>("/jobs/tree");
  return data;
}

export async function fetchJobs(params: Record<string, unknown> = {}): Promise<Job[]> {
  const { data } = await api.get<Job[]>("/jobs", { params });
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

export async function suggestJobRelations(ref: string): Promise<Relation[]> {
  const { data } = await api.post(`/jobs/${ref}/relations/suggest`);
  return data;
}

export async function deleteJob(ref: string): Promise<void> {
  await api.delete(`/jobs/${ref}`);
}
