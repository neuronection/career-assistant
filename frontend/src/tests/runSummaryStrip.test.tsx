import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { RunDetailsDialog } from "@/components/settings/RunDetailsDialog";
import { RunSummaryStrip } from "@/components/settings/RunSummaryStrip";
import type { RunSummary, SourceRun } from "@/api/sources";

const SUMMARY: RunSummary = {
  schema: 1,
  mode: "guest",
  launches: { guest: 1, authenticated: 1 },
  navigations: { search_pages: 2, detail_pages: 5 },
  walled_skips: ["4101111101"],
  budget: { limit_s: 80, search_used_s: 30, detail_used_s: 20 },
  rows: { kept: 25, capped: 0 },
};

const RUN_WITH_SUMMARY: SourceRun = {
  id: "run-1",
  trigger: "manual",
  status: "degraded",
  started_at: "2026-10-27T09:00:00+00:00",
  finished_at: "2026-10-27T09:01:20+00:00",
  duration_ms: 80_000,
  items_synced: 25,
  error: "auth: this posting requires a signed-in view",
  report: {
    synced: 25,
    errors: [
      { code: "auth", detail: "this posting requires a signed-in view" },
    ],
    run_summary: SUMMARY,
  },
};

afterEach(() => cleanup());

describe("RunSummaryStrip", () => {
  it("renders the mode chip, launches, navigations and the budget split", () => {
    render(<RunSummaryStrip summary={SUMMARY} />);
    expect(screen.getByTestId("run-summary-mode").textContent).toContain(
      "Guest",
    );
    expect(screen.getByTestId("run-summary-launches").textContent).toContain(
      "guest 1",
    );
    expect(screen.getByTestId("run-summary-navigations").textContent).toContain(
      "search 2",
    );
    expect(screen.getByTestId("run-summary-budget-search").style.width).toBe(
      "37.5%",
    );
    expect(screen.getByTestId("run-summary-budget-detail").style.width).toBe(
      "25%",
    );
    expect(
      screen.getByTestId("run-summary-budget-label").textContent,
    ).toContain("80");
  });

  it("clamps the budget bar at full width when the run overran its budget", () => {
    render(
      <RunSummaryStrip
        summary={{
          ...SUMMARY,
          budget: { limit_s: 10, search_used_s: 30, detail_used_s: 20 },
        }}
      />,
    );
    expect(screen.getByTestId("run-summary-budget-search").style.width).toBe(
      "100%",
    );
    expect(screen.getByTestId("run-summary-budget-detail").style.width).toBe(
      "0%",
    );
  });

  it("shows the walled-skip count and expands the capped id list", async () => {
    const user = userEvent.setup();
    const walled = Array.from(
      { length: 20 },
      (_, i) => `41011111${String(i).padStart(2, "0")}`,
    );
    render(<RunSummaryStrip summary={{ ...SUMMARY, walled_skips: walled }} />);
    expect(screen.queryByTestId("run-summary-walled-ids")).toBeNull();
    await user.click(screen.getByTestId("run-summary-walled-toggle"));
    const ids = screen.getByTestId("run-summary-walled-ids");
    expect(ids.textContent).toContain("4101111100");
    expect(ids.textContent).toContain("4101111119");
    expect(ids.textContent?.split(",").length).toBe(20);
  });

  it("omits the line for cap-dropped keys instead of rendering zeros", () => {
    render(
      <RunSummaryStrip
        summary={{
          schema: 1,
          mode: "guest",
          walled_skips: ["4101111101"],
          rows: { kept: 25, capped: 0 },
        }}
      />,
    );
    expect(screen.getByTestId("run-summary-mode").textContent).toContain("Guest");
    expect(screen.queryByTestId("run-summary-launches")).toBeNull();
    expect(screen.queryByTestId("run-summary-navigations")).toBeNull();
    expect(screen.queryByTestId("run-summary-budget-bar")).toBeNull();
    expect(screen.queryByTestId("run-summary-budget-label")).toBeNull();
  });

  it("renders the facts but no mode chip when the summary states no mode", () => {
    render(
      <RunSummaryStrip
        summary={{ schema: 1, launches: { guest: 1, authenticated: 0 } }}
      />,
    );
    expect(screen.queryByTestId("run-summary-mode")).toBeNull();
    expect(screen.getByTestId("run-summary-launches").textContent).toContain(
      "guest 1",
    );
  });

  it("renders nothing for an empty summary object — no invented facts", () => {
    const { container } = render(<RunSummaryStrip summary={{}} />);
    expect(container.querySelector('[data-testid="run-summary"]')).toBeNull();
  });

  it("hides itself in the drawer when the run has no summary", async () => {
    const { report: _report, ...rest } = RUN_WITH_SUMMARY;
    render(<RunDetailsDialog run={rest} onClose={() => {}} />);
    expect(await screen.findByTestId("run-details")).toBeTruthy();
    expect(screen.queryByTestId("run-summary")).toBeNull();
  });

  it("rides inside the run drawer when the report carries a summary", async () => {
    render(<RunDetailsDialog run={RUN_WITH_SUMMARY} onClose={() => {}} />);
    expect(await screen.findByTestId("run-summary")).toBeTruthy();
    expect(screen.getByTestId("run-summary-mode").textContent).toContain(
      "Guest",
    );
  });
});
