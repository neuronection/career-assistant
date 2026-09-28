import { api } from "./client";

/** Profile summary from `/api/v1/profiles` (identity-auth §12). */
export interface ProfileSummary {
  id: string;
  name: string;
  color: string | null;
  is_default: boolean;
}

export async function listProfiles(): Promise<ProfileSummary[]> {
  const { data } = await api.get<ProfileSummary[]>("/profiles");
  return data;
}

export async function createProfile(name: string): Promise<ProfileSummary> {
  const { data } = await api.post<ProfileSummary>("/profiles", { name });
  return data;
}

export async function patchProfile(
  id: string,
  patch: { name?: string; color?: string | null; is_default?: boolean },
): Promise<ProfileSummary> {
  const { data } = await api.patch<ProfileSummary>(`/profiles/${id}`, patch);
  return data;
}

export async function deleteProfile(id: string): Promise<void> {
  await api.delete(`/profiles/${id}`);
}
