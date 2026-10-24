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

export interface PathStepPayload {
  kind: string;
  label: string;
  skill_key?: string | null;
  family_key?: string | null;
  education_level?: string | null;
  optional?: boolean;
  parent?: number | null;
  edge_label?: string;
}

export async function createPath(payload: {
  job_ref: string;
  title: string;
  description?: string;
  steps: PathStepPayload[];
}): Promise<PathDetail> {
  const { data } = await api.post<PathDetail>("/paths", payload);
  return data;
}

export async function forkPath(pathId: string): Promise<PathDetail> {
  const { data } = await api.post<PathDetail>(`/paths/${pathId}/fork`);
  return data;
}

export async function activatePath(pathId: string): Promise<PathDetail> {
  const { data } = await api.post<PathDetail>(`/paths/${pathId}/activate`);
  return data;
}

export async function updatePath(
  pathId: string,
  payload: { title?: string; description?: string },
): Promise<PathDetail> {
  const { data } = await api.patch<PathDetail>(`/paths/${pathId}`, payload);
  return data;
}

export async function deletePath(pathId: string): Promise<void> {
  await api.delete(`/paths/${pathId}`);
}

export async function addPathStep(
  pathId: string,
  payload: PathStepPayload & { parent_step_id?: string | null },
): Promise<PathDetail> {
  const { parent_step_id: parentStepId, ...step } = payload;
  const { data } = await api.post<PathDetail>(`/paths/${pathId}/steps`, step, {
    params: parentStepId ? { parent_step_id: parentStepId } : {},
  });
  return data;
}

export async function updatePathStep(
  pathId: string,
  stepId: string,
  payload: Partial<PathStepPayload>,
): Promise<PathDetail> {
  const { data } = await api.patch<PathDetail>(`/paths/${pathId}/steps/${stepId}`, payload);
  return data;
}

export async function deletePathStep(pathId: string, stepId: string): Promise<PathDetail> {
  const { data } = await api.delete<PathDetail>(`/paths/${pathId}/steps/${stepId}`);
  return data;
}

export async function reorderPathSteps(
  pathId: string,
  payload: { parent_step_id: string | null; ordered: string[] },
): Promise<PathDetail> {
  const { data } = await api.post<PathDetail>(`/paths/${pathId}/steps/reorder`, payload);
  return data;
}
