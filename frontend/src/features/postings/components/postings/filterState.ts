/**
 * Pure helpers for the filter system (plan 136): active-filter counting,
 * summary-chip building, and URL state serialization. No React, no IO —
 * every function is unit-testable in isolation.
 */

import { emptyFilterSpec, type FilterSpec } from "@/api/postings";

export interface ActiveChip {
  axis: string;
  label: string;
  value: string;
  kind: "include" | "exclude" | "bound" | "flag";
}

interface AxisDef {
  key: string;
  labelKey: string;
  values: string[];
}

export const AXIS_DEFINITIONS: Record<string, AxisDef> = {
  seniority: {
    key: "seniority",
    labelKey: "filters.seniority",
    values: ["intern", "junior", "mid", "senior", "lead", "principal"],
  },
  employment: {
    key: "employment",
    labelKey: "filters.employment",
    values: ["full_time", "part_time", "contract", "temporary", "internship", "other"],
  },
  work_mode: {
    key: "work_mode",
    labelKey: "filters.workMode",
    values: ["onsite", "hybrid", "remote"],
  },
  education: {
    key: "education",
    labelKey: "filters.education",
    values: [
      "no_formal",
      "middle_school",
      "high_school",
      "vocational",
      "bachelor",
      "master",
      "doctorate",
    ],
  },
};

export function countActiveFilters(spec: FilterSpec): number {
  let count = 0;
  for (const axis of ["skills", "location", "companies", "source", "languages"] as const) {
    const a = spec[axis] as { include: string[]; exclude: string[] };
    count += a.include.length + a.exclude.length;
  }
  if (spec.skills.min_level !== null) count++;
  if (spec.salary.min !== null || spec.salary.max !== null || spec.salary.currency) count++;
  if (spec.location.remote_only !== null) count++;
  if (spec.companies.industries_include.length) count++;
  if (spec.companies.industries_exclude.length) count++;
  if (spec.seniority.min || spec.seniority.max) count++;
  count += spec.seniority.exclude.length;
  for (const axis of ["employment", "work_mode", "education"] as const) {
    count += spec[axis].include.length + spec[axis].exclude.length;
  }
  if (spec.posted_within.days !== null) count++;
  if (spec.match_score.min !== null || spec.match_score.max !== null) count++;
  if (spec.saved.value !== null) count++;
  if (spec.description.text) count++;
  return count;
}

export function buildSummaryChips(spec: FilterSpec): ActiveChip[] {
  const chips: ActiveChip[] = [];
  const add = (axis: string, label: string, value: string, kind: ActiveChip["kind"]) =>
    chips.push({ axis, label, value, kind });

  for (const skill of spec.skills.include) add("skills", skill, skill, "include");
  for (const skill of spec.skills.exclude) add("skills", `− ${skill}`, skill, "exclude");
  if (spec.skills.min_level !== null)
    add("skills", `≥ ${spec.skills.min_level}`, String(spec.skills.min_level), "bound");
  if (spec.skills.include.length > 0 && spec.skills.expand !== "off") {
    const hops = spec.skills.hops === 2 ? " · 2 hops" : "";
    add(
      "skills",
      `+ ${spec.skills.expand === "related" ? "related" : "sub-skills"}${hops}`,
      `expand:${spec.skills.expand}:${spec.skills.hops}`,
      "flag",
    );
  }

  if (spec.salary.min !== null && spec.salary.max !== null)
    add("salary", `${spec.salary.min}–${spec.salary.max}`, "range", "bound");
  else if (spec.salary.min !== null)
    add("salary", `≥ ${spec.salary.min}`, String(spec.salary.min), "bound");
  else if (spec.salary.max !== null)
    add("salary", `≤ ${spec.salary.max}`, String(spec.salary.max), "bound");

  for (const loc of spec.location.include) add("location", loc, loc, "include");
  for (const loc of spec.location.exclude) add("location", `− ${loc}`, loc, "exclude");
  if (spec.location.remote_only === true) add("location", "remote only", "remote", "flag");

  for (const org of spec.companies.include) add("companies", org, org, "include");
  for (const org of spec.companies.exclude) add("companies", `− ${org}`, org, "exclude");

  if (spec.seniority.min || spec.seniority.max) {
    const label = spec.seniority.min && spec.seniority.max
      ? `${spec.seniority.min}–${spec.seniority.max}`
      : spec.seniority.min
        ? `≥ ${spec.seniority.min}`
        : `≤ ${spec.seniority.max}`;
    add("seniority", label, label, "bound");
  }
  for (const v of spec.seniority.exclude) add("seniority", `− ${v}`, v, "exclude");
  for (const axis of ["employment", "work_mode", "education"] as const) {
    for (const v of spec[axis].include) add(axis, v, v, "include");
    for (const v of spec[axis].exclude) add(axis, `− ${v}`, v, "exclude");
  }

  if (spec.posted_within.days !== null)
    add("posted_within", `${spec.posted_within.days}d`, String(spec.posted_within.days), "bound");
  if (spec.match_score.min !== null)
    add("match_score", `score ≥ ${spec.match_score.min}`, String(spec.match_score.min), "bound");
  if (spec.saved.value === true) add("saved", "saved", "true", "flag");
  if (spec.description.text) add("description", `"${spec.description.text}"`, spec.description.text, "flag");

  return chips;
}

export function removeChip(spec: FilterSpec, chip: ActiveChip): FilterSpec {
  const next = structuredClone(spec);
  switch (chip.axis) {
    case "skills":
      if (chip.kind === "flag" && chip.value.startsWith("expand:")) {
        next.skills.expand = "off";
      } else if (chip.kind === "bound" && chip.value === String(next.skills.min_level)) {
        next.skills.min_level = null;
      } else {
        next.skills.include = next.skills.include.filter((v) => v !== chip.value);
        next.skills.exclude = next.skills.exclude.filter((v) => v !== chip.value);
        if (next.skills.include.length === 0) next.skills.min_level = null;
      }
      break;
    case "salary":
      next.salary.min = null;
      next.salary.max = null;
      break;
    case "location":
      if (chip.kind === "flag") {
        next.location.remote_only = null;
      } else {
        next.location.include = next.location.include.filter((v) => v !== chip.value);
        next.location.exclude = next.location.exclude.filter((v) => v !== chip.value);
      }
      break;
    case "companies":
      next.companies.include = next.companies.include.filter((v) => v !== chip.value);
      next.companies.exclude = next.companies.exclude.filter((v) => v !== chip.value);
      break;
    case "seniority":
      if (chip.kind === "bound") {
        next.seniority.min = null;
        next.seniority.max = null;
      } else {
        next.seniority.exclude = next.seniority.exclude.filter((v) => v !== chip.value);
      }
      break;
    case "employment":
    case "work_mode":
    case "education": {
      const axis = next[chip.axis as "employment"];
      axis.include = axis.include.filter((v) => v !== chip.value);
      axis.exclude = axis.exclude.filter((v) => v !== chip.value);
      break;
    }
    case "posted_within":
      next.posted_within.days = null;
      break;
    case "match_score":
      next.match_score.min = null;
      next.match_score.max = null;
      break;
    case "saved":
      next.saved.value = null;
      break;
    case "description":
      next.description.text = null;
      break;
  }
  return next;
}

// ------------------------------------------------------------- URL state

export function encodeFilterSpec(spec: FilterSpec): string {
  const json = JSON.stringify(spec);
  try {
    return btoa(encodeURIComponent(json));
  } catch {
    return "";
  }
}

export function decodeFilterSpec(encoded: string | null): FilterSpec | null {
  if (!encoded) return null;
  try {
    const json = decodeURIComponent(atob(encoded));
    const parsed = JSON.parse(json);
    // sanity: must look like a spec
    if (typeof parsed === "object" && parsed && "v" in parsed && "skills" in parsed) {
      return normalizeFilterSpec(parsed);
    }
    return null;
  } catch {
    return null;
  }
}

type RawFilterSpec = Partial<Omit<FilterSpec, "skills">> & {
  skills?: Partial<FilterSpec["skills"]> | null;
};

/**
 * Fill a possibly older spec (URL, stored preset) with the current defaults.
 *
 * Nested merge matters: a spec written before the expansion knob (plan 138)
 * has a complete `skills` object without `expand`/`hops`, so a shallow spread
 * would drop the whole axis defaults and leave the rail showing a mode the
 * backend would not apply.
 */
export function normalizeFilterSpec(raw: RawFilterSpec | null | undefined): FilterSpec {
  const base = emptyFilterSpec();
  if (!raw) return base;
  return {
    ...base,
    ...raw,
    skills: { ...base.skills, ...(raw.skills ?? {}) },
  };
}
