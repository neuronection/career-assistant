import { api } from "@/api/client";

import type { CatalogPreset, CatalogProvider, SourcesCatalog } from "@/config/sourcesCatalogs";

// ATS catalog import (plan 187): the instance-wide, admin-managed catalog
// store behind `/admin/postings/sources/catalogs` — the backend validates
// + persists; fetching user URLs never touches the server.

export type CatalogUpsertPayload = {
  tier: "operator" | "community" | "user";
  url?: string | null;
  fetchedAt: string;
  etag?: string | null;
  lastModified?: string | null;
  schemaVersion: 1;
  kind: "career-ats-catalog";
  name: string;
  license?: string | null;
  updatedAt: string;
  revision: number;
  contentHash: string;
  signature: null;
  presets: CatalogPreset[];
  providers: CatalogProvider[];
};

export async function fetchCatalogs(): Promise<SourcesCatalog[]> {
  const response = await api.get<SourcesCatalog[]>(
    "/admin/postings/sources/catalogs",
  );
  return response.data;
}

export async function putCatalog(
  id: string,
  payload: CatalogUpsertPayload,
): Promise<SourcesCatalog> {
  const response = await api.put<SourcesCatalog>(
    `/admin/postings/sources/catalogs/${encodeURIComponent(id)}`,
    payload,
  );
  return response.data;
}

export async function deleteCatalog(
  id: string,
): Promise<{ id: string; deleted: boolean }> {
  const response = await api.delete(
    `/admin/postings/sources/catalogs/${encodeURIComponent(id)}`,
  );
  return response.data;
}
