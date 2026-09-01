import { api } from "./client";
import type {
  DerivedSkillOut,
  ExperienceItemIn,
  ExperienceItemOut,
  ExperienceItemUpdate,
  EvidenceOut,
} from "@/types/experience";

export async function fetchExperience(): Promise<{
  items: ExperienceItemOut[];
  years_of_experience: number;
}> {
  const { data } = await api.get("/me/experience");
  return data;
}

export async function createExperienceItem(
  body: ExperienceItemIn
): Promise<ExperienceItemOut> {
  const { data } = await api.post<ExperienceItemOut>("/me/experience", body);
  return data;
}

export async function updateExperienceItem(
  id: string,
  body: ExperienceItemUpdate
): Promise<ExperienceItemOut> {
  const { data } = await api.patch<ExperienceItemOut>(`/me/experience/${id}`, body);
  return data;
}

export async function deleteExperienceItem(id: string): Promise<void> {
  await api.delete(`/me/experience/${id}`);
}

export async function fetchDerivation(): Promise<{
  skills: DerivedSkillOut[];
  years_of_experience: number;
}> {
  const { data } = await api.get("/me/experience/derivation");
  return data;
}

export async function applyDerivation(): Promise<{
  applied: number;
  conflicts: { key: string; self_level: number; derived_level: number }[];
  derived: DerivedSkillOut[];
}> {
  const { data } = await api.post("/me/experience/derivation/apply");
  return data;
}

export async function fetchSkillEvidence(skillId: string): Promise<EvidenceOut> {
  const { data } = await api.get(`/me/skills/${skillId}/evidence`);
  return data;
}
