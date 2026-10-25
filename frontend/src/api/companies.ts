import { api } from "@/api/client";
import type { Company, CompanyDetail, CompanyPosting } from "@/types/wire";

export async function fetchCompanies(params: Record<string, unknown> = {}): Promise<Company[]> {
  const { data } = await api.get<Company[]>("/companies", { params });
  return data;
}

export async function fetchCompany(key: string): Promise<CompanyDetail> {
  const { data } = await api.get<CompanyDetail>(`/companies/${key}`);
  return data;
}

export async function fetchCompanyPostings(key: string, limit = 50): Promise<CompanyPosting[]> {
  const { data } = await api.get<CompanyPosting[]>(`/companies/${key}/postings`, {
    params: { limit },
  });
  return data;
}
