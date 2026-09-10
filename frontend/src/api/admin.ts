import { api } from "./client";
import type { Job } from "@/types";

export interface AdminUser {
  id: string;
  email: string;
  full_name: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
  token_version: number;
  insight_count: number;
}

export interface AIGenerationRow {
  id: string;
  task_type: string;
  provider: string;
  model: string;
  prompt: string;
  output: Record<string, unknown> | null;
  tokens_in: number | null;
  tokens_out: number | null;
  latency_ms: number | null;
  status: string;
  error: string;
  created_at: string;
}

export async function fetchModerationQueue(status = "draft"): Promise<Job[]> {
  const { data } = await api.get<Job[]>("/admin/jobs", { params: { status } });
  return data;
}

export async function bulkJobAction(
  ids: string[],
  action: "publish" | "reject",
): Promise<{ published: number; rejected: number }> {
  const { data } = await api.post("/admin/jobs/bulk", { ids, action });
  return data;
}

export async function fetchUsers(): Promise<AdminUser[]> {
  const { data } = await api.get<AdminUser[]>("/admin/users");
  return data;
}

export async function patchUser(
  id: string,
  body: { is_active?: boolean; is_admin?: boolean },
): Promise<AdminUser> {
  const { data } = await api.patch<AdminUser>(`/admin/users/${id}`, body);
  return data;
}

export async function resetUserPassword(
  id: string,
  newPassword: string,
): Promise<AdminUser> {
  const { data } = await api.post<AdminUser>(`/admin/users/${id}/reset-password`, {
    new_password: newPassword,
  });
  return data;
}

export async function forceLogout(id: string): Promise<AdminUser> {
  const { data } = await api.post<AdminUser>(`/admin/users/${id}/force-logout`);
  return data;
}

export async function fetchAIGenerations(
  params: Record<string, unknown> = {},
): Promise<{ total: number; items: AIGenerationRow[] }> {
  const { data } = await api.get<{ total: number; items: AIGenerationRow[] }>(
    "/admin/ai/generations",
    { params },
  );
  return data;
}
