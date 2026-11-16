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
    fetchSalaryBenchmarks: vi.fn(),
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
  mocked.fetchSalaryBenchmarks.mockResolvedValue({
    as_of: "2026-11-12T00:00:00Z",
    window: "30d",
    status_basis: "all",
    start: null,
    end: "2026-11-12T00:00:00Z",
    floor: 10,
    cells: [
      {
        scope: "job",
        job_code: "data-analyst",
        job_title: "Data Analyst",
        family_key: "data",
        family_title: "Data",
        country: "DE",
        seniority: "mid",
        currency: "EUR",
        period: "year",
        n: 12,
        thin_sample: false,
        p25: 45000,
        p50: 50000,
        p75: 55000,
      },
    ],
    truncated: 0,
    reference: null,
    reference_status: "unavailable",
    notes: ["Per currency only."],
    note_codes: ["currency_only"],
  });
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
  // This render/table path is the observed slow case under the full parallel suite.
  it(
    "the volume Data view is the volume export row-for-row",
    async () => {
      renderMarketIntelligence("/postings/stats?view=demand", "wide");
      const card = await screen.findByTestId("stats-card-volume", {}, { timeout: 5_000 });
      await openDataView(card);
      expect(readTableTexts(card)).toEqual(asTexts(volumeCsv(dashboardPayload().timeseries!)));
    },
    15_000,
  );

  it("the dimensions Data view is the breakdown export row-for-row", async () => {
    renderMarketIntelligence("/postings/stats?view=demand", "wide");
    const card = await screen.findByTestId("stats-card-dimensions", {}, { timeout: 5_000 });
    await openDataView(card);
    expect(readTableTexts(card)).toEqual(asTexts(breakdownCsv(dashboardPayload().breakdown!)));
  });

  it("the rhythm Data view is the condensed by-weekday/by-hour/peak twin", async () => {
    renderMarketIntelligence("/postings/stats?view=demand", "wide");
    const card = await screen.findByTestId("stats-card-rhythm", {}, { timeout: 5_000 });
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

  it("the pay tab shows benchmark cells with n and the floor note", async () => {
    renderMarketIntelligence("/postings/stats?view=pay", "wide");
    const table = await screen.findByTestId("salary-benchmarks", {}, { timeout: 5_000 });
    expect(await within(table).findByText("Data Analyst")).toBeInTheDocument();
    expect(within(table).getByText("12")).toBeInTheDocument();
    expect(within(table).getByText("€50,000")).toBeInTheDocument();
    expect(table).toHaveTextContent("Minimum sample: 10");
  });

  it("shows thin benchmarks and the truncated note", async () => {
    const base = await mocked.fetchSalaryBenchmarks({});
    mocked.fetchSalaryBenchmarks.mockResolvedValue({
      ...base,
      truncated: 2,
      note_codes: ["currency_only", "cells_truncated"],
      notes: ["Per currency only.", "2 further cells are not shown."],
      cells: [{ ...base.cells[0], thin_sample: true, p25: null, p50: null, p75: null }],
    });
    renderMarketIntelligence("/postings/stats?view=pay", "wide");
    const table = await screen.findByTestId("salary-benchmarks", {}, { timeout: 5_000 });
    expect(within(table).getAllByText("—")).toHaveLength(3);
    expect(table).toHaveTextContent(/further cells are not shown/i);
  });

  it("shows an empty benchmark state when no cell is thick enough", async () => {
    const base = await mocked.fetchSalaryBenchmarks({});
    mocked.fetchSalaryBenchmarks.mockResolvedValue({ ...base, cells: [] });
    renderMarketIntelligence("/postings/stats?view=pay", "wide");
    const card = await screen.findByTestId("salary-benchmarks", {}, { timeout: 5_000 });
    expect(card).toHaveTextContent("No thick enough benchmark cell yet");
  });

  it("shows a benchmark error state", async () => {
    mocked.fetchSalaryBenchmarks.mockRejectedValue(new Error("boom"));
    renderMarketIntelligence("/postings/stats?view=pay", "wide");
    const card = await screen.findByTestId("salary-benchmarks", {}, { timeout: 5_000 });
    expect(within(card).getByRole("alert")).toHaveTextContent("Could not load pay benchmarks");
  });

  it("the salary Data view is the salary export row-for-row", async () => {
    renderMarketIntelligence("/postings/stats?view=pay", "wide");
    const card = await screen.findByTestId("stats-card-salary", {}, { timeout: 5_000 });
    await openDataView(card);
    expect(readTableTexts(card)).toEqual(asTexts(salaryCsv(dashboardPayload().salary!)));
  });

  it("the companies Data view is the companies export row-for-row", async () => {
    renderMarketIntelligence("/postings/stats?view=companies", "wide");
    const card = await screen.findByTestId("stats-card-companies-top", {}, { timeout: 5_000 });
    await openDataView(card);
    expect(readTableTexts(card)).toEqual(
      asTexts(companiesCsv(dashboardPayload().companies_overview!)),
    );
  });

  it("the combined export carries every card's rows", async () => {
    const user = userEvent.setup();
    const payload = dashboardPayload();
    renderMarketIntelligence("/postings/stats", "wide");
    await screen.findByTestId("stats-card-pulse", {}, { timeout: 5_000 });
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
