import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18next from "i18next";

import * as statsApi from "@/api/stats";
import { downloadStatsCsv } from "@/components/stats/statsExport";
import { copyText } from "@/lib/clipboard";
import { expectNoA11yViolations } from "@/tests/a11y";
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
  return {
    ...actual,
    fetchPostingStatsDashboard: vi.fn(),
    fetchPostingStatsTimeseries: vi.fn(),
  };
});

vi.mock("@/lib/clipboard", () => ({ copyText: vi.fn().mockResolvedValue(true) }));

vi.mock("@/components/stats/statsExport", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/stats/statsExport")>();
  return { ...actual, downloadStatsCsv: vi.fn() };
});

const mocked = vi.mocked(statsApi);

function lastCall() {
  const calls = mocked.fetchPostingStatsDashboard.mock.calls;
  return calls[calls.length - 1] ?? [];
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.fetchPostingStatsDashboard.mockResolvedValue(dashboardPayload());
});

async function loaded() {
  await waitFor(() => expect(mocked.fetchPostingStatsDashboard).toHaveBeenCalled());
  await screen.findByTestId("stats-card-pulse");
}

function compareCalls() {
  return mocked.fetchPostingStatsDashboard.mock.calls.filter(
    ([params]) => params.cards === "timeseries",
  );
}

describe("market intelligence shell (plan 195)", () => {
  it("renders the overview tab from one composite request with one as-of", async () => {
    renderMarketIntelligence();
    expect(screen.getByTestId("market-stats")).toBeTruthy();
    await loaded();

    expect(mocked.fetchPostingStatsDashboard).toHaveBeenCalledTimes(1);
    const [params] = mocked.fetchPostingStatsDashboard.mock.calls[0];
    expect(params).toMatchObject({ window: "30d", basis: "all" });
    expect(String(params.cards)).toContain("summary");
    expect(String(params.cards)).toContain("clockwork");

    expect(screen.getByTestId("market-stats-asof").textContent).toContain("2026");
    expect(screen.getAllByTestId("stat-tile-value").map((node) => node.textContent)).toEqual(
      expect.arrayContaining(["4", "40", "160", "520"]),
    );
    expect(screen.getAllByTestId("stats-insight-card")).toHaveLength(2);
    expect(screen.getByTestId("stats-freshness-stale")).toBeTruthy();
  });

  it("switches tabs without a second request and keeps the URL in sync", async () => {
    const user = userEvent.setup();
    renderMarketIntelligence();
    await loaded();
    await user.click(screen.getByTestId("market-stats-tab-demand"));

    expect(await screen.findByTestId("market-stats-tabpanel-demand")).toBeTruthy();
    expect(await screen.findByTestId("stats-card-volume")).toBeTruthy();
    expect(screen.getByTestId("stats-card-rhythm")).toBeTruthy();
    expect(screen.getByTestId("stats-card-dimensions")).toBeTruthy();
    expect(mocked.fetchPostingStatsDashboard).toHaveBeenCalledTimes(1);
    expect(
      screen.getByTestId("market-stats-tab-demand").getAttribute("aria-selected"),
    ).toBe("true");
  });

  it("round-trips a segment filter into the request, the URL and a chip", async () => {
    const user = userEvent.setup();
    renderMarketIntelligence("/postings/stats", "wide");
    await loaded();

    await user.type(screen.getByTestId("market-stats-filter-q"), "data");
    const [params] = lastCall();
    expect(params).toMatchObject({ q: "data" });
    expect(screen.getByTestId("market-stats-chip-q").textContent).toContain("data");
    expect(screen.getByTestId("market-stats-chip-remove-q")).toBeTruthy();

    await user.click(screen.getByTestId("market-stats-chip-remove-q"));
    const [cleared] = lastCall();
    expect(cleared).not.toHaveProperty("q");
  });

  it("keeps a failed card isolated and offers a retry", async () => {
    mocked.fetchPostingStatsDashboard.mockResolvedValue({
      ...dashboardPayload(),
      salary: null,
      errors: { salary: { code: "timeout", message: "too slow" } },
    });
    const user = userEvent.setup();
    renderMarketIntelligence();
    await loaded();
    await user.click(screen.getByTestId("market-stats-tab-pay"));

    expect(await screen.findByTestId("stats-card-error")).toBeTruthy();
    expect(screen.getByTestId("stats-card-error").textContent).toContain("took too long");
    expect(screen.getByTestId("stats-card-retry")).toBeTruthy();
  });

  it("renders the empty state when every card is null", async () => {
    mocked.fetchPostingStatsDashboard.mockResolvedValue({
      ...dashboardPayload(),
      summary: null,
      overview: null,
      timeseries: null,
      breakdown: null,
      skills: null,
      salary: null,
      companies_summary: null,
      companies_overview: null,
      clockwork: null,
      errors: {},
    });
    renderMarketIntelligence();
    await loaded();
    expect(screen.getAllByText(/no data/i).length).toBeGreaterThan(0);
  });

  it("aborts the previous request when the view changes", async () => {
    const pending: { resolve: ((value: statsApi.MarketDashboard) => void) | null } = {
      resolve: null,
    };
    mocked.fetchPostingStatsDashboard.mockImplementationOnce(
      () => new Promise((resolve) => {
        pending.resolve = resolve;
      }),
    );
    const user = userEvent.setup();
    renderMarketIntelligence("/postings/stats", "wide");
    await waitFor(() => expect(mocked.fetchPostingStatsDashboard).toHaveBeenCalledTimes(1));
    const firstSignal = mocked.fetchPostingStatsDashboard.mock.calls[0][1];
    expect(firstSignal?.aborted).toBe(false);

    await user.type(screen.getByTestId("market-stats-filter-q"), "x");
    await waitFor(() => expect(mocked.fetchPostingStatsDashboard.mock.calls.length).toBeGreaterThan(1));
    expect(firstSignal?.aborted).toBe(true);
    pending.resolve?.(dashboardPayload());
    await loaded();
  });

  it("fetches the custom B series exactly once for a stable range", async () => {
    renderMarketIntelligence(
      "/postings/stats?view=demand&compare=custom&compare_from=2026-09-01&compare_to=2026-09-30",
      "wide",
    );
    await screen.findByTestId("stats-card-volume");
    await waitFor(() => expect(compareCalls()).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(compareCalls()).toHaveLength(1);
  });

  it("applies the active segments to the custom B series", async () => {
    renderMarketIntelligence(
      "/postings/stats?view=demand&compare=custom&compare_from=2026-09-01&compare_to=2026-09-30" +
        "&source=synth&seniority=senior",
      "wide",
    );
    await screen.findByTestId("stats-card-volume");
    await waitFor(() => expect(compareCalls()).toHaveLength(1));
    const [params] = compareCalls()[0];
    expect(params).toMatchObject({
      cards: "timeseries",
      basis: "all",
      source: ["synth"],
      seniority: ["senior"],
      from: "2026-09-01T00:00:00",
      to: "2026-10-01T00:00:00",
    });
  });

  it("copies the view link and exports the combined CSV", async () => {
    const user = userEvent.setup();
    renderMarketIntelligence();
    await loaded();
    await user.click(screen.getByTestId("stats-copy-link"));
    expect(copyText).toHaveBeenCalled();
    await user.click(screen.getByTestId("stats-export"));
    expect(downloadStatsCsv).toHaveBeenCalledWith("30d", expect.any(Array));
  });

  it("drills a dimension row to the list with window, basis and the value", async () => {
    const user = userEvent.setup();
    renderMarketIntelligence();
    await loaded();
    await user.click(screen.getByTestId("market-stats-tab-demand"));
    await user.click(await screen.findByTestId("stats-breakdown-row-synth"));

    const probe = await screen.findByTestId("probe");
    expect(probe.textContent).toContain("/postings?");
    expect(probe.textContent).toContain("posted_within=30d");
    expect(probe.textContent).toContain("basis=all");
    expect(probe.textContent).toContain("source=synth");
  });

  it("drills the open-postings tile to the all-time open list", async () => {
    const user = userEvent.setup();
    renderMarketIntelligence("/postings/stats", "wide");
    await loaded();
    const tile = screen
      .getAllByTestId("stat-tile-action")
      .find((node) => node.textContent?.includes("Open postings"));
    expect(tile).toBeTruthy();
    await user.click(tile!);

    const probe = await screen.findByTestId("probe");
    expect(probe.textContent).toBe("/postings");
  });

  it("formats numbers in the active locale", async () => {
    try {
      await i18next.changeLanguage("de");
      renderMarketIntelligence();
      await loaded();
      const values = screen.getAllByTestId("stat-tile-value").map((node) => node.textContent);
      expect(values).toContain("1.234");
    } finally {
      await i18next.changeLanguage("en");
    }
  });

  it("has no axe violations on the overview tab", async () => {
    const { container } = renderMarketIntelligence();
    await loaded();
    await expectNoA11yViolations(container);
  });

  it("has no axe violations on the demand tab", async () => {
    const user = userEvent.setup();
    const { container } = renderMarketIntelligence();
    await loaded();
    await user.click(screen.getByTestId("market-stats-tab-demand"));
    await screen.findByTestId("stats-card-volume");
    await expectNoA11yViolations(container);
  });

  it("has no axe violations on the volume Data view", async () => {
    const user = userEvent.setup();
    const { container } = renderMarketIntelligence();
    await loaded();
    await user.click(screen.getByTestId("market-stats-tab-demand"));
    const volume = await screen.findByTestId("stats-card-volume");
    await user.click(within(volume).getByTestId("stats-table-toggle-data"));
    await expectNoA11yViolations(container);
  });
});

describe("market intelligence chart accessibility (plan 195 slice 4)", () => {
  it("labels the volume chart and the clock grid as images with the table as the data twin", async () => {
    const user = userEvent.setup();
    renderMarketIntelligence();
    await loaded();
    await user.click(screen.getByTestId("market-stats-tab-demand"));

    const volume = await screen.findByTestId("stats-card-volume");
    const frame = within(volume).getByTestId("stats-chart-frame");
    expect(frame.getAttribute("role")).toBe("img");
    expect(frame.getAttribute("aria-label")).toBeTruthy();
    expect(within(volume).getByTestId("stats-table-toggle-data")).toBeTruthy();

    const grid = screen.getByTestId("stats-rhythm-grid");
    expect(grid.getAttribute("role")).toBe("img");
    expect(grid.getAttribute("aria-label")).toBeTruthy();
  });
});
