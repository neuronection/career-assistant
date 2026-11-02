import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as statsApi from "@/api/stats";
import { expectNoA11yViolations } from "@/tests/a11y";
import { mockPayloads, renderMarketStatsPage, type MockedStatsApi } from "@/tests/marketStatsFixtures";

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

vi.mock("@/components/stats/statsExport", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/stats/statsExport")>();
  return { ...actual, downloadStatsCsv: vi.fn() };
});

const mocked = vi.mocked(statsApi);
const statsExport = await import("@/components/stats/statsExport");

beforeEach(() => {
  vi.clearAllMocks();
  mockPayloads(mocked as unknown as MockedStatsApi);
});

function cardOf(testId: string): HTMLElement {
  const card = screen.getByTestId(`stats-card-${testId}`);
  expect(card).toBeTruthy();
  return card;
}

function toggleIn(card: HTMLElement): HTMLElement {
  return within(card).getByTestId("stats-table-toggle");
}

async function openDataView(card: HTMLElement) {
  const toggle = toggleIn(card);
  await userEvent.click(within(toggle).getByTestId("stats-table-toggle-data"));
  return toggle;
}

/** The H8 coherence claim: the Data view renders the same CsvRows the
 * card's export downloads — read the table cells as text and compare to
 * the intercepted builder output cell-for-cell. */
function readTableTexts(card: HTMLElement): string[][] {
  const table = within(card).getAllByRole("table")[0];
  return Array.from(table.querySelectorAll("tr")).map((row) =>
    Array.from(row.children).map((cell) => cell.textContent ?? ""),
  );
}

describe("market-stats chart ⇄ data table views", () => {
  it("every data card opens the Data view with a pressed segmented toggle, defaulting to Chart", async () => {
    renderMarketStatsPage("/postings/stats");
    await waitFor(() => expect(screen.getByTestId("stats-card-rhythm")).toBeTruthy());
    const cards = ["volume", "dimensions", "salary", "companies-top", "rhythm"].map(cardOf);
    for (const card of cards) {
      const toggle = toggleIn(card);
      const chart = within(toggle).getByTestId("stats-table-toggle-chart");
      const data = within(toggle).getByTestId("stats-table-toggle-data");
      expect(chart).toHaveAttribute("aria-pressed", "true");
      expect(data).toHaveAttribute("aria-pressed", "false");
      // The chart surface (or the grid twin) is the default body; only the
      // volume card is a ChartFrame — the bars/donut cards render inline.
      if (card === cards[0] || card === cards[4]) {
        expect(card.querySelector("[data-testid='stats-chart-frame'], [data-testid='stats-rhythm-grid']")).toBeTruthy();
      }
      expect(within(card).queryAllByRole("table")).toHaveLength(0);
    }
  });

  it("the volume Data view renders the same rows the CSV export downloads", async () => {
    renderMarketStatsPage("/postings/stats");
    await waitFor(() =>
      expect(screen.getByTestId("stats-export-volume")).toBeTruthy(),
    );
    const card = cardOf("volume");
    const download = vi.mocked(statsExport.downloadStatsCsv);
    await userEvent.click(screen.getByTestId("stats-export-volume"));
    await userEvent.click(within(toggleIn(card)).getByTestId("stats-table-toggle-data"));
    await waitFor(() => expect(within(card).getAllByRole("table").length).toBeGreaterThan(0));
    const exported = download.mock.calls.filter((args) => args[0].startsWith("volume-"))[0]?.[1] as (string | number)[][];
    expect(exported).toBeTruthy();
    const texts = readTableTexts(card);
    // Header row first, then body rows: identical cells, no re-shaping.
    expect(texts).toHaveLength(exported.length);
    texts.forEach((row, index) =>
      expect(row).toEqual(exported[index].map((cell) => String(cell))),
    );
    await userEvent.click(within(toggleIn(card)).getByTestId("stats-table-toggle-chart"));
    expect(within(card).queryAllByRole("table")).toHaveLength(0);
  });

  it("the rhythm Data view is the condensed by-weekday/by-hour/peak twin, never 168 cells", async () => {
    renderMarketStatsPage("/postings/stats");
    await waitFor(() => expect(screen.getByTestId("stats-card-rhythm")).toBeTruthy());
    const card = cardOf("rhythm");
    await openDataView(card);
    await waitFor(() => expect(within(card).getAllByRole("table").length).toBeGreaterThan(0));
    const texts = readTableTexts(card);
    const body = texts.slice(1);
    expect(body).toHaveLength(32); // 7 weekdays + 24 hours + 1 peak
    expect(body[0]).toEqual(["Mon", "0"]);
    expect(body[body.length - 1]).toEqual(["Wed 09:00", "12"]);
  });

  it("the dimensions, salary and companies-top table views open too", async () => {
    renderMarketStatsPage("/postings/stats");
    await waitFor(() => expect(screen.getByTestId("stats-card-rhythm")).toBeTruthy());
    for (const [cardId, firstCell] of [
      ["dimensions", "synth"],
      ["salary", "EUR"],
      ["companies-top", "Acme Cloud"],
    ] as const) {
      const card = cardOf(cardId);
      await openDataView(card);
      const texts = readTableTexts(card);
      expect(texts[1]?.[0]).toBe(firstCell);
    }
  });

  it("the skills lists and the quadrant carry sr-only captions instead of a toggle", async () => {
    renderMarketStatsPage("/postings/stats");
    await waitFor(() => expect(screen.getByTestId("stats-skill-trend-python")).toBeTruthy());
    const skillsCard = cardOf("skills");
    expect(within(skillsCard).queryByTestId("stats-table-toggle")).toBeNull();
    const captions = Array.from(skillsCard.querySelectorAll(".sr-only"));
    expect(captions.length).toBe(2);
  });

  it("the table view is axe-clean and keyboard-reachable", async () => {
    renderMarketStatsPage("/postings/stats");
    await waitFor(() => expect(screen.getByTestId("stats-card-rhythm")).toBeTruthy());
    const card = cardOf("volume");
    await openDataView(card);
    expect(within(card).getAllByRole("table").length).toBeGreaterThan(0);
    // The Data table rides in; `heading-order` is disabled at this call for
    // the same fragment reason the harness itself disables `region`: this
    // card's h3 sits under the page's h1 in the real document — a whole-page
    // pre-existing skip (h1 → h3) nothing in this slice introduced.
    await expectNoA11yViolations(card, {
      rules: { "heading-order": { enabled: false } },
    });
  });
});
