import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import { MarketIntelligence } from "@/features/postings/pages/market-intelligence";
import type { ContainerBand } from "@/hooks/useContainerBand";
import type {
  MarketDashboard,
  PostingStatsClockwork,
  PostingStatsTimeseries,
} from "@/api/stats";

export const AS_OF = "2026-10-31T12:00:00Z";

export const SPARK = Array.from({ length: 14 }, (_, index) => ({
  bucket: `2026-10-${String(index + 18).padStart(2, "0")}`,
  count: index % 3,
}));

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
    as_of: AS_OF,
    window: "30d",
    status_basis: "all",
    start: "2026-10-01T00:00:00Z",
    end: AS_OF,
    time_zone: "UTC",
    cells,
    peak: hot ? { weekday: 3, hour: 9, count: 12 } : null,
    by_weekday: weekdayTotals,
    by_hour: hourTotals,
  };
}

export const TIMESERIES: PostingStatsTimeseries = {
  as_of: AS_OF,
  window: "30d",
  status_basis: "all",
  start: "2026-10-01T00:00:00Z",
  end: AS_OF,
  bucket: "day",
  split: null,
  points: [
    { bucket: "2026-10-27", count: 2, prev: 1, ingestion: 2, series: {} },
    { bucket: "2026-10-28", count: 5, prev: 4, ingestion: 5, series: {} },
    { bucket: "2026-10-29", count: 3, prev: 2, ingestion: 3, series: {} },
    { bucket: "2026-10-30", count: 6, prev: 5, ingestion: 6, series: {} },
  ],
};

export function dashboardPayload(): MarketDashboard {
  return {
    as_of: AS_OF,
    window: "30d",
    basis: "all",
    bucket: "day",
    applied_filters: {},
    summary: {
      as_of: AS_OF,
      status_basis: "open",
      new_24h: { count: 4, prev: 3, delta_pct: 33.3, trend: "up" },
      new_7d: { count: 40, prev: 44, delta_pct: -9.1, trend: "down" },
      new_30d: { count: 160, prev: 0, delta_pct: null, trend: "up" },
      open_total: 520,
      sparkline: SPARK,
      freshness: {
        as_of: AS_OF,
        stale_sources: [
          { source_key: "synth", status: "stale", last_success: "2026-10-29T00:00:00Z" },
        ],
      },
    },
    overview: {
      as_of: AS_OF,
      window: "30d",
      status_basis: "all",
      start: "2026-10-01T00:00:00Z",
      end: AS_OF,
      new_in_range: { count: 1234, prev: 1000, delta_pct: 23.4, trend: "up" },
      open_total: 520,
      status_mix: { mapped: 400, expired: 120 },
      coverage: { salary: 0.42, location: 0.88, org_linked: 0.67, skill_tagged: 0.91 },
      insights: [
        {
          kind: "volume",
          subject: "postings",
          delta_pct: 200.0,
          baseline: 5.0,
          text_key: "insights.volume_high",
        },
        {
          kind: "share",
          subject: "remote",
          delta_pct: 30.0,
          baseline: 0.2,
          text_key: "insights.share_high",
        },
      ],
    },
    timeseries: TIMESERIES,
    breakdown: {
      as_of: AS_OF,
      window: "30d",
      status_basis: "all",
      start: "2026-10-01T00:00:00Z",
      end: AS_OF,
      dimension: "source",
      total: 16,
      rows: [
        { key: "synth", count: 12, share: 0.75, prev: 10, delta_pct: 20.0, trend: "up" },
        { key: "rss", count: 4, share: 0.25, prev: 4, delta_pct: 0.0, trend: "flat" },
      ],
    },
    skills: {
      as_of: AS_OF,
      window: "30d",
      status_basis: "all",
      start: "2026-10-01T00:00:00Z",
      end: AS_OF,
      top: [
        { key: "python", label: "Python", count: 120, share: 0.5, delta_pct: 10.0, trend: "up" },
        { key: "sql", label: "SQL", count: 90, share: 0.375, delta_pct: -5.0, trend: "down" },
      ],
      rising: [
        { key: "python", label: "Python", count: 120, share: 0.5, delta_pct: 10.0, trend: "up" },
      ],
      falling: [
        { key: "sql", label: "SQL", count: 90, share: 0.375, delta_pct: -5.0, trend: "down" },
      ],
      categories: [
        { key: "programming", count: 120, share: 0.5 },
        { key: "data", count: 90, share: 0.375 },
      ],
      levels: Array.from({ length: 10 }, (_, index) => ({
        level: index + 1,
        count: index === 2 ? 30 : 0,
      })),
      avg_level: 3.0,
      priority: { must_have: 30, nice_to_have: 60, bonus: 30, unspecified: 0 },
      avg_skills_per_posting: 2.1,
    },
    salary: {
      as_of: AS_OF,
      window: "30d",
      status_basis: "all",
      start: "2026-10-01T00:00:00Z",
      end: AS_OF,
      primary_currency: "EUR",
      currencies: [
        {
          currency: "EUR",
          disclosed: 12,
          coverage: 0.4,
          thin_sample: false,
          p25: 40_000,
          p50: 55_000,
          p75: 70_000,
          histogram: [
            { floor: 30_000, ceiling: 45_000, count: 4 },
            { floor: 45_000, ceiling: 60_000, count: 6 },
            { floor: 60_000, ceiling: 75_000, count: 2 },
          ],
          by_seniority: [
            { seniority: "senior", count: 6, median: 70_000 },
            { seniority: "mid", count: 6, median: 50_000 },
          ],
          period_basis: { year: 12 },
        },
      ],
    },
    companies_summary: {
      as_of: AS_OF,
      window: "30d",
      status_basis: "all",
      start: "2026-10-01T00:00:00Z",
      end: AS_OF,
      companies_hiring: 12,
      new_companies: { count: 3, prev: 1, delta_pct: 200.0, trend: "up" },
    },
    companies_overview: {
      as_of: AS_OF,
      window: "30d",
      status_basis: "all",
      start: "2026-10-01T00:00:00Z",
      end: AS_OF,
      top_hiring: [
        { key: "acme", name: "Acme", open_postings: 8, new_in_range: { count: 2, prev: 1, delta_pct: 100.0, trend: "up" } },
        { key: "beta", name: "Beta", open_postings: 5, new_in_range: { count: 1, prev: 1, delta_pct: 0.0, trend: "flat" } },
      ],
      industry_mix: [
        { key: "technology", count: 10, share: 0.8 },
        { key: "finance", count: 2, share: 0.2 },
      ],
      openings_histogram: [
        { bucket: "1", count: 8 },
        { bucket: "2-5", count: 3 },
        { bucket: "6-20", count: 1 },
        { bucket: "20+", count: 0 },
      ],
    },
    clockwork: mockClockwork(),
    errors: {},
  };
}

export function LocationProbe() {
  const location = useLocation();
  return <div data-testid="probe">{location.pathname + location.search}</div>;
}

export function renderMarketIntelligence(
  initial = "/postings/stats",
  band?: ContainerBand,
) {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route
          path="/postings/stats"
          element={<MarketIntelligence band={band} />}
        />
        <Route path="/postings" element={<LocationProbe />} />
        <Route path="/companies" element={<LocationProbe />} />
        <Route path="/companies/*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>
  );
}
