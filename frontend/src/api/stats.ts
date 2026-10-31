import { api } from "./client";

/**
 * Market statistics clients (plan 170): `/postings/stats/*` and
 * `/companies/stats/*`. The interfaces mirror the pydantic models in
 * `backend/app/schemas/stats.py` — snake_case, exactly the wire shapes.
 */

export type StatsStatusBasis = "open" | "all";
export type StatsTrend = "up" | "down" | "flat";
export type MarketWindow = "24h" | "7d" | "30d" | "90d" | "all";
export type MarketDimension =
  | "seniority"
  | "work_mode"
  | "employment"
  | "contract"
  | "education"
  | "source"
  | "location"
  | "org"
  | "family";
export type TimeseriesSplit =
  | "status"
  | "source"
  | "work_mode"
  | "seniority"
  | "employment";

export interface StatsDelta {
  count: number;
  prev: number;
  delta_pct: number | null;
  trend: StatsTrend;
}

export interface StatsSparkPoint {
  bucket: string;
  count: number;
}

export interface StatsFreshnessSource {
  source_key: string;
  status: "ok" | "stale" | "paused" | "never";
  last_success: string | null;
}

export interface StatsFreshness {
  as_of: string;
  stale_sources: StatsFreshnessSource[];
}

export interface StatsCoverage {
  salary: number;
  location: number;
  org_linked: number;
  skill_tagged: number;
}

export interface StatsInsight {
  kind: "volume" | "share" | "skill_lead";
  subject: string;
  delta_pct: number | null;
  baseline: number | null;
  text_key: string;
}

export interface PostingStatsSummary {
  as_of: string;
  status_basis: StatsStatusBasis;
  new_24h: StatsDelta;
  new_7d: StatsDelta;
  new_30d: StatsDelta;
  open_total: number;
  sparkline: StatsSparkPoint[];
  freshness: StatsFreshness;
}

export interface PostingStatsOverview {
  as_of: string;
  window: string;
  status_basis: StatsStatusBasis;
  start: string | null;
  end: string;
  new_in_range: StatsDelta;
  open_total: number;
  status_mix: Record<string, number>;
  coverage: StatsCoverage;
  insights: StatsInsight[];
}

export interface TimeseriesPoint {
  bucket: string;
  count: number;
  prev: number;
  ingestion: number;
  series: Record<string, number>;
}

export interface PostingStatsTimeseries {
  as_of: string;
  window: string;
  status_basis: StatsStatusBasis;
  start: string | null;
  end: string;
  bucket: "hour" | "day" | "week" | "month";
  split: TimeseriesSplit | null;
  points: TimeseriesPoint[];
}

export interface SkillStat {
  key: string;
  label: string;
  count: number;
  share: number;
  delta_pct: number | null;
  trend: StatsTrend;
}

export interface SkillCategory {
  key: string;
  count: number;
  share: number;
}

export interface SkillLevel {
  level: number;
  count: number;
}

export interface PostingStatsSkills {
  as_of: string;
  window: string;
  status_basis: StatsStatusBasis;
  start: string | null;
  end: string;
  top: SkillStat[];
  rising: SkillStat[];
  falling: SkillStat[];
  categories: SkillCategory[];
  levels: SkillLevel[];
  avg_level: number | null;
  priority: Record<string, number>;
  avg_skills_per_posting: number;
}

export interface BreakdownRow {
  key: string;
  count: number;
  share: number;
  prev: number;
  delta_pct: number | null;
  trend: StatsTrend;
}

export interface PostingStatsBreakdown {
  as_of: string;
  window: string;
  status_basis: StatsStatusBasis;
  start: string | null;
  end: string;
  dimension: MarketDimension;
  total: number;
  rows: BreakdownRow[];
}

export interface SalaryBucket {
  floor: number;
  ceiling: number;
  count: number;
}

export interface SalarySeniority {
  seniority: string;
  count: number;
  median: number | null;
}

export interface SalaryCurrency {
  currency: string;
  disclosed: number;
  coverage: number;
  thin_sample: boolean;
  p25: number | null;
  p50: number | null;
  p75: number | null;
  histogram: SalaryBucket[];
  by_seniority: SalarySeniority[];
  period_basis: Record<string, number>;
}

export interface PostingStatsSalary {
  as_of: string;
  window: string;
  status_basis: StatsStatusBasis;
  start: string | null;
  end: string;
  primary_currency: string | null;
  currencies: SalaryCurrency[];
}

export interface CompanyStatsSummary {
  as_of: string;
  window: string;
  status_basis: StatsStatusBasis;
  start: string | null;
  end: string;
  companies_hiring: number;
  new_companies: StatsDelta;
}

export interface CompanyHiring {
  key: string;
  name: string;
  open_postings: number;
  new_in_range: StatsDelta;
}

export interface IndustryMix {
  key: string;
  count: number;
  share: number;
}

export interface OpeningsBucket {
  bucket: string;
  count: number;
}

export interface CompanyStatsOverview {
  as_of: string;
  window: string;
  status_basis: StatsStatusBasis;
  start: string | null;
  end: string;
  top_hiring: CompanyHiring[];
  industry_mix: IndustryMix[];
  openings_histogram: OpeningsBucket[];
}

export interface MarketStatsQuery {
  window?: MarketWindow;
  from?: string;
  to?: string;
  status_basis?: StatsStatusBasis;
}

function queryParams(params: MarketStatsQuery): Record<string, string> {
  const query: Record<string, string> = {};
  if (params.from) query.from = params.from;
  if (params.to) query.to = params.to;
  if (params.from || params.to) query.window = "all";
  else if (params.window) query.window = params.window;
  if (params.status_basis) query.status_basis = params.status_basis;
  return query;
}

export async function fetchPostingStatsSummary(
  params: { status_basis?: StatsStatusBasis } = {},
): Promise<PostingStatsSummary> {
  const { data } = await api.get<PostingStatsSummary>("/postings/stats/summary", {
    params: queryParams(params),
  });
  return data;
}

export async function fetchPostingStatsOverview(
  params: MarketStatsQuery = {},
): Promise<PostingStatsOverview> {
  const { data } = await api.get<PostingStatsOverview>("/postings/stats/overview", {
    params: queryParams(params),
  });
  return data;
}

export async function fetchPostingStatsTimeseries(
  params: MarketStatsQuery & {
    bucket?: "hour" | "day" | "week" | "month";
    split?: TimeseriesSplit;
  } = {},
): Promise<PostingStatsTimeseries> {
  const { bucket, split, ...rest } = params;
  const { data } = await api.get<PostingStatsTimeseries>("/postings/stats/timeseries", {
    params: { ...queryParams(rest), ...(bucket ? { bucket } : {}), ...(split ? { split } : {}) },
  });
  return data;
}

export async function fetchPostingStatsSkills(
  params: MarketStatsQuery & { limit?: number } = {},
): Promise<PostingStatsSkills> {
  const { limit, ...rest } = params;
  const { data } = await api.get<PostingStatsSkills>("/postings/stats/skills", {
    params: { ...queryParams(rest), ...(limit ? { limit } : {}) },
  });
  return data;
}

export async function fetchPostingStatsBreakdown(
  dimension: MarketDimension,
  params: MarketStatsQuery & { limit?: number } = {},
): Promise<PostingStatsBreakdown> {
  const { limit, ...rest } = params;
  const { data } = await api.get<PostingStatsBreakdown>("/postings/stats/breakdown", {
    params: { ...queryParams(rest), dimension, ...(limit ? { limit } : {}) },
  });
  return data;
}

export async function fetchPostingStatsSalary(
  params: MarketStatsQuery = {},
): Promise<PostingStatsSalary> {
  const { data } = await api.get<PostingStatsSalary>("/postings/stats/salary", {
    params: queryParams(params),
  });
  return data;
}

export async function fetchCompanyStatsSummary(
  params: MarketStatsQuery = {},
): Promise<CompanyStatsSummary> {
  const { data } = await api.get<CompanyStatsSummary>("/companies/stats/summary", {
    params: queryParams(params),
  });
  return data;
}

export async function fetchCompanyStatsOverview(
  params: MarketStatsQuery & { limit?: number } = {},
): Promise<CompanyStatsOverview> {
  const { limit, ...rest } = params;
  const { data } = await api.get<CompanyStatsOverview>("/companies/stats/overview", {
    params: { ...queryParams(rest), ...(limit ? { limit } : {}) },
  });
  return data;
}
