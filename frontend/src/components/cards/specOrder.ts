export const SPEC_ORDER = [
  "mode",
  "level",
  "contract",
  "hours",
  "salary",
  "education",
  "closes",
  // company-card slots (closed vocabularies of the company facts)
  "type",
  "size",
  "founded",
] as const;

export type SpecKey = (typeof SPEC_ORDER)[number];

import type { LucideIcon } from "lucide-react";
import { Building2, Globe, House } from "lucide-react";

export interface SpecItem {
  key: SpecKey;
  label: string;
  value: string;
  hint?: string;
  tone?: "warning";
  testId?: string;
  /** Nominal-value glyph (mode: globe / house / building) — never a hue. */
  icon?: LucideIcon;
  /** Ordinal-value intensity cue (seniority), filled out of total. */
  scale?: { filled: number; total: number };
}

/** Closed work-mode vocabulary (explore REMOTE_VALUES) → glyph. */
export const MODE_ICON: Record<string, LucideIcon> = {
  remote: Globe,
  hybrid: House,
  onsite: Building2,
};

/** Closed seniority vocabulary → 1–5 intensity. */
const SENIORITY_LEVEL: Record<string, number> = {
  intern: 1,
  junior: 2,
  mid: 3,
  senior: 4,
  lead: 5,
  principal: 5,
};

export function seniorityScale(value: string): { filled: number; total: number } | undefined {
  const filled = SENIORITY_LEVEL[value];
  return filled ? { filled, total: 5 } : undefined;
}

export function orderSpecs(items: SpecItem[]): SpecItem[] {
  return [...items].sort(
    (a, b) => SPEC_ORDER.indexOf(a.key) - SPEC_ORDER.indexOf(b.key)
  );
}
