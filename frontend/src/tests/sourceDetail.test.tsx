import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { SourceDetailPage } from "@/features/integrations/pages/SourceDetail";
import type { PostingSource, SourceRun } from "@/api/sources";

const SOURCE: PostingSource = {
  id: "src-1",
  key: "board-postings",
  connector_key: "mcp",
  kind: "posting",
  schedule_kind: null,
  config: { options: JSON.stringify({ max_pages: 2, keywords: 'devops' }) },
  query_mode: "radar",
  query_batch_size: 1,
  query_info: {
    keywords: "devops",
    location: "Athens, Greece",
    rotation: "1/1",
    rotation_index: 0,
    groups: [{ terms: ["devops"], keywords: "devops" }],
    provenance: { devops: ["radar-1"] },
    group_terms: ["devops"],
    curated: false,
    radar_ids: ["radar-1"],
    computed_at: "2026-10-27T09:00:00+00:00",
  },
  secret_hints: {},
  enabled: true,
  paused_at: null,
  last_status: "degraded",
  last_run_at: "2026-10-27T09:00:00+00:00",
  sync_state: {},
  error: "not-ready: bundle dependencies are not installed",
  posting_count: 12,
};

const RUNS: SourceRun[] = [
  {
    id: "run-1",
    trigger: "manual",
    status: "failed",
    started_at: "2026-10-27T09:00:00+00:00",
    finished_at: "2026-10-27T09:00:02+00:00",
    duration_ms: 2100,
    items_synced: 0,
    error: "not-ready: bundle dependencies are not installed",
  },
  {
    id: "run-2",
    trigger: "scheduled",
    status: "ok",
    started_at: "2026-10-26T22:00:00+00:00",
    finished_at: "2026-10-26T22:00:08+00:00",
    duration_ms: 8100,
    items_synced: 25,
    error: "",
  },
];

const mocks = vi.hoisted(() => ({
  fetchAdminSources: vi.fn(),
  fetchSourceRuns: vi.fn(),
  syncSource: vi.fn(),
  probeSource: vi.fn(),
  updateSource: vi.fn(),
  deleteSource: vi.fn(),
  fetchSystemSchedules: vi.fn(),
}));

vi.mock("@/api/sources", () => mocks);
vi.mock("@/api/scheduler", () => ({ fetchSystemSchedules: mocks.fetchSystemSchedules }));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/sources/src-1"]}>
      <Routes>
        <Route path="/sources/:sourceId" element={<SourceDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mocks.fetchAdminSources.mockResolvedValue([SOURCE]);
  mocks.fetchSourceRuns.mockResolvedValue(RUNS);
  mocks.syncSource.mockResolvedValue({ job_id: "j1", status: "queued" });
  mocks.fetchSystemSchedules.mockResolvedValue([
    {
      id: "sched-1",
      kind: "system_source_sync",
      task: "posting_sync",
      trigger: { type: "interval", params: { every_minutes: 60, jitter_minutes: 10 } },
    },
  ]);
});

afterEach(() => cleanup());

describe("SourceDetailPage", () => {
  it("renders the run history with status, duration, items and errors", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByTestId("source-detail")).toBeTruthy();
    await user.click(screen.getByRole("tab", { name: "Run history" }));
    const failed = await screen.findByTestId("run-run-1");
    expect(failed.textContent).toContain("Failed");
    expect(failed.textContent).toContain("2s");
    expect(failed.textContent).toContain("not-ready");
    const ok = await screen.findByTestId("run-run-2");
    expect(ok.textContent).toContain("Completed");
    expect(ok.textContent).toContain("25");
  });

  it("retries a run through the sync endpoint", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("tab", { name: "Run history" }));
    const failed = await screen.findByTestId("run-run-1");
    await user.click(within(failed).getByRole("button", { name: "Run again" }));
    expect(mocks.syncSource).toHaveBeenCalledWith("src-1");
  });

  it("clamps run errors to three lines and opens full details with copy", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("tab", { name: "Run history" }));
    const errorCell = await screen.findByTestId("run-error-run-1");
    expect(errorCell.className).toContain("line-clamp-3");
    await user.click(await screen.findByTestId("run-details-run-1"));
    const dialog = await screen.findByTestId("run-details");
    expect(dialog.textContent).toContain("bundle dependencies are not installed");
    expect(screen.getByRole("button", { name: "Copy" })).toBeTruthy();
  });

  it("shows the overview status and error", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("not-ready: bundle dependencies are not installed")).toBeTruthy();
    await user.click(screen.getByRole("tab", { name: "Query plan" }));
    expect(await screen.findByTestId("query-plan")).toBeTruthy();
  });

  it("blocks the radar → static switch while required fields are missing", async () => {
    const user = userEvent.setup();
    mocks.fetchAdminSources.mockResolvedValue([
      {
        ...SOURCE,
        query_mode: "radar",
        config: { options: JSON.stringify({ max_pages: 2 }) },
        tool_config_schema: {
          type: "object",
          properties: {
            keywords: { type: "string", title: "Keywords", minLength: 1 },
            max_pages: { type: "number", title: "Max pages" },
          },
          required: ["keywords"],
        },
      },
    ]);
    renderPage();
    await user.click(await screen.findByRole("tab", { name: "Configuration" }));
    await user.selectOptions(screen.getByLabelText("Search source"), "static");
    const notes = await screen.findAllByText(/switching to static mode/);
    expect(notes[0].textContent).toContain("keywords");
    expect(mocks.updateSource).not.toHaveBeenCalled();
  });

  it("switches to static when the required fields are present", async () => {
    const user = userEvent.setup();
    mocks.fetchAdminSources.mockResolvedValue([
      {
        ...SOURCE,
        query_mode: "radar",
        config: { options: JSON.stringify({ keywords: "devops", max_pages: 2 }) },
        tool_config_schema: {
          type: "object",
          properties: {
            keywords: { type: "string", title: "Keywords", minLength: 1 },
            max_pages: { type: "number", title: "Max pages" },
          },
          required: ["keywords"],
        },
      },
    ]);
    mocks.updateSource.mockResolvedValue({});
    renderPage();
    await user.click(await screen.findByRole("tab", { name: "Configuration" }));
    await user.selectOptions(screen.getByLabelText("Search source"), "static");
    await waitFor(() => expect(mocks.updateSource).toHaveBeenCalled());
    const call = mocks.updateSource.mock.calls[mocks.updateSource.mock.calls.length - 1]?.[1];
    expect(call.query_mode).toBe("static");
    expect(JSON.parse(call.config.options).keywords).toBe("devops");
  });
});


  it("configures pacing with presets and a live estimate, saving batch and budget", async () => {
    const user = userEvent.setup();
    mocks.fetchAdminSources.mockResolvedValue([
      {
        ...SOURCE,
        tool_config_schema: {
          type: "object",
          properties: {
            keywords: { type: "string", title: "Keywords" },
            max_pages: { type: "number", title: "Max pages" },
            budget_seconds: { type: "number", title: "Time budget" },
            detail_mode: { type: "string", title: "Detail mode" },
          },
        },
      },
    ]);
    mocks.updateSource.mockResolvedValue({});
    renderPage();
    await user.click(await screen.findByRole("tab", { name: "Configuration" }));
    expect(screen.getByTestId("pacing-card")).toBeTruthy();

    await user.click(screen.getByRole("tab", { name: "Thorough · 90s" }));
    await user.click(screen.getByRole("tab", { name: "2" }));
    expect(screen.getByTestId("pacing-estimate").textContent).toContain("Fits");

    await user.click(screen.getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(mocks.updateSource).toHaveBeenCalled());
    const call = mocks.updateSource.mock.calls[mocks.updateSource.mock.calls.length - 1]?.[1];
    expect(call.query_batch_size).toBe(2);
    expect(JSON.parse(call.config.options).budget_seconds).toBe(90);
    expect(JSON.parse(call.config.options).detail_mode ?? "all").toBe("all");
  });

  it("accepts a custom role-group count and budget through the Custom entry", async () => {
    const user = userEvent.setup();
    mocks.fetchAdminSources.mockResolvedValue([
      {
        ...SOURCE,
        tool_config_schema: {
          type: "object",
          properties: {
            max_pages: { type: "number", title: "Max pages" },
            budget_seconds: { type: "number", title: "Time budget" },
            detail_mode: { type: "string", title: "Detail mode" },
          },
        },
      },
    ]);
    mocks.updateSource.mockResolvedValue({});
    renderPage();
    await user.click(await screen.findByRole("tab", { name: "Configuration" }));

    const batchRow = screen.getByTestId("pacing-Role groups per sync");
    await user.click(within(batchRow).getByRole("tab", { name: "Custom…" }));
    const batchInput = screen.getByTestId("pacing-Role groups per sync-custom");
    expect(batchInput).toHaveAttribute("min", "1");
    expect(batchInput).toHaveAttribute("max", "6");
    await user.clear(batchInput);
    await user.type(batchInput, "5");

    const budgetRow = screen.getByTestId("pacing-Time budget");
    await user.click(within(budgetRow).getByRole("tab", { name: "Custom…" }));
    const budgetInput = screen.getByTestId("pacing-Time budget-custom");
    expect(budgetInput).toHaveAttribute("min", "20");
    expect(budgetInput).toHaveAttribute("max", "90");
    await user.clear(budgetInput);
    await user.type(budgetInput, "75");

    // picking a preset again returns to the presets
    await user.click(within(batchRow).getByRole("tab", { name: "3" }));
    expect(screen.queryByTestId("pacing-Role groups per sync-custom")).toBeNull();

    await user.click(within(batchRow).getByRole("tab", { name: "Custom…" }));
    const reopened = screen.getByTestId("pacing-Role groups per sync-custom");
    await user.clear(reopened);
    await user.type(reopened, "4");

    await user.click(screen.getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(mocks.updateSource).toHaveBeenCalled());
    const call = mocks.updateSource.mock.calls[mocks.updateSource.mock.calls.length - 1]?.[1];
    expect(call.query_batch_size).toBe(4);
    expect(JSON.parse(call.config.options).budget_seconds).toBe(75);
  });
