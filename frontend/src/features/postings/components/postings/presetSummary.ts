import {
  POSTED_WINDOWS,
  SORT_OPTIONS,
  filtersFromRecord,
  toParams,
  type Filters,
} from "@/features/catalog/exploreParams";

type Translate = (key: string, options?: Record<string, unknown>) => string;

const FACET_LABELS: Array<{
  includeKey: keyof Filters;
  excludeKey: keyof Filters;
  labelKey: string;
  localize?: (value: string, t: Translate) => string;
}> = [
  { includeKey: "seniority", excludeKey: "seniorityExclude", labelKey: "explore.seniority" },
  { includeKey: "remotePolicy", excludeKey: "remotePolicyExclude", labelKey: "explore.facet.workMode" },
  { includeKey: "contract", excludeKey: "contractExclude", labelKey: "explore.facet.contract" },
  { includeKey: "travel", excludeKey: "travelExclude", labelKey: "explore.facet.travel" },
  { includeKey: "schedule", excludeKey: "scheduleExclude", labelKey: "explore.facet.schedule" },
  { includeKey: "source", excludeKey: "sourceExclude", labelKey: "explore.facet.sources" },
  { includeKey: "orgs", excludeKey: "orgsExclude", labelKey: "explore.facet.organization" },
];

function facetValue(value: string, t: Translate): string {
  return t(`explore.facetValue.${value}`, { defaultValue: value.replace(/_/g, " ") });
}

function sortLabel(sort: string): string | null {
  const option = SORT_OPTIONS.find((entry) => entry.value === sort);
  return option ? option.labelKey : null;
}

function axisPatch(key: keyof Filters, values: string[]): Partial<Filters> {
  return { [key]: values } as Partial<Filters>;
}

export function describeFilters(filters: Filters, t: Translate): string[] {
  const lines: string[] = [];
  if (filters.q) lines.push(t("presets.summary.query", { value: filters.q }));
  if (filters.skills.length) {
    lines.push(
      t("presets.summary.skills", {
        list: filters.skills
          .map((skill) => (skill.level ? `${skill.key} ≥ ${skill.level}` : skill.key))
          .join(", "),
      })
    );
  }
  if (filters.skillsExclude.length) {
    lines.push(t("presets.summary.skillsExclude", { list: filters.skillsExclude.join(", ") }));
  }
  for (const facet of FACET_LABELS) {
    const include = filters[facet.includeKey] as string[];
    const exclude = filters[facet.excludeKey] as string[];
    const label = t(facet.labelKey);
    if (include.length) {
      lines.push(
        t("presets.summary.include", {
          label,
          list: include.map((value) => facetValue(value, t)).join(", "),
        })
      );
    }
    if (exclude.length) {
      lines.push(
        t("presets.summary.exclude", {
          label,
          list: exclude.map((value) => facetValue(value, t)).join(", "),
        })
      );
    }
  }
  if (filters.postedWithin) {
    const window = POSTED_WINDOWS.find((entry) => entry.value === filters.postedWithin);
    lines.push(
      t("presets.summary.posted", {
        value: window ? t(window.labelKey) : filters.postedWithin,
      })
    );
  }
  if (filters.salaryMin) {
    lines.push(t("presets.summary.salary", { value: filters.salaryMin }));
  }
  if (filters.extractedOnly) lines.push(t("explore.deepExtractedOnly"));
  if (filters.saved) lines.push(t("explore.savedOnly"));
  if (filters.seenExclude) lines.push(t("explore.hideSeen"));
  const sort = sortLabel(filters.sort);
  if (sort && filters.sort !== "fit") lines.push(t("presets.summary.sort", { value: t(sort) }));
  return lines;
}

export function suggestPresetName(filters: Filters, t: Translate): string {
  const parts: string[] = [];
  if (filters.q) parts.push(filters.q);
  for (const value of filters.seniority) parts.push(facetValue(value, t));
  if (filters.remotePolicy.includes("remote")) parts.push(facetValue("remote", t));
  for (const skill of filters.skills.slice(0, 2)) parts.push(skill.key);
  if (!parts.length && filters.source.length) parts.push(filters.source[0]);
  if (!parts.length) {
    for (const value of filters.contract) parts.push(facetValue(value, t));
  }
  return parts.slice(0, 3).join(" · ") || t("presets.defaultName");
}

export function presetFilters(record: Record<string, unknown> | null | undefined): Filters {
  return filtersFromRecord(record);
}

export function presetPayload(filters: Filters): Record<string, unknown> {
  return toParams(filters) as unknown as Record<string, unknown>;
}

export interface ExploreFilterChip {
  key: string;
  label: string;
  patch: Partial<Filters>;
}

/**
 * One removable chip per applied filter value (plan 209): the compact rail's
 * page-level summary, next to the search/sort header. Same label vocabulary
 * as `describeFilters`, but each chip carries the patch that removes exactly
 * that value — search text, skills, enum facets, free-text places and the
 * boolean toggles. Sort and the "all postings" basis keep their own controls.
 */
export function exploreFilterChips(filters: Filters, t: Translate): ExploreFilterChip[] {
  const chips: ExploreFilterChip[] = [];
  const push = (key: string, label: string, patch: Partial<Filters>) =>
    chips.push({ key, label, patch });

  if (filters.q) push("q", t("presets.summary.query", { value: filters.q }), { q: "" });

  for (const skill of filters.skills) {
    push(
      `skill-${skill.key}`,
      skill.level ? `${skill.key} ≥ ${skill.level}` : skill.key,
      { skills: filters.skills.filter((entry) => entry.key !== skill.key) }
    );
  }
  for (const skill of filters.skillsExclude) {
    push(`skill-exclude-${skill}`, `− ${skill}`, {
      skillsExclude: filters.skillsExclude.filter((entry) => entry !== skill),
    });
  }
  if (filters.skillMode !== "all" && filters.skills.length) {
    push("skill-mode", t("explore.anyMatches"), { skillMode: "all" });
  }

  for (const facet of FACET_LABELS) {
    const include = filters[facet.includeKey] as string[];
    const exclude = filters[facet.excludeKey] as string[];
    for (const value of include) {
      push(
        `${String(facet.includeKey)}-${value}`,
        facetValue(value, t),
        axisPatch(facet.includeKey, include.filter((entry) => entry !== value))
      );
    }
    for (const value of exclude) {
      push(
        `${String(facet.excludeKey)}-${value}`,
        `− ${facetValue(value, t)}`,
        axisPatch(facet.excludeKey, exclude.filter((entry) => entry !== value))
      );
    }
  }

  for (const value of filters.employmentType) {
    push(`employment-${value}`, value.replace(/_/g, " "), {
      employmentType: filters.employmentType.filter((entry) => entry !== value),
    });
  }
  for (const value of filters.mappedFamily) {
    push(`family-${value}`, value.replace(/_/g, " "), {
      mappedFamily: filters.mappedFamily.filter((entry) => entry !== value),
    });
  }
  for (const value of filters.job) {
    push(`job-${value}`, value, { job: filters.job.filter((entry) => entry !== value) });
  }
  if (filters.postedWithin) {
    const window = POSTED_WINDOWS.find((entry) => entry.value === filters.postedWithin);
    push("posted", t(window ? window.labelKey : "explore.facet.posted"), { postedWithin: "" });
  }
  if (filters.salaryMin) {
    push("salary", t("presets.summary.salary", { value: filters.salaryMin }), { salaryMin: "" });
  }
  if (filters.city) push("city", filters.city, { city: "" });
  if (filters.country) push("country", filters.country, { country: "" });
  if (filters.extractedOnly) {
    push("extracted", t("explore.deepExtractedOnly"), { extractedOnly: false });
  }
  if (filters.saved) push("saved", t("explore.savedOnly"), { saved: false });
  if (filters.seenExclude) push("seen", t("explore.hideSeen"), { seenExclude: false });
  return chips;
}
