import { api } from "@/api/client";
import type { CompaniesList, CompanyDetail } from "@/types/wire";

export interface CompanyQuery {
  q?: string;
  limit?: number;
  work_mode?: string[];
  work_mode_exclude?: string[];
  seniority?: string[];
  seniority_exclude?: string[];
  employment?: string[];
  employment_exclude?: string[];
  min_open?: number;
  industry?: string[];
  location?: string;
  facets?: boolean;
}

function toParams(query: CompanyQuery): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  if (query.q?.trim()) params.q = query.q.trim();
  if (query.limit) params.limit = query.limit;
  for (const key of [
    "work_mode",
    "work_mode_exclude",
    "seniority",
    "seniority_exclude",
    "employment",
    "employment_exclude",
    "industry",
  ] as const) {
    const values = query[key];
    if (values && values.length > 0) params[key] = values.join(",");
  }
  if (query.min_open) params.min_open = query.min_open;
  if (query.location?.trim()) params.location = query.location.trim();
  if (query.facets) params.facets = true;
  return params;
}

export async function fetchCompanies(query: CompanyQuery = {}): Promise<CompaniesList> {
  const { data } = await api.get<CompaniesList>("/companies", {
    params: toParams(query),
  });
  return data;
}

export async function fetchCompany(key: string): Promise<CompanyDetail> {
  const { data } = await api.get<CompanyDetail>(`/companies/${key}`);
  return data;
}
