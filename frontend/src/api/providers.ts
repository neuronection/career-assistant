import { api } from "@/api/client";
import type { components } from "@/types/api.gen";

// Plan 218: seed-data providers. The admin surface manages publishers,
// immutable pack versions and the applied catalog; the user surface is the
// signed-in read view used by the gallery/radar. Storage stays `seed_*`.

type Schemas = components["schemas"];

export type AdminProvider = Schemas["ProviderAdminOut"];
export type AdminProviderDetail = Schemas["ProviderAdminDetailOut"];
export type ProviderCreate = Schemas["ProviderCreateIn"];
export type ProviderUpdate = Schemas["ProviderUpdateIn"];
export type ProviderVersion = Schemas["VersionOut"];
export type ProviderPlan = Schemas["PlanOut"];
export type ProviderApply = Schemas["ApplyOut"];
export type ProviderSyncReport = Schemas["SyncReportOut"];
export type ProviderSyncRun = Schemas["SyncRunOut"];
export type ProviderDiscover = Schemas["DiscoverOut"];
export type RepositoryImport = Schemas["RepositoryImportIn"];
export type RepositoryImportResult = Schemas["RepositoryImportOut"];
export type ProviderProbe = Schemas["ProbeOut"];
export type UserProvider = Schemas["UserProviderOut"];
export type UserProviderDetail = Schemas["UserProviderDetailOut"];
export type UserProviderEndpoint = Schemas["UserEndpointOut"];
export type ProviderSubscription = Schemas["ProviderSubscriptionOut"];
export type ProviderSubscriptionInput = Schemas["ProviderSubscriptionIn"];
export type SourcePref = Schemas["SourcePrefOut"];
export type SourcePrefInput = Schemas["SourcePrefIn"];

const ADMIN = "/admin/providers";

function encoded(seedKey: string): string {
  return encodeURIComponent(seedKey);
}

export async function listAdminProviders(): Promise<AdminProvider[]> {
  const { data } = await api.get<AdminProvider[]>(ADMIN);
  return data;
}

export async function fetchAdminProvider(id: string): Promise<AdminProviderDetail> {
  const { data } = await api.get<AdminProviderDetail>(`${ADMIN}/${id}`);
  return data;
}

export async function createProvider(payload: ProviderCreate): Promise<AdminProviderDetail> {
  const { data } = await api.post<AdminProviderDetail>(ADMIN, payload);
  return data;
}

export async function updateProvider(
  id: string,
  payload: ProviderUpdate,
): Promise<AdminProviderDetail> {
  const { data } = await api.patch<AdminProviderDetail>(`${ADMIN}/${id}`, payload);
  return data;
}

export async function deleteProvider(id: string): Promise<{ retired: boolean }> {
  const { data } = await api.delete<{ retired: boolean }>(`${ADMIN}/${id}`);
  return data;
}

export async function discoverProvider(payload: {
  kind: "git" | "registry";
  uri: string;
  ref?: string;
}): Promise<ProviderDiscover> {
  const { data } = await api.post<ProviderDiscover>(`${ADMIN}/discover`, payload);
  return data;
}

/** Add one provider per pack published by a repository index (idempotent). */
export async function importProviderRepository(
  payload: RepositoryImport,
): Promise<RepositoryImportResult> {
  const { data } = await api.post<RepositoryImportResult>(`${ADMIN}/import`, payload);
  return data;
}

export async function syncProvider(id: string): Promise<ProviderSyncReport> {
  const { data } = await api.post<ProviderSyncReport>(`${ADMIN}/${id}/sync`);
  return data;
}

/** One-click official catalog install: sync, approve, apply and enable. */
export async function installOfficialProvider(id: string): Promise<ProviderApply> {
  const { data } = await api.post<ProviderApply>(`${ADMIN}/${id}/install`);
  return data;
}

export async function uploadProviderPack(id: string, file: File): Promise<ProviderSyncReport> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post<ProviderSyncReport>(`${ADMIN}/${id}/upload`, form);
  return data;
}

export async function listProviderVersions(id: string): Promise<ProviderVersion[]> {
  const { data } = await api.get<ProviderVersion[]>(`${ADMIN}/${id}/versions`);
  return data;
}

export async function planProviderVersion(id: string, versionId: string): Promise<ProviderPlan> {
  const { data } = await api.get<ProviderPlan>(`${ADMIN}/${id}/versions/${versionId}/plan`);
  return data;
}

export async function approveProviderVersion(
  id: string,
  versionId: string,
): Promise<ProviderVersion> {
  const { data } = await api.post<ProviderVersion>(
    `${ADMIN}/${id}/versions/${versionId}/approve`,
  );
  return data;
}

export async function rejectProviderVersion(
  id: string,
  versionId: string,
  reason: string,
): Promise<ProviderVersion> {
  const { data } = await api.post<ProviderVersion>(
    `${ADMIN}/${id}/versions/${versionId}/reject`,
    { reason },
  );
  return data;
}

export async function revokeProviderVersion(
  id: string,
  versionId: string,
): Promise<ProviderApply> {
  const { data } = await api.post<ProviderApply>(
    `${ADMIN}/${id}/versions/${versionId}/revoke`,
  );
  return data;
}

export async function applyProviderVersion(
  id: string,
  versionId: string,
): Promise<ProviderApply> {
  const { data } = await api.post<ProviderApply>(
    `${ADMIN}/${id}/versions/${versionId}/apply`,
  );
  return data;
}

export async function adoptProviderVersion(
  id: string,
  versionId: string,
  seedKeys?: string[],
): Promise<ProviderApply> {
  const { data } = await api.post<ProviderApply>(`${ADMIN}/${id}/adopt`, {
    version_id: versionId,
    seed_keys: seedKeys ?? null,
  });
  return data;
}

export async function setProviderItemEnabled(
  id: string,
  seedKey: string,
  enabled: boolean,
): Promise<void> {
  await api.post(`${ADMIN}/${id}/items/${encoded(seedKey)}/${enabled ? "enable" : "disable"}`);
}

export async function retireProviderItem(id: string, seedKey: string): Promise<void> {
  await api.post(`${ADMIN}/${id}/items/${encoded(seedKey)}/retire`);
}

export async function listProviderRuns(id: string, limit = 50): Promise<ProviderSyncRun[]> {
  const { data } = await api.get<ProviderSyncRun[]>(`${ADMIN}/${id}/sync-runs`, {
    params: { limit },
  });
  return data;
}

export async function probeProviderEndpoint(id: string, seedKey: string): Promise<ProviderProbe> {
  const { data } = await api.post<ProviderProbe>(
    `${ADMIN}/${id}/endpoints/${encoded(seedKey)}/probe`,
  );
  return data;
}

export async function listUserProviders(): Promise<UserProvider[]> {
  const { data } = await api.get<UserProvider[]>("/providers");
  return data;
}

export async function fetchUserProvider(id: string): Promise<UserProviderDetail> {
  const { data } = await api.get<UserProviderDetail>(`/providers/${id}`);
  return data;
}

export async function listUserProviderEndpoints(
  id: string,
): Promise<UserProviderEndpoint[]> {
  const { data } = await api.get<UserProviderEndpoint[]>(`/providers/${id}/endpoints`);
  return data;
}


export async function listProviderSubscriptions(): Promise<ProviderSubscription[]> {
  const { data } = await api.get<ProviderSubscription[]>("/me/provider-subscriptions");
  return data;
}

export async function putProviderSubscription(
  providerId: string,
  payload: ProviderSubscriptionInput,
): Promise<ProviderSubscription> {
  const { data } = await api.put<ProviderSubscription>(
    `/me/provider-subscriptions/${providerId}`,
    payload,
  );
  return data;
}

export async function deleteProviderSubscription(providerId: string): Promise<void> {
  await api.delete(`/me/provider-subscriptions/${providerId}`);
}

export async function listSourcePrefs(): Promise<SourcePref[]> {
  const { data } = await api.get<SourcePref[]>("/me/source-prefs");
  return data;
}

export async function putSourcePref(
  sourceId: string,
  payload: SourcePrefInput,
): Promise<SourcePref> {
  const { data } = await api.put<SourcePref>(`/me/source-prefs/${sourceId}`, payload);
  return data;
}
