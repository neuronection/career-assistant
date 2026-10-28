import { api } from "@/api/client";
import type { Company, CompanyDetail } from "@/types/wire";

export async function fetchCompanies(params: Record<string, unknown> = {}): Promise<Company[]> {
  const { data } = await api.get<Company[]>("/companies", { params });
  return data;
}

export async function fetchCompany(key: string): Promise<CompanyDetail> {
  const { data } = await api.get<CompanyDetail>(`/companies/${key}`);
  return data;
}
