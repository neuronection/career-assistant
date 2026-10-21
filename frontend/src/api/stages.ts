import { api } from "./client";
import type { Bootstrap, CareerStage } from "@/types";

export async function fetchBootstrap(): Promise<Bootstrap> {
  const { data } = await api.get<Bootstrap>("/me/bootstrap");
  return data;
}

export async function setStage(
  career_stage: CareerStage | null
): Promise<Bootstrap> {
  const { data } = await api.put<Bootstrap>("/me/stage", { career_stage });
  return data;
}

/** Persist the first-run AI setup skip (plan 118); returns the bootstrap. */
export async function setAiSetupDismissed(dismissed: boolean): Promise<Bootstrap> {
  const { data } = await api.put<Bootstrap>("/me/preferences/ai-setup", { dismissed });
  return data;
}
