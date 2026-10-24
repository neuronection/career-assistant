import { api } from "@/api/client";
import type { CareerPath, PathDetail, PathGraph } from "@/types/wire";

export interface PathIndexFilters {
  job?: string;
  family?: string;
  stage?: string;
}

export async function fetchPaths(filters: PathIndexFilters = {}): Promise<CareerPath[]> {
  const { data } = await api.get<CareerPath[]>("/paths", { params: filters });
  return data;
}

export async function fetchPathDetail(pathId: string): Promise<PathDetail> {
  const { data } = await api.get<PathDetail>(`/paths/${pathId}`);
  return data;
}

export async function setPathFlag(
  pathId: string,
  payload: { step_id?: string | null; flag: string | null; note?: string },
): Promise<PathDetail> {
  const { data } = await api.put<PathDetail>(`/paths/${pathId}/flags`, payload);
  return data;
}

export async function fetchJobPaths(
  jobRef: string,
  includeDrafts = false,
): Promise<CareerPath[]> {
  const { data } = await api.get<CareerPath[]>(`/jobs/${jobRef}/paths`, {
    params: { include_drafts: includeDrafts },
  });
  return data;
}

export async function fetchJobPathGraph(jobRef: string): Promise<PathGraph> {
  const { data } = await api.get<PathGraph>(`/jobs/${jobRef}/paths/graph`);
  return data;
}
