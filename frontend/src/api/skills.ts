import { api } from "./client";
import type { CareerPath, Skill, SkillGapReport, UserSkill } from "@/types";

export interface SkillSummary {
  id: string;
  key: string;
  label: string;
  category: string;
  description: string;
  parent_id: string | null;
  level_anchors: Skill["level_anchors"];
  status: string;
}

export async function fetchSkillOntology(params: {
  q?: string;
  category?: string;
} = {}): Promise<SkillSummary[]> {
  const { data } = await api.get<SkillSummary[]>("/skills", { params });
  return data;
}

export async function fetchSkillDetail(key: string): Promise<Skill & { children_keys: string[]; jobs: unknown[] }> {
  const { data } = await api.get(`/skills/${key}`);
  return data;
}

export async function fetchMySkills(): Promise<UserSkill[]> {
  const { data } = await api.get<UserSkill[]>("/me/skills");
  return data;
}

export async function saveMySkills(
  skills: { skill_key: string; level: number }[],
): Promise<UserSkill[]> {
  const { data } = await api.put<UserSkill[]>("/me/skills", { skills });
  return data;
}

export async function setSkillDeriveEnabled(
  skillId: string,
  derive_enabled: boolean,
): Promise<UserSkill> {
  const { data } = await api.patch<UserSkill>(`/me/skills/${skillId}`, {
    derive_enabled,
  });
  return data;
}

export async function deleteMySkill(skillId: string): Promise<void> {
  await api.delete(`/me/skills/${skillId}`);
}

export async function fetchSkillGaps(jobRef: string): Promise<SkillGapReport> {
  const { data } = await api.get<SkillGapReport>("/me/skills/gaps", {
    params: { job_id: jobRef },
  });
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

export async function fetchJobPathGraph(jobRef: string): Promise<{ root: string; nodes: { code: string; title: string; depth: number }[] }> {
  const { data } = await api.get(`/jobs/${jobRef}/paths/graph`);
  return data;
}
