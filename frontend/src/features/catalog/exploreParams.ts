import type { ExploreParams } from "@/types";

export const POSTED_WINDOWS = [
  { value: "24h", labelKey: "explore.posted.h24" },
  { value: "7d", labelKey: "explore.posted.d7" },
  { value: "30d", labelKey: "explore.posted.d30" },
  { value: "90d", labelKey: "explore.posted.d90" },
] as const;

export const CONTRACT_VALUES = [
  "permanent",
  "temporary",
  "contract",
  "freelance",
  "b2b",
  "internship",
  "apprenticeship",
] as const;

export const TRAVEL_VALUES = ["none", "occasional", "frequent"] as const;
export const SCHEDULE_VALUES = [
  "shift_work",
  "on_call",
  "nights",
  "weekends",
  "flexible",
] as const;

export const SORT_OPTIONS = [
  { value: "fit", labelKey: "explore.sortFit" },
  { value: "fresh", labelKey: "explore.sortFresh" },
  { value: "salary", labelKey: "explore.sortSalary" },
  { value: "relevance", labelKey: "explore.sortRelevance" },
  { value: "smart", labelKey: "explore.sortSmart" },
] as const;

export const SORTS = SORT_OPTIONS.map((option) => option.value) as ReadonlyArray<string>;

const SKILL_MODES = ["all", "any"] as const;
const MAX_LIST = 12;

export interface SkillFilter {
  key: string;
  level: number | null;
}

export interface Filters {
  q: string;
  skills: SkillFilter[];
  skillsExclude: string[];
  skillMode: "all" | "any";
  postedWithin: string;
  salaryMin: string;
  seniority: string[];
  seniorityExclude: string[];
  remotePolicy: string[];
  remotePolicyExclude: string[];
  source: string[];
  sourceExclude: string[];
  extractedOnly: boolean;
  saved: boolean;
  seenExclude: boolean;
  sort: string;
  contract: string[];
  contractExclude: string[];
  travel: string[];
  travelExclude: string[];
  schedule: string[];
  scheduleExclude: string[];
  orgs: string[];
  orgsExclude: string[];
}

export const DEFAULT_FILTERS: Filters = {
  q: "",
  skills: [],
  skillsExclude: [],
  skillMode: "all",
  postedWithin: "",
  salaryMin: "",
  seniority: [],
  seniorityExclude: [],
  remotePolicy: [],
  remotePolicyExclude: [],
  source: [],
  sourceExclude: [],
  extractedOnly: false,
  saved: false,
  seenExclude: false,
  sort: "fit",
  contract: [],
  contractExclude: [],
  travel: [],
  travelExclude: [],
  schedule: [],
  scheduleExclude: [],
  orgs: [],
  orgsExclude: [],
};

const VALUE_SETS: Record<string, ReadonlyArray<string>> = {
  contract: CONTRACT_VALUES,
  contract_exclude: CONTRACT_VALUES,
  travel: TRAVEL_VALUES,
  travel_exclude: TRAVEL_VALUES,
  schedule: SCHEDULE_VALUES,
  schedule_exclude: SCHEDULE_VALUES,
  posted_within: POSTED_WINDOWS.map((option) => option.value),
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

function flag(params: URLSearchParams, key: string): boolean {
  const value = (params.get(key) ?? "").trim().toLowerCase();
  return value !== "" && !["0", "false", "no", "off"].includes(value);
}

function skillEntries(value: string | null): SkillFilter[] {
  return csv(value)
    .map((entry) => {
      const [rawKey, rawLevel] = entry.split(":");
      const key = (rawKey ?? "").trim().toLowerCase();
      if (!key) return null;
      if (rawLevel === undefined || rawLevel === "") return { key, level: null };
      const level = Number(rawLevel);
      if (!Number.isInteger(level) || level < 1 || level > 10) return null;
      return { key, level };
    })
    .filter((entry): entry is SkillFilter => entry !== null)
    .slice(0, MAX_LIST);
}

export function parseFilters(params: URLSearchParams): Filters {
  const sortValue = params.get("sort") ?? "fit";
  const q = params.get("q") ?? "";
  const sort = SORTS.includes(sortValue) ? sortValue : "fit";
  const salary = Number(params.get("salary_min"));
  return {
    q,
    skills: skillEntries(params.get("skills")),
    skillsExclude: csv(params.get("skill_exclude")).map((key) => key.toLowerCase()),
    skillMode: (params.get("skill_mode") === "any" ? "any" : "all") as "all" | "any",
    postedWithin: axis(params, "posted_within")[0] ?? "",
    salaryMin: Number.isFinite(salary) && salary > 0 ? String(salary) : "",
    seniority: axis(params, "seniority"),
    seniorityExclude: axis(params, "seniority_exclude"),
    remotePolicy: axis(params, "remote_policy"),
    remotePolicyExclude: axis(params, "remote_policy_exclude"),
    source: axis(params, "source"),
    sourceExclude: axis(params, "source_exclude"),
    extractedOnly: flag(params, "extracted_only"),
    saved: flag(params, "saved"),
    seenExclude: flag(params, "seen_exclude"),
    sort: sort === "relevance" && !q.trim() ? "fit" : sort,
    contract: axis(params, "contract"),
    contractExclude: axis(params, "contract_exclude"),
    travel: axis(params, "travel"),
    travelExclude: axis(params, "travel_exclude"),
    schedule: axis(params, "schedule"),
    scheduleExclude: axis(params, "schedule_exclude"),
    orgs: params.getAll("org").filter(Boolean).slice(0, MAX_LIST),
    orgsExclude: params.getAll("org_exclude").filter(Boolean).slice(0, MAX_LIST),
  };
}

export function toParams(filters: Filters): ExploreParams {
  const params: ExploreParams = {};
  if (filters.q) params.q = filters.q;
  if (filters.skills.length) {
    params.skills = filters.skills
      .map((skill) => (skill.level ? `${skill.key}:${skill.level}` : skill.key))
      .join(",");
    if (filters.skillMode === "any") params.skill_mode = "any";
  }
  if (filters.skillsExclude.length) params.skill_exclude = filters.skillsExclude.join(",");
  if (filters.postedWithin) params.posted_within = filters.postedWithin;
  if (filters.salaryMin) params.salary_min = Number(filters.salaryMin);
  if (filters.seniority.length) params.seniority = filters.seniority.join(",");
  if (filters.seniorityExclude.length)
    params.seniority_exclude = filters.seniorityExclude.join(",");
  if (filters.remotePolicy.length) params.remote_policy = filters.remotePolicy.join(",");
  if (filters.remotePolicyExclude.length)
    params.remote_policy_exclude = filters.remotePolicyExclude.join(",");
  if (filters.source.length) params.source = filters.source.join(",");
  if (filters.sourceExclude.length) params.source_exclude = filters.sourceExclude.join(",");
  if (filters.contract.length) params.contract = filters.contract.join(",");
  if (filters.contractExclude.length) params.contract_exclude = filters.contractExclude.join(",");
  if (filters.travel.length) params.travel = filters.travel.join(",");
  if (filters.travelExclude.length) params.travel_exclude = filters.travelExclude.join(",");
  if (filters.schedule.length) params.schedule = filters.schedule.join(",");
  if (filters.scheduleExclude.length) params.schedule_exclude = filters.scheduleExclude.join(",");
  if (filters.orgs.length) params.org = filters.orgs;
  if (filters.orgsExclude.length) params.org_exclude = filters.orgsExclude;
  if (filters.extractedOnly) params.extracted_only = true;
  if (filters.saved) params.saved = true;
  if (filters.seenExclude) params.seen_exclude = true;
  if (filters.sort !== "fit") params.sort = filters.sort;
  return params;
}

export function filtersFromRecord(record: Record<string, unknown> | null | undefined): Filters {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(record ?? {})) {
    if (value == null) continue;
    if (Array.isArray(value)) {
      for (const entry of value) params.append(key, String(entry));
    } else {
      params.set(key, String(value));
    }
  }
  return parseFilters(params);
}

export function toSearchParams(filters: Filters): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(toParams(filters))) {
    if (value == null) continue;
    if (Array.isArray(value)) {
      for (const entry of value) params.append(key, String(entry));
    } else {
      params.set(key, String(value));
    }
  }
  return params;
}

export function countActive(filters: Filters): number {
  let count = 0;
  if (filters.q) count++;
  count += filters.skills.length + filters.skillsExclude.length;
  if (filters.skillMode !== "all" && filters.skills.length) count++;
  if (filters.postedWithin) count++;
  if (filters.salaryMin) count++;
  count += filters.seniority.length + filters.seniorityExclude.length;
  count += filters.remotePolicy.length + filters.remotePolicyExclude.length;
  count += filters.source.length + filters.sourceExclude.length;
  count += filters.contract.length + filters.contractExclude.length;
  count += filters.travel.length + filters.travelExclude.length;
  count += filters.schedule.length + filters.scheduleExclude.length;
  count += filters.orgs.length + filters.orgsExclude.length;
  if (filters.extractedOnly) count++;
  if (filters.saved) count++;
  if (filters.seenExclude) count++;
  return count;
}
