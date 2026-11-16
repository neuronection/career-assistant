import { api } from "@/api/client";

export type DegreeRoleReason = "matched" | "parent" | "family_expansion";

export interface DegreeRoleMatch {
  family_key: string;
  family_title: string;
  matched_terms: string[];
  reason: DegreeRoleReason;
  depth: number;
}

export interface DegreeRoles {
  matches: DegreeRoleMatch[];
}

export async function fetchDegreeRoles(): Promise<DegreeRoles> {
  const { data } = await api.get<DegreeRoles>("/profile/degree-roles");
  return data;
}
