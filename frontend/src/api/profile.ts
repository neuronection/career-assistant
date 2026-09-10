import { api } from "./client";
import type { Profile, TaxonomyTag } from "@/types";

export async function fetchProfile(): Promise<Profile> {
  const { data } = await api.get<Profile>("/profile");
  return data;
}

export async function saveProfileSection(section: Partial<Profile>): Promise<Profile> {
  const { data } = await api.put<Profile>("/profile", section);
  return data;
}

export async function analyzeProfile(): Promise<{ ai_summary: Profile["ai_summary"]; completeness: Profile["completeness"] }> {
  const { data } = await api.post("/profile/ai-analyze");
  return data;
}

export async function fetchInterests(category?: string): Promise<TaxonomyTag[]> {
  const { data } = await api.get<TaxonomyTag[]>("/taxonomy/interests", {
    params: { category, include_deprecated: false },
  });
  return data;
}

export async function fetchSkills(): Promise<TaxonomyTag[]> {
  const { data } = await api.get<TaxonomyTag[]>("/skills");
  return data;
}
