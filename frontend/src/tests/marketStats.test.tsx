import userEvent from "@testing-library/user-event";
import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as statsApi from "@/api/stats";
import {
  mockPayloads,
  mockClockwork,
  renderMarketStatsPage,
  SUMMARY,
  type MockedStatsApi,
} from "@/tests/marketStatsFixtures";

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
    fetchPostingStatsClockwork: vi.fn(),
    fetchCompanyStatsSummary: vi.fn(),
    fetchCompanyStatsOverview: vi.fn(),
  };
});

const mocked = vi.mocked(statsApi);

beforeEach(() => {
  vi.clearAllMocks();
  mockPayloads(mocked as unknown as MockedStatsApi);
});

describe("MarketStats page", () => {
  it("renders the pulse, insights, skills and companies payload", async () => {
    renderMarketStatsPage("/postings/stats");
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
    renderMarketStatsPage("/postings/stats");
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
    renderMarketStatsPage("/postings/stats");
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
    renderMarketStatsPage("/postings/stats");
    await waitFor(() => expect(screen.getByTestId("stats-breakdown-row-synth")).toBeTruthy());
    await userEvent.click(screen.getByTestId("stats-breakdown-row-synth"));
    await waitFor(() =>
      expect(screen.getByTestId("location-probe").textContent).toBe("/postings?source=synth")
    );
  });

  it("links the new-companies tile to the companies page", async () => {
    renderMarketStatsPage("/postings/stats");
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
      renderMarketStatsPage("/postings/stats");
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

  it("renders the clock card on the real wire shape, with the ramp and the peak ringed", async () => {
    renderMarketStatsPage("/postings/stats");
    await waitFor(() => expect(screen.getByTestId("stats-card-rhythm")).toBeTruthy());
    const cells = screen.getAllByTestId("stats-rhythm-cell");
    expect(cells).toHaveLength(168);
    // Weekday/hour coordinates ride the cells; the hot cell reads the top ramp band.
    expect(cells.every((cell) => Number(cell.getAttribute("data-w")) >= 1)).toBe(true);
    const hot = cells.find((cell) => cell.getAttribute("data-w") === "3" && cell.getAttribute("data-h") === "9");
    expect(hot).toHaveAttribute("data-level", "5");
    // Zero cells stay muted (level 0) — a quarter of the matrix spot-checked.
    expect(cells.filter((cell) => cell.getAttribute("data-level") === "0").length).toBe(167);
    expect(screen.getByTestId("stats-rhythm-peak").textContent).toBe("Busiest: Wed 09:00 UTC");
    expect(screen.getByTestId("stats-rhythm-grid")).toHaveAttribute(
      "aria-label",
      "Posting counts by weekday and hour (UTC)"
    );
    // The condensable sr-only summary carries the by_weekday/by_hour twin.
    expect(
      screen
        .getByTestId("stats-card-rhythm")
        .querySelector(".sr-only")
        ?.textContent
        ?.startsWith("Busiest: Wed 09:00 UTC.")
    ).toBe(true);
  });

  it("hides the peak caption and renders the zero ramp when the clock is empty", async () => {
    mocked.fetchPostingStatsClockwork.mockResolvedValue(mockClockwork(false));
    renderMarketStatsPage("/postings/stats");
    await waitFor(() => expect(screen.getByTestId("stats-card-rhythm")).toBeTruthy());
    expect(screen.queryByTestId("stats-rhythm-peak")).toBeNull();
  });

  it("rides the view state: the clock fetcher shares window and basis with the card family", async () => {
    renderMarketStatsPage("/postings/stats");
    await waitFor(() => expect(mocked.fetchPostingStatsClockwork).toHaveBeenCalledWith({
      window: "30d",
      status_basis: "all",
    }));
    await userEvent.click(screen.getByTestId("market-stats-basis-open"));
    await waitFor(() =>
      expect(mocked.fetchPostingStatsClockwork).toHaveBeenCalledWith({
        window: "30d",
        status_basis: "open",
      })
    );
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
    renderMarketStatsPage("/postings/stats");
    await waitFor(() => expect(screen.getAllByText("No data in this window").length).toBeGreaterThan(0));
  });
});
