import type { FitBreakdown } from "@/types";

export const DIMENSION_LABELS: Record<string, string> = {
  skills: "Skills",
  interests: "Interests & style",
  values: "Work values",
  education: "Education",
  experience: "Experience",
  location: "Location",
};

export function dimensionKey(key: string): string {
  return `dimensions.${key}`;
}

export function dimensionKeys(breakdowns: (FitBreakdown | null)[]): string[] {
  const keys: string[] = [];
  for (const breakdown of breakdowns) {
    if (!breakdown) continue;
    for (const key of Object.keys(breakdown.dimensions)) {
      if (!keys.includes(key)) keys.push(key);
    }
  }
  return keys;
}
