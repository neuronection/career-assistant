import { api } from "./client";

export interface CostRow {
  provider: string;
  model: string;
  calls: number;
  tokens_in: number;
  tokens_out: number;
  cost_micros: number | null;
  priced_calls: number;
  unpriced_calls: number;
}

export interface CostsResponse {
  window: "24h" | "7d" | "30d";
  rows: CostRow[];
}

export interface EffectivePrice {
  provider: string | null;
  provider_id: string | null;
  model: string;
  source: string;
  input_micros_per_million: number;
  output_micros_per_million: number;
  metering: string;
  reviewed_at: string | null;
  price_version: string | null;
}

export interface PricesResponse {
  overrides: Array<{
    id: string;
    provider_key: string | null;
    provider_ref: string | null;
    model: string;
    match: "exact" | "prefix";
    input_micros_per_million: number;
    output_micros_per_million: number;
    metering: string;
    updated_at: string;
  }>;
  effective: EffectivePrice[];
}

export async function fetchAiCosts(
  window: "24h" | "7d" | "30d" = "30d",
): Promise<CostsResponse> {
  const { data } = await api.get<CostsResponse>("/ai/usage/costs", {
    params: { window },
  });
  return data;
}

export async function fetchAiPrices(): Promise<PricesResponse> {
  const { data } = await api.get<PricesResponse>("/ai/prices");
  return data;
}

export interface PriceOverrideInput {
  provider_key?: string | null;
  provider_ref?: string | null;
  model: string;
  match?: "exact" | "prefix";
  input_micros_per_million: number;
  output_micros_per_million: number;
  metering?: "tokens" | "input_only" | "output_only";
}

export async function saveAiPrice(
  body: PriceOverrideInput,
): Promise<PricesResponse["overrides"][number]> {
  const { data } = await api.put<PricesResponse["overrides"][number]>("/ai/prices", body);
  return data;
}

export async function deleteAiPrice(id: string): Promise<void> {
  await api.delete(`/ai/prices/${id}`);
}
