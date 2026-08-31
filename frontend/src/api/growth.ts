import { api } from "./client";
import type {
  CheckinStatus,
  GrowthPlanItem,
  MarketSnapshot,
  RadarEntry,
} from "@/types";

export async function createGrowthPlan(targetJobId: string): Promise<GrowthPlanItem> {
  const { data } = await api.post<GrowthPlanItem>("/growth/plans", {
    target_job_id: targetJobId,
  });
  return data;
}

export async function fetchGrowthPlans(): Promise<GrowthPlanItem[]> {
  const { data } = await api.get<GrowthPlanItem[]>("/growth/plans");
  return data;
}

export async function patchGrowthStep(
  stepId: string,
  body: { status?: string; completed_level?: number }
): Promise<void> {
  await api.patch(`/growth/steps/${stepId}`, body);
}

export async function fetchRadar(): Promise<RadarEntry[]> {
  const { data } = await api.get<RadarEntry[]>("/growth/radar");
  return data;
}

export async function fetchMarketSnapshot(params: {
  family_key?: string;
  job_id?: string;
}): Promise<MarketSnapshot> {
  const { data } = await api.get<MarketSnapshot>("/market/snapshot", { params });
  return data;
}

export async function fetchCheckinStatus(): Promise<CheckinStatus> {
  const { data } = await api.get<CheckinStatus>("/me/checkin");
  return data;
}

export async function skipCheckin(): Promise<void> {
  await api.post("/me/checkin", { skipped: true });
}
