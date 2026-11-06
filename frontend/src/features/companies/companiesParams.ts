import type { CompanyQuery } from "@/api/companies";

export const MIN_OPEN_OPTIONS = [1, 3, 5, 10] as const;

export const SORT_OPTIONS = [
  { value: "open_postings", labelKey: "companies.sortOpen" },
  { value: "name", labelKey: "companies.sortName" },
  { value: "recent", labelKey: "companies.sortRecent" },
] as const;

const SORTS = SORT_OPTIONS.map((option) => option.value) as ReadonlyArray<string>;
const MAX_LIST = 10;

export const DEFAULT_SORT = "open_postings";

export interface CompanyFilters {
  q: string;
  status: "all" | "new";
  workMode: string[];
  workModeExclude: string[];
  seniority: string[];
  seniorityExclude: string[];
  employment: string[];
  employmentExclude: string[];
  industries: string[];
  industriesExclude: string[];
  minOpen: number;
  location: string;
  sort: string;
}

export const DEFAULT_FILTERS: CompanyFilters = {
  q: "",
  status: "all",
  workMode: [],
  workModeExclude: [],
  seniority: [],
  seniorityExclude: [],
  employment: [],
  employmentExclude: [],
  industries: [],
  industriesExclude: [],
  minOpen: 0,
  location: "",
  sort: DEFAULT_SORT,
};

function csv(value: string | null): string[] {
  if (!value) return [];
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .slice(0, MAX_LIST);
}

function sortFrom(params: URLSearchParams): string {
  const value = params.get("sort") ?? DEFAULT_SORT;
  return SORTS.includes(value) ? value : DEFAULT_SORT;
}

export function parseFilters(params: URLSearchParams): CompanyFilters {
  const minOpen = Number(params.get("min_open"));
  return {
    q: params.get("q") ?? "",
    status: params.get("status") === "new" ? "new" : "all",
    workMode: csv(params.get("work_mode")),
    workModeExclude: csv(params.get("work_mode_exclude")),
    seniority: csv(params.get("seniority")),
    seniorityExclude: csv(params.get("seniority_exclude")),
    employment: csv(params.get("employment")),
    employmentExclude: csv(params.get("employment_exclude")),
    industries: csv(params.get("industry")),
    industriesExclude: csv(params.get("industry_exclude")),
    minOpen: (MIN_OPEN_OPTIONS as ReadonlyArray<number>).includes(minOpen) ? minOpen : 0,
    location: params.get("location") ?? "",
    sort: sortFrom(params),
  };
}

export function toParams(filters: CompanyFilters): CompanyQuery {
  const params: CompanyQuery = {};
  if (filters.q) params.q = filters.q;
  if (filters.workMode.length) params.work_mode = filters.workMode;
  if (filters.workModeExclude.length) params.work_mode_exclude = filters.workModeExclude;
  if (filters.seniority.length) params.seniority = filters.seniority;
  if (filters.seniorityExclude.length) params.seniority_exclude = filters.seniorityExclude;
  if (filters.employment.length) params.employment = filters.employment;
  if (filters.employmentExclude.length) params.employment_exclude = filters.employmentExclude;
  if (filters.industries.length) params.industry = filters.industries;
  if (filters.industriesExclude.length) params.industry_exclude = filters.industriesExclude;
  if (filters.minOpen) params.min_open = filters.minOpen;
  if (filters.location) params.location = filters.location;
  if (filters.sort !== DEFAULT_SORT) params.sort = filters.sort;
  return params;
}

export function toSearchParams(filters: CompanyFilters): URLSearchParams {
  const params = new URLSearchParams();
  const values = toParams(filters);
  if (filters.status === "new") params.set("status", "new");
  for (const [key, value] of Object.entries(values)) {
    if (value == null) continue;
    if (Array.isArray(value)) {
      params.set(key, value.join(","));
    } else {
      params.set(key, String(value));
    }
  }
  return params;
}

export function countActive(filters: CompanyFilters): number {
  return (
    filters.workMode.length +
    filters.workModeExclude.length +
    filters.seniority.length +
    filters.seniorityExclude.length +
    filters.employment.length +
    filters.employmentExclude.length +
    filters.industries.length +
    filters.industriesExclude.length +
    (filters.minOpen ? 1 : 0) +
    (filters.location ? 1 : 0) +
    (filters.status === "new" ? 1 : 0)
  );
}

type Translate = (key: string, options?: Record<string, unknown>) => string;

export interface CompanyFilterChip {
  key: string;
  label: string;
  patch: Partial<CompanyFilters>;
}

const FACET_AXES: Array<{
  axis: "work_mode" | "seniority" | "employment" | "industries";
  includeKey: keyof CompanyFilters;
  excludeKey: keyof CompanyFilters;
}> = [
  { axis: "work_mode", includeKey: "workMode", excludeKey: "workModeExclude" },
  { axis: "seniority", includeKey: "seniority", excludeKey: "seniorityExclude" },
  { axis: "employment", includeKey: "employment", excludeKey: "employmentExclude" },
  { axis: "industries", includeKey: "industries", excludeKey: "industriesExclude" },
];

/** One removable chip per applied company filter (plan 209) — the compact
 * rail's page-level summary. */
export function companiesFilterChips(filters: CompanyFilters, t: Translate): CompanyFilterChip[] {
  const chips: CompanyFilterChip[] = [];
  const push = (key: string, label: string, patch: Partial<CompanyFilters>) =>
    chips.push({ key, label, patch });
  const facetLabel = (axis: string, value: string) =>
    t(`companies.facet.${axis}.${value}`, { defaultValue: value.replace(/_/g, " ") });

  if (filters.q) push("q", t("presets.summary.query", { value: filters.q }), { q: "" });
  if (filters.status === "new") {
    push("status", t("companies.filter.new"), { status: "all" });
  }
  for (const facet of FACET_AXES) {
    const include = filters[facet.includeKey] as string[];
    const exclude = filters[facet.excludeKey] as string[];
    for (const value of include) {
      push(`${facet.axis}-${value}`, facetLabel(facet.axis, value), {
        [facet.includeKey]: include.filter((entry) => entry !== value),
      } as Partial<CompanyFilters>);
    }
    for (const value of exclude) {
      push(`${facet.axis}-exclude-${value}`, `− ${facetLabel(facet.axis, value)}`, {
        [facet.excludeKey]: exclude.filter((entry) => entry !== value),
      } as Partial<CompanyFilters>);
    }
  }
  if (filters.minOpen) {
    push("min-open", t("companies.minOpenN", { count: filters.minOpen }), { minOpen: 0 });
  }
  if (filters.location) {
    push(
      "location",
      t("presets.summary.include", {
        label: t("companies.facetTitle.locations"),
        list: filters.location,
      }),
      { location: "" }
    );
  }
  return chips;
}

