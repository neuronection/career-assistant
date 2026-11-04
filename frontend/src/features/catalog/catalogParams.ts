/**
 * Pure URL state for the catalog filter rail (plan 190), mirroring
 * `exploreParams.ts`: parse, serialize, count and summarize — no React,
 * no IO. The URL is the state; the store receives a translated API
 * parameter object via `catalogApiParams`.
 */

import { CONTRACT_VALUES, SCHEDULE_VALUES, TRAVEL_VALUES } from "./exploreParams";

export { CONTRACT_VALUES, SCHEDULE_VALUES, TRAVEL_VALUES };

const SKILL_MODES = ["all", "any"] as const;
const MAX_LIST = 20;

export const EDUCATION_VALUES = [
  "no_formal",
  "middle_school",
  "high_school",
  "vocational",
  "bachelor",
  "master",
  "doctorate",
] as const;

export const DEMAND_VALUES = ["declining", "stable", "growing", "hot"] as const;

export const ENVIRONMENT_VALUES = [
  "office",
  "field",
  "lab",
  "studio",
  "workshop",
  "clinic",
  "classroom",
  "vehicle",
  "outdoors",
  "remote",
  "kitchen",
  "stage",
] as const;

export const CATALOG_SORT_OPTIONS = [
  { value: "title", labelKey: "catalog.sort.title" },
  { value: "demand", labelKey: "catalog.sort.demand" },
  { value: "salary", labelKey: "catalog.sort.salary" },
  { value: "open_roles", labelKey: "catalog.sort.openRoles" },
  { value: "family", labelKey: "catalog.sort.family" },
] as const;

export const CATALOG_SORTS = CATALOG_SORT_OPTIONS.map((option) => option.value);

export interface CatalogSkillFilter {
  key: string;
  level: number | null;
}

export interface CatalogFilters {
  q: string;
  family: string;
  skills: CatalogSkillFilter[];
  skillsExclude: string[];
  skillMode: "all" | "any";
  minLevel: number | null;
  interests: string[];
  interestsExclude: string[];
  education: string[];
  educationExclude: string[];
  educationMin: string;
  demand: string[];
  demandExclude: string[];
  salaryMin: string;
  salaryMax: string;
  contract: string[];
  contractExclude: string[];
  schedule: string[];
  scheduleExclude: string[];
  travel: string[];
  travelExclude: string[];
  environment: string[];
  environmentExclude: string[];
  experienceMax: string;
  hasRoles: boolean | null;
  sort: string;
}

export const DEFAULT_CATALOG_FILTERS: CatalogFilters = {
  q: "",
  family: "",
  skills: [],
  skillsExclude: [],
  skillMode: "all",
  minLevel: null,
  interests: [],
  interestsExclude: [],
  education: [],
  educationExclude: [],
  educationMin: "",
  demand: [],
  demandExclude: [],
  salaryMin: "",
  salaryMax: "",
  contract: [],
  contractExclude: [],
  schedule: [],
  scheduleExclude: [],
  travel: [],
  travelExclude: [],
  environment: [],
  environmentExclude: [],
  experienceMax: "",
  hasRoles: null,
  sort: "title",
};

export interface CatalogActiveChip {
  axis: string;
  value: string;
  label: string;
  labelKey?: string;
  kind: "include" | "exclude" | "bound" | "flag";
}

const VALUE_SETS: Record<string, ReadonlyArray<string>> = {
  education: EDUCATION_VALUES,
  education_exclude: EDUCATION_VALUES,
  education_min: EDUCATION_VALUES,
  demand: DEMAND_VALUES,
  demand_exclude: DEMAND_VALUES,
  contract: CONTRACT_VALUES,
  contract_exclude: CONTRACT_VALUES,
  schedule: SCHEDULE_VALUES,
  schedule_exclude: SCHEDULE_VALUES,
  travel: TRAVEL_VALUES,
  travel_exclude: TRAVEL_VALUES,
  environment: ENVIRONMENT_VALUES,
  environment_exclude: ENVIRONMENT_VALUES,
  skill_mode: SKILL_MODES,
};

function csv(value: string | null): string[] {
  if (!value) return [];
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .slice(0, MAX_LIST);
}

function axis(params: URLSearchParams, key: string): string[] {
  const values = csv(params.get(key));
  const allowed = VALUE_SETS[key];
  if (!allowed) return values;
  return values.filter((value) => allowed.includes(value));
}

function lowerCsv(value: string | null): string[] {
  return csv(value).map((entry) => entry.toLowerCase());
}

function numberInRange(value: string | null, minimum: number, maximum: number): string {
  if (value == null || value === "") return "";
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= minimum && parsed <= maximum
    ? String(parsed)
    : "";
}

function skillEntries(value: string | null): CatalogSkillFilter[] {
  return csv(value)
    .map((entry) => {
      const [rawKey, levelPart] = entry.split("@");
      const normalized = rawKey.trim().toLowerCase();
      if (!normalized) return null;
      if (levelPart === undefined || levelPart === "") return { key: normalized, level: null };
      const level = Number(levelPart);
      if (!Number.isInteger(level) || level < 1 || level > 10) return null;
      return { key: normalized, level };
    })
    .filter((entry): entry is CatalogSkillFilter => entry !== null)
    .slice(0, MAX_LIST);
}

function flagState(value: string | null): boolean | null {
  if (value == null || value === "") return null;
  const normalized = value.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) return true;
  if (["0", "false", "no", "off"].includes(normalized)) return false;
  return null;
}

export function parseCatalogParams(params: URLSearchParams): CatalogFilters {
  const sort = params.get("sort") ?? "title";
  const minLevel = Number(params.get("skill_min_level"));
  return {
    q: (params.get("q") ?? "").trim().slice(0, 200),
    family: (params.get("family") ?? "").trim().toLowerCase(),
    skills: skillEntries(params.get("skills")),
    skillsExclude: lowerCsv(params.get("skill_exclude")),
    skillMode: params.get("skill_mode") === "any" ? "any" : "all",
    minLevel:
      Number.isInteger(minLevel) && minLevel >= 1 && minLevel <= 10
        ? minLevel
        : null,
    interests: csv(params.get("interests")),
    interestsExclude: csv(params.get("interest_exclude")),
    education: axis(params, "education"),
    educationExclude: axis(params, "education_exclude"),
    educationMin: axis(params, "education_min")[0] ?? "",
    demand: axis(params, "demand"),
    demandExclude: axis(params, "demand_exclude"),
    salaryMin: numberInRange(params.get("salary_min"), 0, 10_000_000),
    salaryMax: numberInRange(params.get("salary_max"), 0, 10_000_000),
    contract: axis(params, "contract"),
    contractExclude: axis(params, "contract_exclude"),
    schedule: axis(params, "schedule"),
    scheduleExclude: axis(params, "schedule_exclude"),
    travel: axis(params, "travel"),
    travelExclude: axis(params, "travel_exclude"),
    environment: axis(params, "environment"),
    environmentExclude: axis(params, "environment_exclude"),
    experienceMax: numberInRange(params.get("experience_max_years"), 0, 50),
    hasRoles: flagState(params.get("has_roles")),
    sort: CATALOG_SORTS.includes(sort as (typeof CATALOG_SORTS)[number]) ? sort : "title",
  };
}

export function catalogParams(filters: CatalogFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.family) params.set("family", filters.family);
  if (filters.skills.length) {
    params.set(
      "skills",
      filters.skills
        .map((skill) => (skill.level ? `${skill.key}@${skill.level}` : skill.key))
        .join(",")
    );
  }
  if (filters.skillsExclude.length) params.set("skill_exclude", filters.skillsExclude.join(","));
  if (filters.skillMode !== "all" && filters.skills.length) {
    params.set("skill_mode", filters.skillMode);
  }
  if (filters.minLevel != null) params.set("skill_min_level", String(filters.minLevel));
  if (filters.interests.length) params.set("interests", filters.interests.join(","));
  if (filters.interestsExclude.length) {
    params.set("interest_exclude", filters.interestsExclude.join(","));
  }
  if (filters.education.length) params.set("education", filters.education.join(","));
  if (filters.educationExclude.length) {
    params.set("education_exclude", filters.educationExclude.join(","));
  }
  if (filters.educationMin) params.set("education_min", filters.educationMin);
  if (filters.demand.length) params.set("demand", filters.demand.join(","));
  if (filters.demandExclude.length) params.set("demand_exclude", filters.demandExclude.join(","));
  if (filters.salaryMin) params.set("salary_min", filters.salaryMin);
  if (filters.salaryMax) params.set("salary_max", filters.salaryMax);
  if (filters.contract.length) params.set("contract", filters.contract.join(","));
  if (filters.contractExclude.length) {
    params.set("contract_exclude", filters.contractExclude.join(","));
  }
  if (filters.schedule.length) params.set("schedule", filters.schedule.join(","));
  if (filters.scheduleExclude.length) {
    params.set("schedule_exclude", filters.scheduleExclude.join(","));
  }
  if (filters.travel.length) params.set("travel", filters.travel.join(","));
  if (filters.travelExclude.length) params.set("travel_exclude", filters.travelExclude.join(","));
  if (filters.environment.length) params.set("environment", filters.environment.join(","));
  if (filters.environmentExclude.length) {
    params.set("environment_exclude", filters.environmentExclude.join(","));
  }
  if (filters.experienceMax) params.set("experience_max_years", filters.experienceMax);
  if (filters.hasRoles !== null) params.set("has_roles", filters.hasRoles ? "1" : "0");
  if (filters.sort !== "title") params.set("sort", filters.sort);
  return params;
}

export function catalogApiParams(
  filters: CatalogFilters,
  withFacets = true
): Record<string, unknown> {
  const api: Record<string, unknown> = {
    page_size: 100,
    sort: filters.sort,
    with_facets: withFacets,
  };
  if (filters.q) api.q = filters.q;
  if (filters.family) api.family_key = filters.family;
  if (filters.skills.length) {
    api.skills = filters.skills
      .map((skill) => (skill.level ? `${skill.key}@${skill.level}` : skill.key))
      .join(",");
  }
  if (filters.skillsExclude.length) api.skill_exclude = filters.skillsExclude.join(",");
  if (filters.skillMode !== "all" && filters.skills.length) api.skill_mode = filters.skillMode;
  if (filters.minLevel != null) api.skill_min_level = filters.minLevel;
  if (filters.interests.length) api.interests = filters.interests.join(",");
  if (filters.interestsExclude.length) {
    api.interest_exclude = filters.interestsExclude.join(",");
  }
  if (filters.education.length) api.education = filters.education.join(",");
  if (filters.educationExclude.length) api.education_exclude = filters.educationExclude.join(",");
  if (filters.educationMin) api.education_min = filters.educationMin;
  if (filters.demand.length) api.demand = filters.demand.join(",");
  if (filters.demandExclude.length) api.demand_exclude = filters.demandExclude.join(",");
  if (filters.salaryMin) api.salary_min = Number(filters.salaryMin);
  if (filters.salaryMax) api.salary_max = Number(filters.salaryMax);
  if (filters.contract.length) api.contract = filters.contract.join(",");
  if (filters.contractExclude.length) api.contract_exclude = filters.contractExclude.join(",");
  if (filters.schedule.length) api.schedule = filters.schedule.join(",");
  if (filters.scheduleExclude.length) api.schedule_exclude = filters.scheduleExclude.join(",");
  if (filters.travel.length) api.travel = filters.travel.join(",");
  if (filters.travelExclude.length) api.travel_exclude = filters.travelExclude.join(",");
  if (filters.environment.length) api.environment = filters.environment.join(",");
  if (filters.environmentExclude.length) {
    api.environment_exclude = filters.environmentExclude.join(",");
  }
  if (filters.experienceMax) api.experience_max_years = Number(filters.experienceMax);
  if (filters.hasRoles !== null) api.has_roles = filters.hasRoles;
  return api;
}

export function countActiveCatalogFilters(filters: CatalogFilters): number {
  let count = 0;
  if (filters.q) count++;
  if (filters.family) count++;
  count += filters.skills.length + filters.skillsExclude.length;
  if (filters.skillMode !== "all" && filters.skills.length) count++;
  if (filters.minLevel != null) count++;
  count += filters.interests.length + filters.interestsExclude.length;
  count += filters.education.length + filters.educationExclude.length;
  if (filters.educationMin) count++;
  count += filters.demand.length + filters.demandExclude.length;
  if (filters.salaryMin) count++;
  if (filters.salaryMax) count++;
  count += filters.contract.length + filters.contractExclude.length;
  count += filters.schedule.length + filters.scheduleExclude.length;
  count += filters.travel.length + filters.travelExclude.length;
  count += filters.environment.length + filters.environmentExclude.length;
  if (filters.experienceMax) count++;
  if (filters.hasRoles !== null) count++;
  return count;
}

export function catalogActiveChips(filters: CatalogFilters): CatalogActiveChip[] {
  const chips: CatalogActiveChip[] = [];
  const add = (
    axis: string,
    value: string,
    kind: CatalogActiveChip["kind"],
    label = value,
    labelKey?: string
  ) => chips.push({ axis, value, kind, label, labelKey });

  if (filters.q) add("q", filters.q, "flag", filters.q, "catalog.chips.query");
  if (filters.family) add("family", filters.family, "include", filters.family, "catalog.chips.family");
  for (const skill of filters.skills) {
    add("skills", skill.key, "include", skill.key);
  }
  for (const skill of filters.skillsExclude) {
    add("skills", skill, "exclude", `− ${skill}`);
  }
  if (filters.skillMode !== "all" && filters.skills.length) {
    add("skillMode", filters.skillMode, "flag", filters.skillMode, "catalog.chips.skillMode");
  }
  if (filters.minLevel != null) {
    add("minLevel", String(filters.minLevel), "bound", `≥ ${filters.minLevel}`, "catalog.chips.minLevel");
  }
  for (const interest of filters.interests) add("interests", interest, "include", interest);
  for (const interest of filters.interestsExclude) {
    add("interests", interest, "exclude", `− ${interest}`);
  }
  for (const value of filters.education) {
    add("education", value, "include", value, `catalog.facetValue.${value}`);
  }
  for (const value of filters.educationExclude) {
    add("education", value, "exclude", `− ${value}`, `catalog.facetValue.${value}`);
  }
  if (filters.educationMin) {
    add(
      "educationMin",
      filters.educationMin,
      "bound",
      filters.educationMin,
      `catalog.facetValue.${filters.educationMin}`
    );
  }
  for (const value of filters.demand) {
    add("demand", value, "include", value, `catalog.facetValue.${value}`);
  }
  for (const value of filters.demandExclude) {
    add("demand", value, "exclude", `− ${value}`, `catalog.facetValue.${value}`);
  }
  if (filters.salaryMin) {
    add("salary", "min", "bound", `≥ ${filters.salaryMin}`, "catalog.chips.salaryMin");
  }
  if (filters.salaryMax) {
    add("salary", "max", "bound", `≤ ${filters.salaryMax}`, "catalog.chips.salaryMax");
  }
  for (const value of filters.contract) {
    add("contract", value, "include", value, `catalog.facetValue.${value}`);
  }
  for (const value of filters.contractExclude) {
    add("contract", value, "exclude", `− ${value}`, `catalog.facetValue.${value}`);
  }
  for (const value of filters.schedule) {
    add("schedule", value, "include", value, `catalog.facetValue.${value}`);
  }
  for (const value of filters.scheduleExclude) {
    add("schedule", value, "exclude", `− ${value}`, `catalog.facetValue.${value}`);
  }
  for (const value of filters.travel) {
    add("travel", value, "include", value, `catalog.facetValue.${value}`);
  }
  for (const value of filters.travelExclude) {
    add("travel", value, "exclude", `− ${value}`, `catalog.facetValue.${value}`);
  }
  for (const value of filters.environment) {
    add("environment", value, "include", value, `catalog.facetValue.${value}`);
  }
  for (const value of filters.environmentExclude) {
    add("environment", value, "exclude", `− ${value}`, `catalog.facetValue.${value}`);
  }
  if (filters.experienceMax) {
    add(
      "experienceMax",
      filters.experienceMax,
      "bound",
      `≤ ${filters.experienceMax}`,
      "catalog.chips.experienceMax"
    );
  }
  if (filters.hasRoles !== null) {
    add(
      "hasRoles",
      String(filters.hasRoles),
      "flag",
      filters.hasRoles ? "has roles" : "no roles",
      filters.hasRoles ? "catalog.chips.hasRoles" : "catalog.chips.noRoles"
    );
  }
  return chips;
}

export function removeCatalogChip(
  filters: CatalogFilters,
  chip: CatalogActiveChip
): Partial<CatalogFilters> {
  const drop = (values: string[]) => values.filter((value) => value !== chip.value);
  switch (chip.axis) {
    case "q":
      return { q: "" };
    case "family":
      return { family: "" };
    case "skills":
      if (chip.kind === "include") {
        const skills = filters.skills.filter((skill) => skill.key !== chip.value);
        return { skills, ...(skills.length === 0 ? { minLevel: null } : {}) };
      }
      return { skillsExclude: drop(filters.skillsExclude) };
    case "minLevel":
      return { minLevel: null };
    case "skillMode":
      return { skillMode: "all" };
    case "interests":
      return chip.kind === "include"
        ? { interests: drop(filters.interests) }
        : { interestsExclude: drop(filters.interestsExclude) };
    case "education":
      return chip.kind === "include"
        ? { education: drop(filters.education) }
        : { educationExclude: drop(filters.educationExclude) };
    case "educationMin":
      return { educationMin: "" };
    case "demand":
      return chip.kind === "include"
        ? { demand: drop(filters.demand) }
        : { demandExclude: drop(filters.demandExclude) };
    case "salary":
      return chip.value === "min" ? { salaryMin: "" } : { salaryMax: "" };
    case "contract":
      return chip.kind === "include"
        ? { contract: drop(filters.contract) }
        : { contractExclude: drop(filters.contractExclude) };
    case "schedule":
      return chip.kind === "include"
        ? { schedule: drop(filters.schedule) }
        : { scheduleExclude: drop(filters.scheduleExclude) };
    case "travel":
      return chip.kind === "include"
        ? { travel: drop(filters.travel) }
        : { travelExclude: drop(filters.travelExclude) };
    case "environment":
      return chip.kind === "include"
        ? { environment: drop(filters.environment) }
        : { environmentExclude: drop(filters.environmentExclude) };
    case "experienceMax":
      return { experienceMax: "" };
    case "hasRoles":
      return { hasRoles: null };
    default:
      return {};
  }
}
