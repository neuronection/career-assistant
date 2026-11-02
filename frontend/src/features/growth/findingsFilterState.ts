/**
 * The findings workspace filter vocabulary (plan 175 S2): pure helpers —
 * URL state serialization, active-filter counting, API param mapping.
 * No React, no IO; every function is unit-testable in isolation (the
 * exploreParams pattern, ui-conventions §2h).
 */

import type { FindingFeedParams, FindingFeedSort, FindingFeedState } from "@/api/autopilot";

export const FINDINGS_POSTED_WINDOWS = ["24h", "7d", "30d", "90d"] as const;
export const FINDINGS_SENIORITIES = [
  "intern",
  "junior",
  "mid",
  "senior",
  "lead",
  "principal",
] as const;
export const FINDINGS_SORTS: FindingFeedSort[] = ["newest", "score"];

export interface FindingsFilters {
  goal: string | null;
  runId: string | null;
  view: "flat" | "byrun";
  state: FindingFeedState;
  latest: boolean;
  hideApplied: boolean;
  sort: FindingFeedSort;
  minScore: number | null;
  coverageMin: number | null;
  org: string;
  source: string | null;
  seniority: string | null;
  remote: boolean;
  postedWithin: string;
}

export const DEFAULT_FINDINGS_FILTERS: FindingsFilters = {
  goal: null,
  runId: null,
  view: "flat",
  state: "open",
  latest: true,
  hideApplied: false,
  sort: "newest",
  minScore: null,
  coverageMin: null,
  org: "",
  source: null,
  seniority: null,
  remote: false,
  postedWithin: "",
};

const STATE_VALUES: FindingFeedState[] = ["open", "dismissed", "all"];
const VIEW_VALUES = ["flat", "byrun"] as const;

export function countActiveFindingsFilters(f: FindingsFilters): number {
  let count = 0;
  if (f.state !== DEFAULT_FINDINGS_FILTERS.state) count++;
  if (!f.latest) count++;
  if (f.hideApplied) count++;
  if (f.minScore !== null) count++;
  if (f.coverageMin !== null) count++;
  if (f.org.trim()) count++;
  if (f.source) count++;
  if (f.seniority) count++;
  if (f.remote) count++;
  if (f.postedWithin) count++;
  return count;
}

/** The query params the findings feed endpoint reads. */
export function toFeedParams(f: FindingsFilters): FindingFeedParams {
  return {
    goal_id: f.goal ?? undefined,
    run_id: f.runId ?? undefined,
    state: f.state,
    latest_per_posting: f.latest,
    sort: f.sort,
    min_score: f.minScore ?? undefined,
    coverage_min: f.coverageMin ?? undefined,
    org: f.org.trim() || undefined,
    source: f.source ?? undefined,
    seniority: f.seniority ?? undefined,
    remote: f.remote || undefined,
    posted_within: f.postedWithin || undefined,
    hide_applied: f.hideApplied || undefined,
  };
}

/** URLSearchParams → filters; unknown values fall back to defaults. */
export function parseFindingsFilters(params: URLSearchParams): FindingsFilters {
  const state = params.get("state");
  const view = params.get("view");
  const sort = params.get("sort");
  const postedWithin = params.get("posted_within");
  const seniority = params.get("seniority");
  return {
    goal: params.get("goal"),
    runId: params.get("run_id"),
    view: VIEW_VALUES.includes(view as "flat" | "byrun")
      ? (view as "flat" | "byrun")
      : DEFAULT_FINDINGS_FILTERS.view,
    state: STATE_VALUES.includes(state as FindingFeedState)
      ? (state as FindingFeedState)
      : DEFAULT_FINDINGS_FILTERS.state,
    latest: params.get("latest") !== "0",
    hideApplied: params.get("hide_applied") === "1",
    sort: FINDINGS_SORTS.includes(sort as FindingFeedSort)
      ? (sort as FindingFeedSort)
      : DEFAULT_FINDINGS_FILTERS.sort,
    minScore: numberParam(params.get("min_score"), 0, 10),
    coverageMin: numberParam(params.get("coverage_min"), 0, 20),
    org: params.get("org") ?? "",
    source: params.get("source") || null,
    seniority:
      seniority && (FINDINGS_SENIORITIES as readonly string[]).includes(seniority)
        ? seniority
        : null,
    remote: params.get("remote") === "1",
    postedWithin:
      postedWithin && (FINDINGS_POSTED_WINDOWS as readonly string[]).includes(postedWithin)
        ? postedWithin
        : "",
  };
}

/** Filters → the canonical search string; defaults are omitted. */
export function toFindingsSearchParams(f: FindingsFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (f.goal) params.set("goal", f.goal);
  if (f.runId) params.set("run_id", f.runId);
  if (f.view !== DEFAULT_FINDINGS_FILTERS.view) params.set("view", f.view);
  if (f.state !== DEFAULT_FINDINGS_FILTERS.state) params.set("state", f.state);
  if (!f.latest) params.set("latest", "0");
  if (f.hideApplied) params.set("hide_applied", "1");
  if (f.sort !== DEFAULT_FINDINGS_FILTERS.sort) params.set("sort", f.sort);
  if (f.minScore !== null) params.set("min_score", String(f.minScore));
  if (f.coverageMin !== null) params.set("coverage_min", String(f.coverageMin));
  if (f.org.trim()) params.set("org", f.org.trim());
  if (f.source) params.set("source", f.source);
  if (f.seniority) params.set("seniority", f.seniority);
  if (f.remote) params.set("remote", "1");
  if (f.postedWithin) params.set("posted_within", f.postedWithin);
  return params;
}

function numberParam(raw: string | null, min: number, max: number): number | null {
  if (raw === null || raw.trim() === "") return null;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < min || value > max) return null;
  return value;
}
