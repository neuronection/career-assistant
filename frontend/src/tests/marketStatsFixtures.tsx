import { render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import { MarketStats } from "@/features/postings/pages/MarketStats";
import {
  type PostingStatsClockwork,
  type PostingStatsSummary,
} from "@/api/stats";

export const SPARK = Array.from({ length: 14 }, (_, index) => ({
  bucket: `2026-10-${String(index + 10).padStart(2, "0")}`,
  count: index % 3,
}));

export const SUMMARY: PostingStatsSummary = {
  as_of: "2026-10-31T12:00:00Z",
  status_basis: "open",
  new_24h: { count: 4, prev: 3, delta_pct: 33.3, trend: "up" },
  new_7d: { count: 40, prev: 44, delta_pct: -9.1, trend: "down" },
  new_30d: { count: 160, prev: 0, delta_pct: null, trend: "up" },
  open_total: 520,
  sparkline: SPARK,
  freshness: {
    as_of: "2026-10-31T12:00:00Z",
    stale_sources: [{ source_key: "synth", status: "stale", last_success: "2026-10-29T00:00:00Z" }],
  },
};

/** A complete zero-filled 7×24 matrix — the real ClockworkOut contract
 * (mock-reality rule); `hot` fills one cell and its aggregates. */
export function mockClockwork(hot = true): PostingStatsClockwork {
  const cells = Array.from({ length: 168 }, (_, index) => ({
    weekday: Math.floor(index / 24) + 1,
    hour: index % 24,
    count: hot && index === (3 - 1) * 24 + 9 ? 12 : 0,
    prev: hot && index === (3 - 1) * 24 + 9 ? 4 : 0,
    delta_pct: hot && index === (3 - 1) * 24 + 9 ? 200.0 : null,
  }));
  const weekdayTotals = Array.from({ length: 7 }, () => 0);
  const hourTotals = Array.from({ length: 24 }, () => 0);
  if (hot) {
    weekdayTotals[2] = 12;
    hourTotals[9] = 12;
  }
  return {
    as_of: SUMMARY.as_of,
    window: "30d",
    status_basis: "all",
    start: "2026-10-01T00:00:00Z",
    end: SUMMARY.as_of,
    time_zone: "UTC",
    cells,
    peak: hot ? { weekday: 3, hour: 9, count: 12 } : null,
    by_weekday: weekdayTotals,
    by_hour: hourTotals,
  };
}

export const TIMESERIES = {
  as_of: SUMMARY.as_of,
  window: "30d",
  status_basis: "all",
  start: null,
  end: SUMMARY.as_of,
  bucket: "day",
  split: null,
  points: [
    { bucket: "2026-10-20", count: 8, prev: 5, ingestion: 9, series: {} },
    { bucket: "2026-10-21", count: 0, prev: 4, ingestion: 0, series: {} },
    { bucket: "2026-10-22", count: 11, prev: 6, ingestion: 11, series: {} },
  ],
} as const;

/** The shapes mirror the real pydantic wire models — the mock-reality
 * rule; a silent field miss here hides against the live endpoint. */
type MockFn = { mockResolvedValue: (value: unknown) => void };

export type MockedStatsApi = Partial<Record<string, MockFn>>;

export function mockPayloads(api: MockedStatsApi) {
  const asMock = (name: string): MockFn => api[name] as MockFn;
  asMock("fetchPostingStatsSummary").mockResolvedValue(SUMMARY);
  asMock("fetchPostingStatsClockwork").mockResolvedValue(mockClockwork());
  asMock("fetchPostingStatsOverview").mockResolvedValue({
    as_of: SUMMARY.as_of,
    window: "30d",
    status_basis: "all",
    start: null,
    end: SUMMARY.as_of,
    new_in_range: { count: 160, prev: 140, delta_pct: 14.3, trend: "up" },
    open_total: 520,
    status_mix: { mapped: 120, created: 40 },
    coverage: { salary: 0.55, location: 0.8, org_linked: 0.4, skill_tagged: 0.95 },
    insights: [
      {
        kind: "volume",
        subject: "postings",
        delta_pct: 42.9,
        baseline: 35,
        text_key: "insights.volume_high",
      },
      {
        kind: "skill_lead",
        subject: "python",
        delta_pct: 18.2,
        baseline: 7.5,
        text_key: "insights.skill_lead",
      },
    ],
  });
  asMock("fetchPostingStatsTimeseries").mockResolvedValue(TIMESERIES);
  asMock("fetchPostingStatsSkills").mockResolvedValue({
    as_of: SUMMARY.as_of,
    window: "30d",
    status_basis: "all",
    start: null,
    end: SUMMARY.as_of,
    top: [
      { key: "python", label: "Python", count: 90, share: 0.56, delta_pct: 12.5, trend: "up" },
      { key: "sql", label: "SQL", count: 70, share: 0.44, delta_pct: -3.2, trend: "down" },
    ],
    rising: [
      { key: "kubernetes", label: "Kubernetes", count: 22, share: 0.14, delta_pct: 100, trend: "up" },
    ],
    falling: [
      { key: "excel", label: "Excel", count: 11, share: 0.07, delta_pct: -35, trend: "down" },
    ],
    categories: [{ key: "data", count: 120, share: 0.75 }],
    levels: [
      { level: 2, count: 30 },
      { level: 4, count: 80 },
    ],
    avg_level: 3.4,
    priority: { must_have: 90, nice_to_have: 60, bonus: 10 },
    avg_skills_per_posting: 6.5,
  });
  asMock("fetchPostingStatsBreakdown").mockResolvedValue({
    as_of: SUMMARY.as_of,
    window: "30d",
    status_basis: "all",
    start: null,
    end: SUMMARY.as_of,
    dimension: "source",
    total: 160,
    rows: [
      { key: "synth", count: 100, share: 0.63, prev: 88, delta_pct: 13.6, trend: "up" },
      { key: "rss", count: 50, share: 0.31, prev: 60, delta_pct: -16.7, trend: "down" },
    ],
  });
  asMock("fetchPostingStatsSalary").mockResolvedValue({
    as_of: SUMMARY.as_of,
    window: "30d",
    status_basis: "all",
    start: null,
    end: SUMMARY.as_of,
    primary_currency: "EUR",
    currencies: [
      {
        currency: "EUR",
        disclosed: 88,
        coverage: 0.55,
        thin_sample: false,
        p25: 30000,
        p50: 42000,
        p75: 58000,
        histogram: [
          { floor: 20000, ceiling: 30000, count: 12 },
          { floor: 30000, ceiling: 40000, count: 30 },
          { floor: 40000, ceiling: 50000, count: 24 },
        ],
        by_seniority: [{ seniority: "mid", count: 40, median: 44000 }],
        period_basis: { year: 70, month: 18 },
      },
    ],
  });
  asMock("fetchCompanyStatsSummary").mockResolvedValue({
    as_of: SUMMARY.as_of,
    window: "30d",
    status_basis: "all",
    start: null,
    end: SUMMARY.as_of,
    companies_hiring: 34,
    new_companies: { count: 6, prev: 9, delta_pct: -33.3, trend: "down" },
  });
  asMock("fetchCompanyStatsOverview").mockResolvedValue({
    as_of: SUMMARY.as_of,
    window: "30d",
    status_basis: "all",
    start: null,
    end: SUMMARY.as_of,
    top_hiring: [
      { key: "acme-cloud", name: "Acme Cloud", open_postings: 9, new_in_range: { count: 3, prev: 2, delta_pct: 50.0, trend: "up" } },
      { key: "globex", name: "Globex", open_postings: 5, new_in_range: { count: 1, prev: 1, delta_pct: 0.0, trend: "flat" } },
    ],
    industry_mix: [{ key: "technology", count: 60, share: 0.38 }],
    openings_histogram: [
      { bucket: "1", count: 12 },
      { bucket: "2-5", count: 18 },
    ],
  });
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname + location.search}</div>;
}

export async function awaitMarketStatsLoaded() {
  await waitFor(() =>
    expect(document.querySelector(`[data-testid='stats-card-rhythm']`)).toBeTruthy(),
  );
}

export function renderMarketStatsPage(initial = "/") {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="/" element={<MarketStats />} />
        <Route path="/postings" element={<LocationProbe />} />
        <Route path="/postings/stats" element={<MarketStats />} />
        <Route path="/companies" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>
  );
}
