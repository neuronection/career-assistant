import { api } from "./client";
import type { Bootstrap, CareerStage, ScoringWeights } from "@/types";

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

export async function saveScoringWeightsSuggested(
  weights: ScoringWeights
): Promise<{ scoring_weights: ScoringWeights; refitted: number }> {
  const { data } = await api.put("/me/preferences/scoring", weights);
  return data;
}
