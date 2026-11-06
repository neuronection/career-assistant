import type {
  CompanyStatsOverview,
  CompanyStatsSummary,
  PostingStatsBreakdown,
  PostingStatsSalary,
  PostingStatsSkills,
  PostingStatsSummary,
  PostingStatsTimeseries,
  SkillStat,
} from "@/api/stats";
import type { CsvRows } from "@/components/stats/statsExport";

export const CSV_HEADER_VOLUME = ["bucket", "count", "prev", "ingestion"];

export function volumeCsv(series: PostingStatsTimeseries): CsvRows {
  return [
    CSV_HEADER_VOLUME,
    ...series.points.map((point) => [point.bucket, point.count, point.prev, point.ingestion]),
  ];
}

function skillRowsCsv(label: string, rows: SkillStat[]): CsvRows {
  return [
    [label, "key", "count", "share", "delta_pct", "trend"],
    ...rows.map((row) => [row.key, row.label, row.count, row.share, row.delta_pct ?? "", row.trend]),
  ];
}

export function skillsCsv(skills: PostingStatsSkills): CsvRows {
  return [
    ...skillRowsCsv("top", skills.top),
    ...skillRowsCsv("rising", skills.rising),
    ...skillRowsCsv("falling", skills.falling),
  ];
}

export function breakdownCsv(breakdown: PostingStatsBreakdown): CsvRows {
  return [
    ["key", "count", "share", "prev", "delta_pct", "trend"],
    ...breakdown.rows.map((row) => [
      row.key,
      row.count,
      row.share,
      row.prev,
      row.delta_pct ?? "",
      row.trend,
    ]),
  ];
}

export function salaryCsv(salary: PostingStatsSalary): CsvRows {
  const rows: CsvRows = [["currency", "disclosed", "coverage", "thin_sample", "p25", "p50", "p75"]];
  for (const currency of salary.currencies) {
    rows.push([
      currency.currency,
      currency.disclosed,
      currency.coverage,
      currency.thin_sample,
      currency.p25 ?? "",
      currency.p50 ?? "",
      currency.p75 ?? "",
    ]);
    for (const seniority of currency.by_seniority) {
      rows.push([`  ${seniority.seniority}`, seniority.count, seniority.median ?? ""]);
    }
  }
  return rows;
}

export function companiesCsv(overview: CompanyStatsOverview): CsvRows {
  return [
    ["company", "open_postings", "new_in_range", "delta_pct", "trend"],
    ...overview.top_hiring.map((row) => [
      row.name,
      row.open_postings,
      row.new_in_range.count,
      row.new_in_range.delta_pct ?? "",
      row.new_in_range.trend,
    ]),
  ];
}

export interface DashboardCsvSource {
  summary: PostingStatsSummary | null;
  series: PostingStatsTimeseries | null;
  skills: PostingStatsSkills | null;
  breakdown: PostingStatsBreakdown | null;
  salary: PostingStatsSalary | null;
  companySummary: CompanyStatsSummary | null;
  companyOverview: CompanyStatsOverview | null;
}

export function allExportRows({
  summary,
  series,
  skills,
  breakdown,
  salary,
  companySummary,
  companyOverview,
}: DashboardCsvSource): CsvRows {
  const rows: CsvRows = [];
  if (summary) {
    rows.push(
      ["pulse", "count", "prev", "delta_pct", "trend"],
      ["new_24h", summary.new_24h.count, summary.new_24h.prev, summary.new_24h.delta_pct ?? "", summary.new_24h.trend],
      ["new_7d", summary.new_7d.count, summary.new_7d.prev, summary.new_7d.delta_pct ?? "", summary.new_7d.trend],
      ["new_30d", summary.new_30d.count, summary.new_30d.prev, summary.new_30d.delta_pct ?? "", summary.new_30d.trend],
      ["open_total", summary.open_total],
    );
  }
  if (series) rows.push([], ["volume"], ...volumeCsv(series));
  if (skills) rows.push([], ["skills"], ...skillsCsv(skills));
  if (breakdown) rows.push([], [`breakdown:${breakdown.dimension}`], ...breakdownCsv(breakdown));
  if (salary) rows.push([], ["salary"], ...salaryCsv(salary));
  if (companySummary) {
    rows.push(
      [],
      ["companies"],
      ["companies_hiring", companySummary.companies_hiring],
      [
        "new_companies",
        companySummary.new_companies.count,
        companySummary.new_companies.prev,
        companySummary.new_companies.delta_pct ?? "",
        companySummary.new_companies.trend,
      ],
    );
  }
  if (companyOverview) rows.push([], ["top_hiring"], ...companiesCsv(companyOverview));
  return rows.length > 0 ? rows : [["market-stats", "no data"]];
}
