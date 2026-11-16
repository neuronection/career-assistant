import { api } from "@/api/client";
import type { OfferComparison } from "@/types/application";

export async function fetchOfferComparison(): Promise<OfferComparison> {
  const { data } = await api.get<OfferComparison>("/me/applications/offers/compare");
  return data;
}
