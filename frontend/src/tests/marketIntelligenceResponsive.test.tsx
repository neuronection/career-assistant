import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as statsApi from "@/api/stats";
import { dashboardPayload, renderMarketIntelligence } from "@/tests/marketIntelligenceFixtures";

// Page-level renders mount the lazy tab chunks; the coverage run's CPU
// contention can exceed the 5 s default (plan 195 F6).
vi.setConfig({ testTimeout: 20_000 });

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
  return { ...actual, fetchPostingStatsDashboard: vi.fn(), fetchPostingStatsTimeseries: vi.fn() };
});

const mocked = vi.mocked(statsApi);

beforeEach(() => {
  vi.clearAllMocks();
  mocked.fetchPostingStatsDashboard.mockResolvedValue(dashboardPayload());
});

async function loaded() {
  await screen.findByTestId("stats-card-pulse");
}

describe("market intelligence responsive contract (plan 195 §3.6)", () => {
  it("compact opens the filters in a modal with the active count", async () => {
    const user = userEvent.setup();
    renderMarketIntelligence("/postings/stats?seniority=senior", "compact");
    await loaded();

    expect(screen.getByTestId("market-stats").getAttribute("data-band")).toBe("compact");
    const button = screen.getByTestId("market-stats-filters-button");
    expect(button.textContent).toContain("1");
    await user.click(button);

    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByTestId("market-stats-filter-fields")).toBeTruthy();
    await user.click(screen.getByTestId("market-stats-sheet-apply"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("wide renders the fields inline and no sheet trigger", async () => {
    renderMarketIntelligence("/postings/stats", "wide");
    await loaded();
    expect(screen.getByTestId("market-stats-filter-fields")).toBeTruthy();
    expect(screen.queryByTestId("market-stats-filters-button")).toBeNull();
  });

  it("compact renders a data table as cards with a view-all expansion", async () => {
    const user = userEvent.setup();
    renderMarketIntelligence("/postings/stats", "compact");
    await loaded();
    await user.click(screen.getByTestId("market-stats-tab-demand"));
    const volume = await screen.findByTestId("stats-card-volume");
    await user.click(within(volume).getByTestId("stats-table-toggle-data"));

    expect(within(volume).getAllByTestId("stats-table-card").length).toBeGreaterThan(0);
    expect(within(volume).queryByRole("table")).toBeNull();
  });

  it("medium keeps the heatmap scrollable with the sticky weekday column", async () => {
    const user = userEvent.setup();
    renderMarketIntelligence("/postings/stats", "medium");
    await loaded();
    await user.click(screen.getByTestId("market-stats-tab-demand"));
    expect(await screen.findByTestId("stats-rhythm-grid")).toBeTruthy();
  });

  it("moves between tabs with the arrow keys", async () => {
    const user = userEvent.setup();
    renderMarketIntelligence("/postings/stats", "wide");
    await loaded();
    const overview = screen.getByTestId("market-stats-tab-overview");
    overview.focus();
    await user.keyboard("{ArrowRight}");
    await waitFor(() =>
      expect(screen.getByTestId("market-stats-tab-demand").getAttribute("aria-selected")).toBe(
        "true",
      ),
    );
  });
});
