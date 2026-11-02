import { api } from "@/api/client";

/** Public update check (`GET /api/v1/instance/update-check`) — a cached
 * (6 h, server-side) lookup against the family version API
 * (neuronection.com, ADR-0048); readable without a session so the banner
 * renders pre-login too. A failed fetch reads as "no update"
 * (fail-closed, never a blocker). */
export interface UpdateCheck {
  current_version: string;
  latest_version: string | null;
  update_available: boolean;
  release_url: string;
  checked_at: string | null;
  error: string | null;
}

export async function getUpdateCheck(): Promise<UpdateCheck> {
  const { data } = await api.get<UpdateCheck>("/instance/update-check");
  return data;
}
