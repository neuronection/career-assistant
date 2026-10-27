import { api } from "@/api/client";
import type { SkillGapReport } from "@/types/wire";
import type { Skill, UserSkill } from "@/types";

export interface SkillSummary {
  id: string;
  key: string;
  label: string;
  category: string;
  description: string;
  parent_id: string | null;
  level_anchors: Skill["level_anchors"];
  /** Present on admin/taxonomy listings; omitted by /skills (active-only). */
  status?: string;
}

export async function fetchSkillOntology(params: {
  q?: string;
  category?: string;
} = {}): Promise<SkillSummary[]> {
  const { data } = await api.get<SkillSummary[]>("/skills", { params });
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


