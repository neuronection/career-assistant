import userEvent from "@testing-library/user-event";
import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as statsApi from "@/api/stats";
import type { PostingStatsTimeseries } from "@/api/stats";
import {
  mockPayloads,
  mockClockwork,
  renderMarketStatsPage,
  SUMMARY,
  TIMESERIES,
  type MockedStatsApi,
} from "@/tests/marketStatsFixtures";
import { addIsoDays } from "@/features/postings/pages/marketStatsParams";

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

vi.mock("@/lib/clipboard", () => ({
  copyText: vi.fn().mockResolvedValue(true),
}));

import { copyText } from "@/lib/clipboard";

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

const clipboard = vi.mocked(copyText);

/** The real 400 shape over the B window (the DomainError mapping) — the
 * stub mirrors the API answering {"detail": ...} with status 400, never
 * a 422. */
function axios400(detail: string): unknown {
  const error = new Error("Request failed with status code 400");
  Object.assign(error, {
    isAxiosError: true,
    config: { url: "/postings/stats/timeseries" },
    response: { status: 400, data: { detail } },
  });
  return error;
}

const matchesIso = (value: unknown): boolean =>
  /^\d{4}-\d{2}-\d{2}T00:00:00$/.test(String(value));

describe("custom comparison + copy link (plan 171 H9/H10)", () => {
  it("defaults to the previous-window mode: one timeseries call, pressed control, no hint", async () => {
    renderMarketStatsPage("/postings/stats");
    await waitFor(() => expect(mocked.fetchPostingStatsTimeseries).toHaveBeenCalled());
    expect(screen.getByTestId("market-stats-compare-previous")).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByTestId("compare-hint")).toBeNull();
    expect(mocked.fetchPostingStatsTimeseries).toHaveBeenCalledTimes(1);
  });

  it("a custom pick seeds B to A's span and fetches it aligned by the resolved bucket", async () => {
    renderMarketStatsPage("/postings/stats");
    await waitFor(() => expect(screen.getByTestId("market-stats-kpis")).toBeTruthy());
    // The initial load (A), then the compare switch reload (A) + the B fetch.
    await userEvent.click(screen.getByTestId("market-stats-compare-custom"));
    await waitFor(() => expect(mocked.fetchPostingStatsTimeseries).toHaveBeenCalledTimes(3));
    expect(screen.getByTestId("market-stats-compare-custom")).toHaveAttribute("aria-pressed", "true");
    const args = mocked.fetchPostingStatsTimeseries.mock.calls[2]![0] as Record<string, unknown>;
    expect(args.bucket).toBe("day");
    expect(args.status_basis).toBe("all");
    expect(matchesIso(args.from)).toBe(true);
    expect(matchesIso(args.to)).toBe(true);
    // The seed mirrors the ghost: B = the equally-long span before A.
    const today = new Date().toISOString().slice(0, 10);
    const seed = addIsoDays(today, -59);
    expect(args.from).toBe(`${seed}T00:00:00`);
    expect(args.to).toBe(`${addIsoDays(seed, 30)}T00:00:00`);
    // The localized legend names the three series.
    expect(screen.getByTestId("stats-legend-compare").textContent).toBe("Comparison");
    expect(screen.queryByTestId("compare-hint")).toBeNull();
  });

  it("the URL compare pair rides the round trip: the B fetch mirrors it exactly", async () => {
    renderMarketStatsPage("/postings/stats?compare=custom&compare_from=2026-01-01&compare_to=2026-01-14");
    await waitFor(() => expect(mocked.fetchPostingStatsTimeseries).toHaveBeenCalledTimes(2));
    expect(mocked.fetchPostingStatsTimeseries.mock.calls[1]![0]).toEqual({      from: "2026-01-01T00:00:00",
      to: "2026-01-15T00:00:00",
      bucket: "day",
      status_basis: "all",
    });
    // Equal grids after the crop: no offset hint.
    expect(screen.queryByTestId("compare-hint")).toBeNull();
  });

  it("a too-long B span degrades to the localized hint on the real HTTP 400", async () => {
    mocked.fetchPostingStatsTimeseries
      .mockResolvedValueOnce(TIMESERIES)
      .mockRejectedValueOnce(axios400("range too long for bucket 'day' (max 400 points)"));
    renderMarketStatsPage(
      "/postings/stats?window=90d&compare=custom&compare_from=2019-01-01&compare_to=2026-01-01"
    );
    await waitFor(() => expect(screen.getByTestId("compare-hint")).toBeTruthy());
    const hint = screen.getByTestId("compare-hint");
    expect(hint.textContent).toMatch(/bucket bound/);
    // The status travels on the hint: the REAL 400, asserted.
    expect(hint.getAttribute("title")).toBe("400");
    // The page stays functional around the failed B fetch.
    expect(screen.getByTestId("stats-card-volume")).toBeTruthy();
  });

  it("pauses the overlay while a split is on: state preserved, no B fetch, hint chip", async () => {
    renderMarketStatsPage(
      "/postings/stats?compare=custom&compare_from=2026-01-01&compare_to=2026-01-14&split=source"
    );
    await waitFor(() => expect(mocked.fetchPostingStatsTimeseries).toHaveBeenCalled());
    expect(mocked.fetchPostingStatsTimeseries).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.getByTestId("compare-hint")).toBeTruthy());
    expect(screen.getByTestId("compare-hint").textContent).toMatch(/pauses/);
  });

  it("hints the offset when the B grid differs: the longer is cropped, the shorter padded", async () => {
    const longer: PostingStatsTimeseries = {
      ...TIMESERIES,
      points: [
        ...TIMESERIES.points,
        { bucket: "2026-10-23", count: 3, prev: 0, ingestion: 0, series: {} },
      ],
    };
    mocked.fetchPostingStatsTimeseries
      .mockResolvedValueOnce(TIMESERIES)
      .mockResolvedValueOnce(longer);
    renderMarketStatsPage("/postings/stats?compare=custom&compare_from=2026-01-01&compare_to=2026-01-14");
    await waitFor(() => expect(screen.getByTestId("compare-hint")).toBeTruthy());
    expect(screen.getByTestId("compare-hint").textContent).toContain("1");
  });

  it("copies origin+path+search through the family clipboard with a transient Copied state", async () => {
    renderMarketStatsPage("/postings/stats");
    await waitFor(() => expect(screen.getByTestId("market-stats")).toBeTruthy());
    await userEvent.click(screen.getByTestId("stats-copy-link"));
    await waitFor(() =>
      expect(clipboard).toHaveBeenCalledWith("http://localhost:3000/postings/stats")
    );
    const button = screen.getByTestId("stats-copy-link");
    await waitFor(() => expect(button.textContent).toContain("Link copied ✓"));
    // The transient state auto-resets; the aria-live region rides along.
    await waitFor(() =>
      expect(screen.getByTestId("stats-copy-link").textContent).not.toContain("Link copied ✓"),
      { timeout: 2500 },
    );
  });
});
