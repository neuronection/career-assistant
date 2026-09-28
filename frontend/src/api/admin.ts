import axios from "axios";
import { api } from "./client";
import type { Job } from "@/types";

/** `PublicUser` (identity-auth §12) — what `/auth/me` and
 * `PATCH /me/password` return. Never hashes/counters/stamps. */
export interface PublicUser {
  id: string;
  email: string;
  full_name: string;
  is_admin: boolean;
  is_active: boolean;
}

/** Admin row shape of `GET /admin/users` (identity-auth §12). */
export interface AdminUser {
  id: string;
  email: string;
  full_name: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
  activity_count: number;
}

export interface AdminUserPatch {
  is_active?: boolean;
  is_admin?: boolean;
}

/** Entry of `GET /me/sessions` (identity-auth §12) — one row per
 * refresh family ("device"); `current` marks the caller's own session. */
export interface UserSession {
  id: string;
  client_label: string;
  created_at: string | null;
  expires_at: string;
  revoked_at: string | null;
  current: boolean;
}

/** Guard-rail rejection shaped for the shared `AdminUserTable`'s error
 * mapping (`describeAdminUserError` reads `{status, detail}`): 403s with
 * "themselves"/"last admin" become friendly messages, anything else falls
 * back to its detail or the generic one. Axios errors are normalized to
 * this shape on the way out of the admin calls. */
export class AdminApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
    this.name = "AdminApiError";
  }
}

function toAdminApiError(error: unknown): unknown {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: string } | undefined)?.detail;
    return new AdminApiError(error.response?.status ?? 0, detail ?? "");
  }
  return error;
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

// --- Admin users (identity-auth §12) — the shared AdminUserTable's data
// layer. Rejections normalize to AdminApiError so guard-rail 403s map to
// the table's friendly messages.

export async function fetchUsers(): Promise<AdminUser[]> {
  try {
    const { data } = await api.get<AdminUser[]>("/admin/users");
    return data;
  } catch (error) {
    throw toAdminApiError(error);
  }
}

export async function patchUser(
  id: string,
  body: AdminUserPatch,
): Promise<AdminUser> {
  try {
    const { data } = await api.patch<AdminUser>(`/admin/users/${id}`, body);
    return data;
  } catch (error) {
    throw toAdminApiError(error);
  }
}

export async function resetUserPassword(id: string, newPassword: string): Promise<void> {
  try {
    await api.post(`/admin/users/${id}/reset-password`, { new_password: newPassword });
  } catch (error) {
    throw toAdminApiError(error);
  }
}

export async function forceLogout(id: string): Promise<void> {
  try {
    await api.post(`/admin/users/${id}/force-logout`);
  } catch (error) {
    throw toAdminApiError(error);
  }
}

// --- Account self-service (identity-auth §12, `/api/v1/me`): own
// sessions, password change and account deletion. Wrong-password 403s
// are mapped by the callers (the Account settings page).

export async function listMySessions(): Promise<UserSession[]> {
  const { data } = await api.get<UserSession[]>("/me/sessions");
  return data;
}

export async function revokeMySession(familyId: string): Promise<void> {
  await api.delete(`/me/sessions/${familyId}`);
}

/** Changes the password and rotates the caller's session cookies — the
 * caller stays signed in, every other session is signed out. */
export async function changeMyPassword(
  currentPassword: string,
  newPassword: string,
): Promise<PublicUser> {
  const { data } = await api.patch<PublicUser>("/me/password", {
    current_password: currentPassword,
    new_password: newPassword,
  });
  return data;
}

export async function deleteMyAccount(password: string): Promise<void> {
  await api.delete("/me", { data: { password } });
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
