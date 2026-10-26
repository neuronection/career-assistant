import { api } from "@/api/client";
import type { ExploreResponse, RadarOut } from "@/types/wire";

export interface RadarLocationInput {
  city?: string | null;
  country?: string | null;
  remote?: boolean;
}

export interface RadarInput {
  keywords: string[];
  locations: RadarLocationInput[];
  seniority: string[];
  onsite_policy: "onsite" | "hybrid" | "remote" | null;
  salary_min_annual: string | number | null;
  salary_currency: string | null;
  source_keys: string[];
  cadence: "instant" | "daily" | "weekly" | "off";
  enabled: boolean;
}

export async function fetchRadar(): Promise<RadarOut> {
  const { data } = await api.get<RadarOut>("/me/job-radar");
  return data;
}

export async function updateRadar(body: RadarInput): Promise<RadarOut> {
  const { data } = await api.put<RadarOut>("/me/job-radar", body);
  return data;
}

export async function previewRadar(body: RadarInput): Promise<ExploreResponse> {
  const { data } = await api.post<ExploreResponse>("/postings/preview-radar", body);
  return data;
}
