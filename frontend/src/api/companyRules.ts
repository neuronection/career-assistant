import { api } from "@/api/client";

/** Plan 135 — the company rules & corrections surface (admin). */

export interface OrgBrief {
  id: string;
  key: string;
  name: string;
  status: string;
}

export interface OrgRow {
  id: string;
  key: string;
  name: string;
  domain: string | null;
  aliases: string[];
  status: string;
  posting_count: number;
}

export interface OrgAliasRow {
  id: string;
  alias: string;
  alias_key: string;
  source: string;
  state: string;
  created_by: string;
  created_at: string | null;
}

export interface OrgExclusionRow {
  id: string;
  label: string;
  label_key: string;
  org_id: string | null;
  org: OrgBrief | null;
  reason: string;
  source: string;
  created_by: string;
  created_at: string | null;
}

export interface MergeSuggestionRow {
  id: string;
  label: string;
  score: number;
  reason: string;
  status: string;
  evidence: Record<string, unknown>;
  org_a: OrgBrief | null;
  org_b: OrgBrief | null;
  created_at: string | null;
}

export interface MatchPairRow {
  id: string;
  label: string;
  status: string;
  verdict: string | null;
  confidence: number | null;
  evidence: Record<string, unknown>;
  candidate: OrgBrief | null;
  created_at: string | null;
}

export interface MatchThresholds {
  match: number;
  gray_low: number;
  llm_auto: number;
}

export async function fetchOrganizations(params: Record<string, unknown> = {}): Promise<OrgRow[]> {
  const { data } = await api.get<OrgRow[]>("/admin/organizations", { params });
  return data;
}

export async function fetchAliasRows(orgId: string): Promise<OrgAliasRow[]> {
  const { data } = await api.get<OrgAliasRow[]>(`/admin/organizations/${orgId}/aliases`);
  return data;
}

export async function addAlias(orgId: string, alias: string): Promise<OrgAliasRow[]> {
  await api.post(`/admin/organizations/${orgId}/aliases`, { alias });
  return fetchAliasRows(orgId);
}

export async function removeAlias(orgId: string, aliasId: string): Promise<void> {
  await api.delete(`/admin/organizations/${orgId}/aliases/${aliasId}`);
}

export async function setAliasState(
  orgId: string,
  aliasId: string,
  state: "active" | "excluded"
): Promise<OrgAliasRow> {
  const { data } = await api.post<OrgAliasRow>(
    `/admin/organizations/${orgId}/aliases/${aliasId}/state`,
    { state }
  );
  return data;
}

export async function fetchExclusions(kind?: "global" | "pair"): Promise<OrgExclusionRow[]> {
  const { data } = await api.get<OrgExclusionRow[]>("/admin/organizations/exclusions", {
    params: kind ? { kind } : {},
  });
  return data;
}

export async function createExclusion(payload: {
  label: string;
  org_id?: string;
  reason?: string;
}): Promise<{ id: string }> {
  const { data } = await api.post<{ id: string }>("/admin/organizations/exclusions", payload);
  return data;
}

export async function deleteExclusion(id: string): Promise<void> {
  await api.delete(`/admin/organizations/exclusions/${id}`);
}

export async function fetchThresholds(): Promise<MatchThresholds> {
  const { data } = await api.get<MatchThresholds>("/admin/organizations/thresholds");
  return data;
}

export async function saveThresholds(payload: MatchThresholds): Promise<MatchThresholds> {
  const { data } = await api.put<MatchThresholds>("/admin/organizations/thresholds", payload);
  return data;
}

export async function fetchSuggestions(status = "open"): Promise<MergeSuggestionRow[]> {
  const { data } = await api.get<MergeSuggestionRow[]>("/admin/organizations/suggestions", {
    params: { status },
  });
  return data;
}

export async function acceptSuggestion(id: string): Promise<{ id: string; status: string }> {
  const { data } = await api.post(`/admin/organizations/suggestions/${id}/accept`, {});
  return data;
}

export async function dismissSuggestion(id: string): Promise<{ id: string; status: string }> {
  const { data } = await api.post(`/admin/organizations/suggestions/${id}/dismiss`, {});
  return data;
}

export async function fetchPairs(status = "pending"): Promise<MatchPairRow[]> {
  const { data } = await api.get<MatchPairRow[]>("/admin/organizations/pairs", {
    params: { status },
  });
  return data;
}
