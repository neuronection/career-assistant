import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import {
  CompaniesStatsRail,
  PostingsStatsRail,
} from "@/components/stats/StatsRail";
import * as statsApi from "@/api/stats";

vi.mock("@/api/stats", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/stats")>();
  return {
    ...actual,
    fetchPostingStatsSummary: vi.fn(),
    fetchPostingStatsSkills: vi.fn(),
    fetchPostingStatsBreakdown: vi.fn(),
    fetchCompanyStatsSummary: vi.fn(),
    fetchCompanyStatsOverview: vi.fn(),
  };
});

const mocked = vi.mocked(statsApi);

/** Mock shapes mirror the REAL wire models (backend/app/schemas/stats.py)
 * — the mock-reality gotcha applied to the stats endpoints. */
const SUMMARY = {
  as_of: "2026-10-31T12:00:00Z",
  status_basis: "open" as const,
  new_24h: { count: 4, prev: 3, delta_pct: 33.3, trend: "up" as const },
  new_7d: { count: 40, prev: 0, delta_pct: null, trend: "up" as const },
  new_30d: { count: 160, prev: 150, delta_pct: 6.7, trend: "up" as const },
  open_total: 520,
  sparkline: [
    { bucket: "2026-10-18", count: 2 },
    { bucket: "2026-10-19", count: 5 },
    { bucket: "2026-10-20", count: 3 },
  ],
  freshness: {
    as_of: "2026-10-31T12:00:00Z",
    stale_sources: [],
  },
};

function LocationProbe() {
  const location = useLocation();
  return (
    <div data-testid="probe">{location.pathname + location.search}</div>
  );
}

function postingsRail(onPostedWithin = vi.fn(), onSkill = vi.fn(), onSource = vi.fn()) {
  return render(
    <MemoryRouter initialEntries={["/postings"]}>
      <Routes>
        <Route
          path="/postings"
          element={
            <>
              <LocationProbe />
              <PostingsStatsRail
                onPostedWithin={onPostedWithin}
                onSkill={onSkill}
                onSource={onSource}
              />
            </>
          }
        />
        <Route path="/postings/stats" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>
  );
}

function companiesRail(onNew = vi.fn(), onIndustry = vi.fn(), onCompany = vi.fn()) {
  return render(
    <MemoryRouter initialEntries={["/companies"]}>
      <Routes>
        <Route
          path="/companies"
          element={
            <>
              <LocationProbe />
              <CompaniesStatsRail onNewCompanies={onNew} onIndustry={onIndustry} onCompany={onCompany} />
            </>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.fetchPostingStatsSummary.mockResolvedValue(SUMMARY);
  mocked.fetchPostingStatsSkills.mockResolvedValue({
    as_of: "2026-10-31T12:00:00Z",
    window: "30d",
    status_basis: "open",
    start: null,
    end: "2026-10-31T12:00:00Z",
    top: [],
    rising: [
      { key: "kubernetes", label: "Kubernetes", count: 22, share: 0.14, delta_pct: 100, trend: "up" },
    ],
    falling: [],
    categories: [],
    levels: [],
    avg_level: null,
    priority: {},
    avg_skills_per_posting: 5,
  });
  mocked.fetchPostingStatsBreakdown.mockResolvedValue({
    as_of: "2026-10-31T12:00:00Z",
    window: "30d",
    status_basis: "open",
    start: null,
    end: "2026-10-31T12:00:00Z",
    dimension: "source",
    total: 160,
    rows: [
      { key: "synth", count: 100, share: 0.63, prev: 88, delta_pct: 13.6, trend: "up" },
      { key: "rss", count: 50, share: 0.31, prev: 60, delta_pct: -16.7, trend: "down" },
    ],
  });
  mocked.fetchCompanyStatsSummary.mockResolvedValue({
    as_of: "2026-10-31T12:00:00Z",
    window: "30d",
    status_basis: "open",
    start: null,
    end: "2026-10-31T12:00:00Z",
    companies_hiring: 34,
    new_companies: { count: 6, prev: 9, delta_pct: -33.3, trend: "down" },
  });
  mocked.fetchCompanyStatsOverview.mockResolvedValue({
    as_of: "2026-10-31T12:00:00Z",
    window: "30d",
    status_basis: "open",
    start: null,
    end: "2026-10-31T12:00:00Z",
    top_hiring: [
      { key: "acme-cloud", name: "Acme Cloud", open_postings: 9, new_in_range: { count: 3, prev: 2, delta_pct: 50.0, trend: "up" } },
    ],
    industry_mix: [{ key: "technology", count: 60, share: 0.38 }],
    openings_histogram: [],
  });
});

describe("PostingsStatsRail", () => {
  it("applies the posted-window mapping through the host seam", async () => {
    const onPostedWithin = vi.fn();
    postingsRail(onPostedWithin);
    await waitFor(() =>
      expect(screen.getAllByTestId("rail-posted-24h").length).toBeGreaterThan(0)
    );
    await userEvent.click(screen.getByTestId("rail-posted-24h"));
    expect(onPostedWithin).toHaveBeenCalledWith("24h");
  });

  it("applies a rising skill through the host's include patch", async () => {
    const onSkill = vi.fn();
    postingsRail(vi.fn(), onSkill);
    await waitFor(() => expect(screen.getByTestId("rail-skill-kubernetes")).toBeTruthy());
    await userEvent.click(screen.getByTestId("rail-skill-kubernetes"));
    expect(onSkill).toHaveBeenCalledWith("kubernetes");
  });

  it("applies a source include through the host's tri-state patch", async () => {
    const onSource = vi.fn();
    postingsRail(vi.fn(), vi.fn(), onSource);
    await waitFor(() => expect(screen.getByTestId("rail-source-synth")).toBeTruthy());
    await userEvent.click(screen.getByTestId("rail-source-synth"));
    expect(onSource).toHaveBeenCalledWith("synth");
  });

  it("links to the full market stats page", async () => {
    postingsRail();
    await waitFor(() => expect(screen.getByTestId("rail-open-full")).toBeTruthy());
    await userEvent.click(screen.getByTestId("rail-open-full"));
    await waitFor(() => expect(screen.getByTestId("probe").textContent).toBe("/postings/stats"));
  });

  it("opens and closes the compact 'Market pulse' card", async () => {
    postingsRail();
    await waitFor(() => expect(screen.getByTestId("stats-rail")).toBeTruthy());
    const details = screen.getByTestId("stats-rail").querySelector("details");
    expect(details).toBeTruthy();
    expect(details).toHaveAttribute("open");
    await userEvent.click(screen.getByTestId("stats-rail-toggle"));
    expect(details).not.toHaveAttribute("open");
    await userEvent.click(screen.getByTestId("stats-rail-toggle"));
    expect(details).toHaveAttribute("open");
  });

  it("keeps a slow response from overwriting a refetch (requestId guard)", async () => {
    let resolveFirst: (value: unknown) => void = () => {};
    mocked.fetchPostingStatsSummary
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve;
          }) as never
      )
      .mockResolvedValue({ ...SUMMARY, open_total: 999 });
    render(
      <MemoryRouter>
        <PostingsStatsRail onPostedWithin={vi.fn()} onSkill={vi.fn()} onSource={vi.fn()} />
      </MemoryRouter>
    );
    // The mounts fetch (call one) and the refresh button fetches again
    // (call two) while call one is still pending.
    await waitFor(() => expect(screen.getByTestId("stats-rail-refresh")).toBeTruthy());
    await userEvent.click(screen.getByTestId("stats-rail-refresh"));
    await waitFor(() =>
      // The refetch (fast) already owns the value slot...
      expect(screen.getAllByTestId("stat-tile-value")[3].textContent).toBe("999")
    );
    resolveFirst({ ...SUMMARY, open_total: 1 });
    await new Promise((resolve) => setTimeout(resolve, 0));
    // ...and the stale first response is dropped when it finally lands.
    expect(screen.getAllByTestId("stat-tile-value")[3].textContent).toBe("999");
  });
});

describe("CompaniesStatsRail", () => {
  it("filters the host page to new companies via the status chip", async () => {
    const onNew = vi.fn();
    companiesRail(onNew);
    await waitFor(() => expect(screen.getByTestId("rail-new-companies")).toBeTruthy());
    await userEvent.click(screen.getByTestId("rail-new-companies"));
    expect(onNew).toHaveBeenCalledTimes(1);
  });

  it("navigates a hiring company card to its company page", async () => {
    const onCompany = vi.fn();
    companiesRail(vi.fn(), vi.fn(), onCompany);
    await waitFor(() => expect(screen.getByTestId("rail-company-acme-cloud")).toBeTruthy());
    await userEvent.click(screen.getByTestId("rail-company-acme-cloud"));
    expect(onCompany).toHaveBeenCalledWith("acme-cloud");
  });

  it("applies an industry facet include", async () => {
    const onIndustry = vi.fn();
    companiesRail(vi.fn(), onIndustry);
    await waitFor(() => expect(screen.getByTestId("rail-industry-technology")).toBeTruthy());
    await userEvent.click(screen.getByTestId("rail-industry-technology"));
    expect(onIndustry).toHaveBeenCalledWith("technology");
  });

  it("renders plain when the stats endpoints fail", async () => {
    mocked.fetchCompanyStatsSummary.mockRejectedValue(new Error("boom"));
    mocked.fetchCompanyStatsOverview.mockRejectedValue(new Error("boom"));
    companiesRail();
    await waitFor(() => expect(screen.getByTestId("stats-rail-note")).toBeTruthy());
  });
});
