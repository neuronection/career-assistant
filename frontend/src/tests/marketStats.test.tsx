import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import * as statsApi from "@/api/stats";
import { MarketStats } from "@/features/postings/pages/MarketStats";
import type { PostingStatsSummary } from "@/api/stats";

vi.mock("recharts", async (importOriginal) => {
  const mod = await importOriginal<typeof import("recharts")>();
  return {
    ...mod,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div>{children}</div>
    ),
  };
});

vi.mock("@/api/stats", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/stats")>();
  return {
    ...actual,
    fetchPostingStatsSummary: vi.fn(),
    fetchPostingStatsOverview: vi.fn(),
    fetchPostingStatsTimeseries: vi.fn(),
    fetchPostingStatsSkills: vi.fn(),
    fetchPostingStatsBreakdown: vi.fn(),
    fetchPostingStatsSalary: vi.fn(),
    fetchCompanyStatsSummary: vi.fn(),
    fetchCompanyStatsOverview: vi.fn(),
  };
});

const mocked = vi.mocked(statsApi);

const SPARK = Array.from({ length: 14 }, (_, index) => ({
  bucket: `2026-10-${String(index + 10).padStart(2, "0")}`,
  count: index % 3,
}));

const SUMMARY: PostingStatsSummary = {
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

/** The shapes mirror the real pydantic wire models — the mock-reality
 * rule; a silent field miss here hides against the live endpoint. */
function mockPayloads() {
  mocked.fetchPostingStatsSummary.mockResolvedValue(SUMMARY);
  mocked.fetchPostingStatsOverview.mockResolvedValue({
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
  mocked.fetchPostingStatsTimeseries.mockResolvedValue({
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
  });
  mocked.fetchPostingStatsSkills.mockResolvedValue({
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
  mocked.fetchPostingStatsBreakdown.mockResolvedValue({
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
  mocked.fetchPostingStatsSalary.mockResolvedValue({
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
  mocked.fetchCompanyStatsSummary.mockResolvedValue({
    as_of: SUMMARY.as_of,
    window: "30d",
    status_basis: "all",
    start: null,
    end: SUMMARY.as_of,
    companies_hiring: 34,
    new_companies: { count: 6, prev: 9, delta_pct: -33.3, trend: "down" },
  });
  mocked.fetchCompanyStatsOverview.mockResolvedValue({
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
  return (
    <div data-testid="location-probe">
      {`${location.pathname}${location.search.replace("?", "?")}`}
    </div>
  );
}

function renderPage(initial = "/") {
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

beforeEach(() => {
  vi.clearAllMocks();
  mockPayloads();
});

describe("MarketStats page", () => {
  it("renders the pulse, insights, skills and companies payload", async () => {
    renderPage("/postings/stats");
    expect(screen.getByTestId("market-stats")).toBeTruthy();
    await waitFor(() => expect(mocked.fetchPostingStatsSkills).toHaveBeenCalled());
    await waitFor(() => expect(screen.getAllByTestId("stat-tile-action").length).toBeGreaterThan(0));
    // KPI pulse values surface verbatim.
    expect(screen.getAllByTestId("stat-tile-value").map((n) => n.textContent)).toEqual(
      expect.arrayContaining(["4", "40", "160", "520"])
    );
    // Insight cards render mapped text for the wire keys, subjects localized.
    await waitFor(() => expect(screen.getAllByTestId("stats-insight-card").length).toBe(2));
    expect(screen.getByTestId("market-stats-footer")).toBeTruthy();
    expect(screen.getByTestId("stats-freshness-stale")).toBeTruthy();
  });

  it("fetches the default window and basis, honing split only when set", async () => {
    renderPage("/postings/stats");
    await waitFor(() => expect(mocked.fetchPostingStatsTimeseries).toHaveBeenCalled());
    expect(mocked.fetchPostingStatsTimeseries).toHaveBeenCalledWith({
      window: "30d",
      status_basis: "all",
    });
    expect(mocked.fetchPostingStatsSkills).toHaveBeenCalledWith({
      window: "30d",
      status_basis: "all",
    });
  });

  it("switches the window through the URL", async () => {
    renderPage("/postings/stats");
    await waitFor(() => expect(screen.getByTestId("market-stats-kpis")).toBeTruthy());
    const tabs = screen.getAllByRole("tab");
    const tab = tabs.find((node) => node.textContent === "Last 7 days");
    expect(tab).toBeTruthy();
    await userEvent.click(tab!);
    await waitFor(() =>
      expect(mocked.fetchPostingStatsTimeseries).toHaveBeenCalledWith({
        window: "7d",
        status_basis: "all",
      })
    );
  });

  it("drills from a dimension row into the explore filter vocabulary", async () => {
    renderPage("/postings/stats");
    await waitFor(() => expect(screen.getByTestId("stats-breakdown-row-synth")).toBeTruthy());
    await userEvent.click(screen.getByTestId("stats-breakdown-row-synth"));
    await waitFor(() =>
      expect(screen.getByTestId("location-probe").textContent).toBe("/postings?source=synth")
    );
  });

  it("links the new-companies tile to the companies page", async () => {
    renderPage("/postings/stats");
    await waitFor(() => expect(screen.getByTestId("market-stats-companies")).toBeTruthy());
    const newTile = screen
      .getAllByTestId("stat-tile-action")
      .find((node) => node.textContent?.includes("New companies"));
    expect(newTile).toBeTruthy();
    await userEvent.click(newTile!);
    await waitFor(() =>
      expect(screen.getByTestId("location-probe").textContent).toBe("/companies?status=new")
    );
  });

  it("exports the per-card and combined CSV payloads through the blob funnel", async () => {
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:market-stats-test");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const clicks = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    try {
      renderPage("/postings/stats");
      await waitFor(() => expect(mocked.fetchPostingStatsTimeseries).toHaveBeenCalled());
      await waitFor(() =>
        expect(screen.getByTestId("stats-export-volume")).toBeTruthy(),
      );
      await userEvent.click(screen.getByTestId("stats-export-volume"));
      expect(createObjectURL).toHaveBeenCalledWith(
        expect.objectContaining({ type: "text/csv;charset=utf-8" })
      );
      const volumeAnchor = clicks.mock.instances[0] as unknown as HTMLAnchorElement;
      expect(volumeAnchor.download).toMatch(/^market-stats-volume-/);
      await userEvent.click(screen.getByTestId("stats-export"));
      expect(clicks).toHaveBeenCalledTimes(2);
    } finally {
      clicks.mockRestore();
      revokeObjectURL.mockRestore();
      createObjectURL.mockRestore();
    }
  });

  it("renders the empty state, never a crash, when everything returns nothing", async () => {
    mocked.fetchPostingStatsSkills.mockResolvedValue({
      ...{}, // every list empty
      as_of: SUMMARY.as_of,
      window: "30d",
      status_basis: "all",
      start: null,
      end: SUMMARY.as_of,
      top: [],
      rising: [],
      falling: [],
      categories: [],
      levels: [],
      avg_level: null,
      priority: {},
      avg_skills_per_posting: 0,
    } as never);
    renderPage("/postings/stats");
    await waitFor(() => expect(screen.getAllByText("No data in this window").length).toBeGreaterThan(0));
  });
});
