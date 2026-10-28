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

export interface SpecItem {
  key: SpecKey;
  label: string;
  value: string;
  hint?: string;
  tone?: "warning";
  testId?: string;
}

export function orderSpecs(items: SpecItem[]): SpecItem[] {
  return [...items].sort(
    (a, b) => SPEC_ORDER.indexOf(a.key) - SPEC_ORDER.indexOf(b.key)
  );
}
