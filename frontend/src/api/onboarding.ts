import { api } from "./client";
import type {
  CompletenessRing,
  ExpressResult,
  ExpressStart,
  Nudge,
  ResolveResponse,
  TargetDashboard,
} from "@/types";

export async function resolveTarget(q: string): Promise<ResolveResponse> {
  const { data } = await api.get<ResolveResponse>("/onboarding/resolve", {
    params: { q },
  });
  return data;
}

export async function expressStart(body: ExpressStart): Promise<ExpressResult> {
  const { data } = await api.post<ExpressResult>("/onboarding/express", body);
  return data;
}

export async function fetchCompleteness(): Promise<CompletenessRing> {
  const { data } = await api.get<CompletenessRing>("/me/completeness");
  return data;
}

export async function fetchNudges(): Promise<Nudge[]> {
  const { data } = await api.get<Nudge[]>("/me/nudges");
  return data;
}

export async function dismissNudge(type: string): Promise<void> {
  await api.post(`/me/nudges/${type}/dismiss`);
}

export async function fetchTargetDashboard(): Promise<TargetDashboard> {
  const { data } = await api.get<TargetDashboard>("/dashboard/target");
  return data;
}
