import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as statsApi from "@/api/stats";
import {
  allExportRows,
  breakdownCsv,
  companiesCsv,
  salaryCsv,
  volumeCsv,
} from "@/features/postings/pages/market-intelligence/exportRows";
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

vi.mock("@/components/stats/statsExport", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/stats/statsExport")>();
  return { ...actual, downloadStatsCsv: vi.fn() };
});

const mocked = vi.mocked(statsApi);
const statsExport = await import("@/components/stats/statsExport");

beforeEach(() => {
  vi.clearAllMocks();
  mocked.fetchPostingStatsDashboard.mockResolvedValue(dashboardPayload());
});

async function openDataView(card: HTMLElement): Promise<void> {
  await userEvent.click(within(card).getByTestId("stats-table-toggle-data"));
  await waitFor(() =>
    expect(within(card).getAllByRole("table").length).toBeGreaterThan(0),
  );
}

/** The H8 coherence claim: the Data view renders the same CsvRows the
 * card's export downloads — read the table cells as text and compare to
 * the builder output cell-for-cell. */
function readTableTexts(card: HTMLElement): string[][] {
  const table = within(card).getAllByRole("table")[0];
  return Array.from(table.querySelectorAll("tr")).map((row) =>
    Array.from(row.children).map((cell) => cell.textContent ?? ""),
  );
}

function asTexts(rows: (string | number | boolean | null | undefined)[][]): string[][] {
  return rows.map((row) => row.map((cell) => (cell == null ? "" : String(cell))));
}

describe("market intelligence Data views mirror their exports (plan 195)", () => {
  it("the volume Data view is the volume export row-for-row", async () => {
    renderMarketIntelligence("/postings/stats?view=demand", "wide");
    const card = await screen.findByTestId("stats-card-volume");
    await openDataView(card);
    expect(readTableTexts(card)).toEqual(asTexts(volumeCsv(dashboardPayload().timeseries!)));
  });

  it("the dimensions Data view is the breakdown export row-for-row", async () => {
    renderMarketIntelligence("/postings/stats?view=demand", "wide");
    const card = await screen.findByTestId("stats-card-dimensions");
    await openDataView(card);
    expect(readTableTexts(card)).toEqual(asTexts(breakdownCsv(dashboardPayload().breakdown!)));
  });

  it("the rhythm Data view is the condensed by-weekday/by-hour/peak twin", async () => {
    renderMarketIntelligence("/postings/stats?view=demand", "wide");
    const card = await screen.findByTestId("stats-card-rhythm");
    await openDataView(card);
    const texts = readTableTexts(card);
    const clock = dashboardPayload().clockwork!;
    const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const hours = Array.from({ length: 24 }, (_, hour) => `${String(hour).padStart(2, "0")}:00`);
    expect(texts).toEqual([
      ["when", "postings"],
      ...clock.by_weekday.map((count, index) => [weekdays[index], String(count)]),
      ...clock.by_hour.map((count, hour) => [hours[hour], String(count)]),
      ["Wed 09:00", "12"],
    ]);
  });

  it("the salary Data view is the salary export row-for-row", async () => {
    renderMarketIntelligence("/postings/stats?view=pay", "wide");
    const card = await screen.findByTestId("stats-card-salary");
    await openDataView(card);
    expect(readTableTexts(card)).toEqual(asTexts(salaryCsv(dashboardPayload().salary!)));
  });

  it("the companies Data view is the companies export row-for-row", async () => {
    renderMarketIntelligence("/postings/stats?view=companies", "wide");
    const card = await screen.findByTestId("stats-card-companies-top");
    await openDataView(card);
    expect(readTableTexts(card)).toEqual(
      asTexts(companiesCsv(dashboardPayload().companies_overview!)),
    );
  });

  it("the combined export carries every card's rows", async () => {
    const user = userEvent.setup();
    const payload = dashboardPayload();
    renderMarketIntelligence("/postings/stats", "wide");
    await screen.findByTestId("stats-card-pulse");
    await user.click(screen.getByTestId("stats-export"));
    expect(vi.mocked(statsExport.downloadStatsCsv)).toHaveBeenCalledWith(
      "30d",
      allExportRows({
        summary: payload.summary,
        series: payload.timeseries,
        skills: payload.skills,
        breakdown: payload.breakdown,
        salary: payload.salary,
        companySummary: payload.companies_summary,
        companyOverview: payload.companies_overview,
      }),
    );
  });
});
