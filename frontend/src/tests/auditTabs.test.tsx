import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";

import {
  AUDIT_TABS,
  Audit,
  parseAuditTab,
  parseAuditWindow,
} from "@/pages/settings/Audit";
import { OverviewTab } from "@/components/audit/OverviewTab";
import {
  AUDIT_CATEGORIES,
  categoryRollup,
  formatTokens,
  formatTokensExact,
} from "@/config/auditVocab";
import type {
  AuditChangeRow,
  AuditEventRow,
  AuditFailuresPreview,
  AuditJobRow,
  AIGenerationRow,
  AuditOverview,
  AuditSeries,
  AuditSourceRunRow,
} from "@/api/audit";

vi.mock("@/api/audit", () => ({
  fetchAuditOverview: vi.fn(),
  fetchAuditTimeseries: vi.fn(),
  fetchAuditBreakdown: vi.fn(),
  fetchAuditEvents: vi.fn(),
  fetchAuditGenerations: vi.fn(),
  fetchAuditJobs: vi.fn(),
  fetchAuditJobFacets: vi.fn(),
  fetchAuditSourceRuns: vi.fn(),
  fetchAuditChanges: vi.fn(),
  exportAuditCsv: vi.fn(),
  fetchAuditProduction: vi.fn(),
  fetchAuditFailures: vi.fn(),
  requeueAuditJobs: vi.fn(),
}));

import {
  exportAuditCsv,
  fetchAuditBreakdown,
  fetchAuditChanges,
  fetchAuditEvents,
  fetchAuditFailures,
  fetchAuditGenerations,
  fetchAuditJobFacets,
  fetchAuditJobs,
  fetchAuditOverview,
  fetchAuditProduction,
  fetchAuditSourceRuns,
  fetchAuditTimeseries,
  requeueAuditJobs,
} from "@/api/audit";

const OVERVIEW: AuditOverview = {
  window: "24h",
  ai: {
    calls: 12,
    errors: 1,
    error_rate: 0.0833,
    tokens_in: 4000,
    tokens_out: 1000,
    avg_latency_ms: 1500,
    max_latency_ms: 3000,
    prev_calls: 8,
    prev_errors: 0,
  },
  jobs: { failed: 1, running: 0, queued: 2 },
  schedules: { failing: 0 },
  auth: { events: 5, denied: 1 },
  recent_failures: [
    {
      stream: "ai",
      title: "match_score",
      detail: "429 rate limit",
      occurred_at: "2026-10-30T10:04:00Z",
    },
    {
      stream: "job",
      title: "posting_sync",
      detail: "timeout",
      occurred_at: "2026-10-30T09:58:00Z",
    },
  ],
};

const SERIES: AuditSeries = {
  window: "24h",
  bucket: "hour",
  points: [
    { bucket: "2026-10-30T09:00:00", calls: 7, errors: 0, tokens_in: 1, tokens_out: 1 },
    { bucket: "2026-10-30T10:00:00", calls: 5, errors: 1, tokens_in: 2, tokens_out: 1 },
  ],
};

const GENERATIONS: AIGenerationRow[] = [
  {
    id: "gen-ok",
    task_type: "chat",
    provider: "openai",
    model: "gpt-4o-mini",
    prompt: "hello",
    output: { reply: "hi" },
    tokens_in: 5329,
    tokens_out: 356,
    latency_ms: 900,
    status: "ok",
    error: "",
    task_tier: "fast",
    prompt_version: "v12",
    pack_key: null,
    pack_version: null,
    run_id: "11111111-1111-1111-1111-111111111111",
    run_stage: "reply",
    user_id: null,
    created_at: "2026-10-30T10:31:00Z",
  },
  {
    id: "gen-mock",
    task_type: "cv_draft",
    provider: "mock",
    model: "structured",
    prompt: "draft",
    output: null,
    tokens_in: null,
    tokens_out: null,
    latency_ms: 40,
    status: "ok",
    error: "",
    task_tier: null,
    prompt_version: null,
    pack_key: null,
    pack_version: null,
    run_id: null,
    run_stage: null,
    user_id: null,
    created_at: "2026-10-30T10:29:00Z",
  },
];

const REMOTE_GENERATION: AIGenerationRow = {
  ...GENERATIONS[0],
  id: "gen-remote",
  task_type: "match_score",
  status: "error",
  error: "429 rate limit",
};

const EVENTS: AuditEventRow[] = [
  {
    id: "evt-1",
    action: "auth.login",
    actor: "11111111-1111-1111-1111-111111111111",
    actor_email: "admin@example.com",
    resource: "",
    outcome: "ok",
    created_at: "2026-10-30T10:29:00Z",
  },
  {
    id: "evt-2",
    action: "auth.login",
    actor: "10.0.4.12",
    actor_email: null,
    resource: "",
    outcome: "denied",
    created_at: "2026-10-30T10:41:00Z",
  },
];

const JOBS: AuditJobRow[] = [
  {
    id: "job-1",
    job_type: "posting_sync",
    status: "failed",
    stage: "fetch",
    progress: 40,
    attempts: 2,
    max_attempts: 3,
    error: "timeout after 120s",
    created_at: "2026-10-30T09:58:00Z",
    finished_at: "2026-10-30T10:00:00Z",
    user_id: null,
    user_email: "admin@example.com",
    payload: { source: "board-postings" },
    result: { items: 3 },
  },
];

const FAILED_GROUP_JOBS: AuditJobRow[] = [
  {
    id: "fail-1",
    job_type: "posting_extract",
    status: "failed",
    stage: null,
    progress: 0,
    attempts: 2,
    max_attempts: 2,
    error: "Connection reset by peer",
    created_at: "2026-10-30T09:10:00Z",
    finished_at: "2026-10-30T09:12:00Z",
    user_id: null,
    user_email: null,
    payload: { posting_id: "p-9" },
    result: null,
  },
];

const FAILURES_PREVIEW: AuditFailuresPreview = {
  groups: [
    {
      job_type: "posting_extract",
      window_count: 3,
      top_error: "Connection reset by peer",
      est_jobs: 3,
      full_rerun: false,
      sweep: false,
    },
    {
      job_type: "autopilot_run",
      window_count: 1,
      top_error: "provider quota exhausted",
      est_jobs: 1,
      full_rerun: true,
      sweep: false,
    },
    {
      job_type: "query_curator",
      window_count: 5,
      top_error: "provider down",
      est_jobs: 1,
      full_rerun: false,
      sweep: true,
    },
  ],
  cap: 200,
  total_failed: 9,
  truncated: 0,
  skipped_dup_preview: 1,
};

const RUNS: AuditSourceRunRow[] = [
  {
    id: "run-1",
    source_id: "src-1",
    source_key: "board-postings",
    connector_key: "demo",
    trigger: "scheduled",
    status: "failed",
    started_at: "2026-10-30T09:58:00Z",
    finished_at: "2026-10-30T10:00:00Z",
    duration_ms: 120000,
    items_synced: 0,
    error: "boom",
  },
];

const CHANGES: AuditChangeRow[] = [
  {
    id: "chg-1",
    occurred_at: "2026-10-30T09:00:00Z",
    actor_kind: "sync_run",
    outcome: "ok",
    posting_id: "11111111-1111-1111-1111-111111111111",
    duration_ms: 900,
    actor_ref: { run_id: "r-1" },
    operation: null,
    diff: { title: { from: "Old", to: "New" } },
  },
];

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location-probe">{location.pathname + location.search}</span>;
}

function renderPage(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Audit />
      <LocationProbe />
    </MemoryRouter>,
  );
}

const probe = () => screen.getByTestId("location-probe").textContent;

describe("audit tab helpers", () => {
  it("AUDIT_TABS is overview-first with the failures and retrieval tabs", () => {
    expect([...AUDIT_TABS]).toEqual([
      "overview",
      "ai",
      "usage",
      "security",
      "jobs",
      "failures",
      "changes",
      "retrieval",
    ]);
  });

  it("parseAuditTab falls back to overview on unknown values", () => {
    expect(parseAuditTab(null)).toBe("overview");
    expect(parseAuditTab("security")).toBe("security");
    expect(parseAuditTab("failures")).toBe("failures");
    expect(parseAuditTab("bogus")).toBe("overview");
  });

  it("parseAuditWindow only accepts presets (retrieval adds 90d)", () => {
    expect(parseAuditWindow(null)).toBe("24h");
    expect(parseAuditWindow("7d")).toBe("7d");
    expect(parseAuditWindow("90d")).toBe("90d");
    expect(parseAuditWindow("bogus")).toBe("24h");
  });
});

describe("formatTokens", () => {
  it("abbreviates with one decimal below 10k and integers above", () => {
    expect(formatTokens(5329)).toBe("5.3k");
    expect(formatTokens(5_000)).toBe("5k");
    expect(formatTokens(12_400)).toBe("12k");
    expect(formatTokens(1_200_000)).toBe("1.2M");
    expect(formatTokens(950)).toBe("950");
  });

  it("formatTokensExact always renders the locale number", () => {
    expect(formatTokensExact(5329)).toBe("5,329");
  });
});

describe("categoryRollup", () => {
  it("groups task rows into categories ordered by calls", () => {
    const rollup = categoryRollup([
      { key: "chat", calls: 10, errors: 0, tokens_in: 0, tokens_out: 0 },
      { key: "interview_turn", calls: 4, errors: 1, tokens_in: 0, tokens_out: 0 },
      { key: "cv_draft", calls: 6, errors: 0, tokens_in: 0, tokens_out: 0 },
      { key: "unknown_task", calls: 2, errors: 0, tokens_in: 0, tokens_out: 0 },
    ]);
    expect(rollup.map((r) => r.category)).toEqual(["chat", "cv", "ops"]);
    expect(rollup[0]).toMatchObject({ category: "chat", calls: 14, errors: 1 });
    for (const row of rollup) {
      expect(AUDIT_CATEGORIES).toContain(row.category);
    }
  });
});

describe("audit page tabs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchAuditOverview).mockResolvedValue(OVERVIEW);
    vi.mocked(fetchAuditTimeseries).mockResolvedValue(SERIES);
    vi.mocked(fetchAuditBreakdown).mockResolvedValue({
      dimension: "task",
      window: "24h",
      rows: [
        { key: "chat", calls: 7, errors: 0, tokens_in: 0, tokens_out: 0 },
        { key: "cv_draft", calls: 5, errors: 1, tokens_in: 0, tokens_out: 0 },
      ],
    });
    vi.mocked(fetchAuditGenerations).mockImplementation(async (params) => {
      if (params?.id) {
        const row = [...GENERATIONS, REMOTE_GENERATION].find((g) => g.id === params.id);
        return { total: row ? 1 : 0, items: row ? [row] : [] };
      }
      return { total: 2, items: GENERATIONS };
    });
    vi.mocked(fetchAuditEvents).mockResolvedValue({ total: 2, items: EVENTS });
    vi.mocked(fetchAuditJobs).mockResolvedValue({ total: 1, items: JOBS });
    vi.mocked(fetchAuditJobFacets).mockResolvedValue({
      rows: [{ key: "posting_sync", count: 1 }],
    });
    vi.mocked(fetchAuditSourceRuns).mockResolvedValue({ total: 1, items: RUNS });
    vi.mocked(fetchAuditChanges).mockResolvedValue({
      entity: "postings",
      total: 1,
      items: CHANGES,
    });
    vi.mocked(exportAuditCsv).mockResolvedValue(new Blob(["csv"]));
    vi.mocked(fetchAuditFailures).mockResolvedValue(FAILURES_PREVIEW);
    vi.mocked(requeueAuditJobs).mockResolvedValue({
      requeued: 8,
      skipped_dup: 1,
      skipped_cap: 0,
      collapsed: 4,
      cap: 200,
      items: [],
    });
    vi.mocked(fetchAuditProduction).mockResolvedValue({
      postings: {
        ingested: 5,
        by_status: { mapped: 5 },
        ingested_items: 42,
        activity: { sync_run: 3, extract_llm: 2 },
      },
      skills: { created: 4, promoted: 1 },
      companies: { created: 2, by_source: { manual: 2 } },
      catalog_jobs: {
        created: 3,
        by_status: { published: 3 },
        by_source: { ai: 3 },
      },
    });
  });

  it("renders the overview KPIs, categories and failure feed", async () => {
    renderPage("/settings/audit");
    expect(await screen.findByTestId("audit-kpis")).toBeTruthy();
    expect(screen.getAllByTestId("stat-tile").length).toBe(6);
    expect(await screen.findByTestId("audit-categories")).toBeTruthy();
    expect(screen.getAllByTestId("audit-category-row").length).toBe(2);
    expect(screen.getAllByTestId("audit-failure-row").length).toBe(2);
    expect(screen.getByText("match_score")).toBeTruthy();
    expect(fetchAuditOverview).toHaveBeenCalledWith({ window: "24h" });
    expect(screen.getByTestId("audit-auto-refresh")).toBeTruthy();
  });

  it("canonicalizes an unknown tab param", async () => {
    renderPage("/settings/audit?tab=bogus");
    await screen.findByTestId("audit-kpis");
    await waitFor(() => expect(probe()).toBe("/settings/audit"));
  });

  it("lands the AI tab deep link, marks mock rows simulated and opens the drawer", async () => {
    renderPage("/settings/audit?tab=ai");
    expect(await screen.findByTestId("audit-ai-tab")).toBeTruthy();
    expect(screen.getByTestId("audit-gen-simulated-gen-mock")).toBeTruthy();

    const tokensCell = screen.getByTitle("5,329 → 356");
    expect(tokensCell.textContent).toBe("5.3k → 356");
    const mockRow = screen.getByTestId("audit-gen-row-gen-mock");
    expect(mockRow.textContent).toContain("—");
    expect(mockRow.textContent).not.toContain("?");

    await userEvent.click(screen.getByTestId("audit-gen-row-gen-ok"));
    expect(await screen.findByTestId("audit-gen-drawer")).toBeTruthy();
    expect(screen.getByTestId("audit-gen-meta").textContent).toContain("5,329 → 356");
    const pairs = screen.getByTestId("audit-parsed-pairs");
    expect(pairs.textContent).toContain("reply");
    expect(pairs.textContent).toContain("hi");
    expect(probe()).toBe("/settings/audit?tab=ai&detail=gen-ok");

    await userEvent.click(screen.getByRole("tab", { name: "Raw" }));
    const raw = screen.getByTestId("audit-gen-drawer");
    expect(raw.textContent).toContain('"reply": "hi"');

    expect(screen.getByTestId("audit-gen-drawer-prev")).toBeDisabled();
    await userEvent.click(screen.getByTestId("audit-gen-drawer-next"));
    await waitFor(() =>
      expect(screen.getByTestId("audit-gen-row-gen-mock")).toBeTruthy(),
    );
    expect(screen.getByTestId("audit-gen-drawer-prev")).toBeEnabled();
  });

  it("syncs the AI task filter with ?task=embed and clears it", async () => {
    renderPage("/settings/audit?tab=ai&task=embed");
    await screen.findByTestId("audit-ai-tab");
    await waitFor(() =>
      expect(fetchAuditGenerations).toHaveBeenLastCalledWith(
        expect.objectContaining({ task: "embed", offset: 0 }),
      ),
    );
    expect(screen.getByTestId("audit-filter-task")).toHaveValue("embed");

    await userEvent.selectOptions(screen.getByTestId("audit-filter-task"), "");
    await waitFor(() => expect(probe()).toBe("/settings/audit?tab=ai"));
    await waitFor(() =>
      expect(fetchAuditGenerations).toHaveBeenLastCalledWith(
        expect.not.objectContaining({ task: expect.anything() }),
      ),
    );
  });

  it("resolves an off-page ?detail= row by id", async () => {
    renderPage("/settings/audit?tab=ai&detail=gen-remote");
    expect(await screen.findByTestId("audit-gen-drawer")).toBeTruthy();
    expect(screen.getByTestId("audit-gen-error")).toBeTruthy();
    expect(screen.getByText("429 rate limit")).toBeTruthy();
    expect(fetchAuditGenerations).toHaveBeenCalledWith(
      expect.objectContaining({ id: "gen-remote", limit: 1 }),
    );
    expect(screen.queryByTestId("audit-gen-drawer-prev")).toBeNull();
  });

  it("applies the task facet filter and pages the ledger", async () => {
    vi.mocked(fetchAuditGenerations).mockResolvedValue({
      total: 75,
      items: GENERATIONS,
    });
    renderPage("/settings/audit?tab=ai");
    await screen.findByTestId("audit-gen-range");

    await userEvent.selectOptions(screen.getByTestId("audit-filter-task"), "chat");
    await waitFor(() =>
      expect(fetchAuditGenerations).toHaveBeenLastCalledWith(
        expect.objectContaining({ task: "chat", offset: 0 }),
      ),
    );
    await waitFor(() =>
      expect(screen.getByTestId("audit-gen-range").textContent).toContain("75"),
    );

    await userEvent.click(screen.getByTestId("audit-gen-next"));
    await waitFor(() =>
      expect(fetchAuditGenerations).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 50 }),
      ),
    );
  });

  it("renders the security trail with outcome filters", async () => {
    renderPage("/settings/audit?tab=security");
    expect(await screen.findByTestId("audit-security-tab")).toBeTruthy();
    expect(screen.getAllByTestId("audit-event-row").length).toBe(2);
    expect(screen.getByText("admin@example.com")).toBeTruthy();
    expect(fetchAuditEvents).toHaveBeenCalledWith(
      expect.objectContaining({ group: "all", window: "24h" }),
    );
  });

  it("renders the usage tab with model rows, token trend and throughput", async () => {
    vi.mocked(fetchAuditBreakdown).mockResolvedValue({
      dimension: "model",
      window: "24h",
      rows: [
        {
          key: "openai/gpt-4o-mini",
          calls: 2,
          errors: 0,
          tokens_in: 200,
          tokens_out: 40,
          avg_latency_ms: 850,
        },
        {
          key: "google/gemini-2.5-flash",
          calls: 1,
          errors: 0,
          tokens_in: 100,
          tokens_out: 10,
          avg_latency_ms: 900,
        },
      ],
    });
    renderPage("/settings/audit?tab=usage");
    expect(await screen.findByTestId("audit-usage-tab")).toBeTruthy();
    expect(screen.getAllByTestId("audit-model-row").length).toBe(2);
    expect(screen.getByText("openai/gpt-4o-mini")).toBeTruthy();
    expect(await screen.findByTestId("audit-throughput-tiles")).toBeTruthy();
    expect(screen.getAllByTestId("stat-tile").length).toBe(4);
    expect(await screen.findByTestId("audit-posting-activity")).toBeTruthy();
    expect(screen.getAllByTestId("audit-skill-events")).toBeTruthy();
    expect(fetchAuditProduction).toHaveBeenCalledWith(
      expect.objectContaining({ window: "24h" }),
    );
  });

  it("auto-refresh refetches on the interval when enabled", async () => {
    vi.useFakeTimers();
    try {
      render(
        <MemoryRouter initialEntries={["/settings/audit"]}>
          <OverviewTab range={{ window: "24h" }} refreshMs={50} />
        </MemoryRouter>,
      );
      await vi.advanceTimersByTimeAsync(5);
      const initial = vi.mocked(fetchAuditOverview).mock.calls.length;
      expect(initial).toBeGreaterThanOrEqual(1);

      fireEvent.click(screen.getByTestId("audit-auto-refresh"));
      await vi.advanceTimersByTimeAsync(120);
      expect(vi.mocked(fetchAuditOverview).mock.calls.length).toBeGreaterThan(initial);
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders the jobs tab with facets, expandable rows and source runs", async () => {
    renderPage("/settings/audit?tab=jobs");
    expect(await screen.findByTestId("audit-jobs-tab")).toBeTruthy();
    expect(screen.getByTestId("audit-job-row-job-1")).toBeTruthy();
    expect(screen.getByText("admin@example.com")).toBeTruthy();

    await userEvent.click(screen.getByTestId("audit-job-row-job-1"));
    expect(screen.getByTestId("audit-job-detail-job-1")).toBeTruthy();

    expect(screen.getAllByTestId("audit-source-run-row").length).toBe(1);
    expect(screen.getByText("board-postings")).toBeTruthy();
    expect(fetchAuditJobs).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 50, offset: 0 }),
    );
  });

  it("exports the jobs CSV from the jobs tab with the active filters", async () => {
    renderPage("/settings/audit?tab=jobs");
    await screen.findByTestId("audit-jobs-tab");
    await userEvent.click(screen.getByTestId("audit-jobs-export"));
    await waitFor(() =>
      expect(exportAuditCsv).toHaveBeenCalledWith(
        "jobs",
        expect.objectContaining({ window: "7d" }),
      ),
    );
  });

  it("exports the source runs and changes CSVs", async () => {
    renderPage("/settings/audit?tab=jobs");
    await screen.findByTestId("audit-jobs-tab");
    await userEvent.click(screen.getByTestId("audit-runs-export"));
    await waitFor(() =>
      expect(exportAuditCsv).toHaveBeenCalledWith(
        "source_runs",
        expect.objectContaining({ window: "7d" }),
      ),
    );

    renderPage("/settings/audit?tab=changes");
    await screen.findByTestId("audit-changes-tab");
    await userEvent.click(screen.getByTestId("audit-changes-export"));
    await waitFor(() =>
      expect(exportAuditCsv).toHaveBeenCalledWith(
        "changes",
        expect.objectContaining({ entity: "postings", window: "7d" }),
      ),
    );
  });

  it("exports the events CSV from the security tab", async () => {
    renderPage("/settings/audit?tab=security");
    await screen.findByTestId("audit-security-tab");
    await userEvent.click(screen.getByTestId("audit-events-export"));
    await waitFor(() =>
      expect(exportAuditCsv).toHaveBeenCalledWith(
        "events",
        expect.objectContaining({ group: "all" }),
      ),
    );
  });

  it("renders the changes tab and switches journal entity", async () => {
    renderPage("/settings/audit?tab=changes");
    expect(await screen.findByTestId("audit-changes-tab")).toBeTruthy();
    expect(screen.getAllByTestId("audit-change-row").length).toBe(1);
    expect(fetchAuditChanges).toHaveBeenCalledWith(
      expect.objectContaining({ entity: "postings", window: "7d" }),
    );

    await userEvent.click(screen.getByRole("tab", { name: "Skills" }));
    await waitFor(() =>
      expect(fetchAuditChanges).toHaveBeenLastCalledWith(
        expect.objectContaining({ entity: "skills" }),
      ),
    );
  });

  it("sends a custom from/to range on the AI tab", async () => {
    renderPage("/settings/audit?tab=ai");
    await screen.findByTestId("audit-gen-range-filter");

    await userEvent.selectOptions(
      screen.getByTestId("audit-gen-range-filter"),
      "custom",
    );
    await userEvent.type(screen.getByTestId("audit-gen-range-filter-from"), "2026-10-01");
    await userEvent.type(screen.getByTestId("audit-gen-range-filter-to"), "2026-10-20");
    await waitFor(() =>
      expect(fetchAuditGenerations).toHaveBeenLastCalledWith(
        expect.objectContaining({
          from: "2026-10-01T00:00:00",
          to: "2026-10-21T00:00:00",
        }),
      ),
    );
  });

  it("renders the failures tab with grouped cards, badges and counts", async () => {
    renderPage("/settings/audit?tab=failures");
    expect(await screen.findByTestId("audit-failures-tab")).toBeTruthy();
    expect(fetchAuditFailures).toHaveBeenCalledWith(
      expect.objectContaining({ window: "24h" }),
    );
    expect(screen.getByTestId("audit-failure-group-posting_extract")).toBeTruthy();
    expect(screen.getByText("Connection reset by peer")).toBeTruthy();
    expect(screen.getAllByTestId("audit-failure-count").length).toBe(3);
    expect(screen.getByTestId("audit-failure-full-rerun")).toBeTruthy();
    expect(screen.getByTestId("audit-failure-sweep")).toBeTruthy();
    const maintenance = screen.getByTestId("audit-failures-maintenance");
    expect(maintenance.getAttribute("href")).toBeNull();
    expect(screen.getByText("Embeddings recompute").getAttribute("href")).toBe(
      "/settings/tools?section=retrieval",
    );
    expect(screen.getByText("Scheduled sweeps").getAttribute("href")).toBe(
      "/settings/automations",
    );
  });

  it("lands the ?job_type= pre-filter with a live group and keeps it", async () => {
    renderPage("/settings/audit?tab=failures&job_type=posting_extract");
    await screen.findByTestId("audit-failures-tab");
    await waitFor(() => expect(probe()).toBe("/settings/audit?tab=failures&job_type=posting_extract"));
    expect(fetchAuditFailures).toHaveBeenCalledWith(
      expect.objectContaining({ window: "24h", job_type: "posting_extract" }),
    );
  });

  it("keeps the window param on the failures tab and fetches the chosen window", async () => {
    renderPage("/settings/audit?tab=failures&window=7d");
    await screen.findByTestId("audit-failures-tab");
    await waitFor(() =>
      expect(fetchAuditFailures).toHaveBeenLastCalledWith(
        expect.objectContaining({ window: "7d" }),
      ),
    );
    await waitFor(() => expect(probe()).toBe("/settings/audit?tab=failures&window=7d"));
  });

  it("clears a stale job_type filter once the preview has no such group", async () => {
    renderPage("/settings/audit?tab=failures&job_type=gone_type");
    await screen.findByTestId("audit-failures-tab");
    expect(fetchAuditFailures).toHaveBeenCalledWith(
      expect.objectContaining({ window: "24h", job_type: "gone_type" }),
    );
    await waitFor(() => expect(probe()).toBe("/settings/audit?tab=failures"));
    await waitFor(() =>
      expect(fetchAuditFailures).toHaveBeenLastCalledWith(
        expect.not.objectContaining({ job_type: expect.anything() }),
      ),
    );
  });

  it("expands a group into failed job rows and opens the detail drawer", async () => {
    vi.mocked(fetchAuditJobs).mockResolvedValue({
      total: 1,
      items: FAILED_GROUP_JOBS,
    });
    renderPage("/settings/audit?tab=failures");
    await screen.findByTestId("audit-failures-tab");
    await userEvent.click(screen.getByTestId("audit-failure-group-toggle-posting_extract"));
    await waitFor(() =>
      expect(fetchAuditJobs).toHaveBeenCalledWith(
        expect.objectContaining({
          status: "failed",
          job_type: "posting_extract",
          limit: 20,
        }),
      ),
    );
    await userEvent.click(screen.getByTestId("audit-failure-row-link-fail-1"));
    const drawer = await screen.findByTestId("audit-failure-drawer");
    expect(drawer.textContent).toContain("Connection reset by peer");
    expect(drawer.textContent).toContain("posting_id");
  });

  it("runs the confirmed requeue-all flow once with the previewed filters and shows the outcome", async () => {
    renderPage("/settings/audit?tab=failures");
    await screen.findByTestId("audit-failures-tab");
    await userEvent.click(screen.getByTestId("audit-failures-requeue-all"));
    const confirm = screen.getByTestId("audit-failures-confirm");
    expect(confirm.textContent).toContain("Requeues 5 jobs across all types");
    expect(confirm.textContent).toContain("cap 200 per action");
    expect(confirm.textContent).toContain("1 duplicate skipped");

    await userEvent.click(screen.getByTestId("audit-failures-confirm-go"));
    await waitFor(() =>
      expect(requeueAuditJobs).toHaveBeenCalledTimes(1),
    );
    expect(requeueAuditJobs).toHaveBeenCalledWith(
      expect.objectContaining({ window: "24h", confirm: true }),
    );
    const outcome = await screen.findByTestId("audit-failures-outcome");
    expect(outcome.textContent).toContain("8 requeued");
    expect(outcome.textContent).toContain("1 skipped (duplicate queued)");
    expect(outcome.textContent).toContain("0 skipped (cap)");
    expect(outcome.textContent).toContain("4 collapsed into one sweep requeue");
    await waitFor(() => expect(fetchAuditFailures).toHaveBeenCalledTimes(2));
  });

  it("requeues one job from the group flow and one from the drawer", async () => {
    vi.mocked(fetchAuditJobs).mockResolvedValue({
      total: 1,
      items: FAILED_GROUP_JOBS,
    });
    renderPage("/settings/audit?tab=failures");
    await screen.findByTestId("audit-failures-tab");
    await userEvent.click(screen.getByTestId("audit-failure-group-toggle-posting_extract"));
    await userEvent.click(screen.getByTestId("audit-failure-requeue-posting_extract"));
    const confirm = await screen.findByTestId("audit-failures-confirm");
    expect(confirm.textContent).toContain("of this type");
    await userEvent.click(screen.getByTestId("audit-failures-confirm-go"));
    await waitFor(() =>
      expect(requeueAuditJobs).toHaveBeenCalledWith(
        expect.objectContaining({ job_type: "posting_extract", confirm: true }),
      ),
    );

    vi.mocked(requeueAuditJobs).mockClear();
    await waitFor(() =>
      expect(screen.queryByTestId("audit-failures-confirm")).toBeNull(),
    );
    await userEvent.click(screen.getByTestId("audit-failure-group-toggle-posting_extract"));
    await userEvent.click(screen.getByTestId("audit-failure-row-link-fail-1"));
    await screen.findByTestId("audit-failure-drawer");
    await userEvent.click(screen.getByTestId("audit-failure-drawer-requeue"));
    await waitFor(() =>
      expect(requeueAuditJobs).toHaveBeenCalledWith(
        expect.objectContaining({ job_ids: ["fail-1"], confirm: true }),
      ),
    );
    expect(await screen.findByTestId("audit-failures-row-outcome")).toBeTruthy();
  });

  it("shows the requeue action on the jobs tab linked into failures pre-filtered", async () => {
    renderPage("/settings/audit?tab=jobs");
    expect(await screen.findByTestId("audit-jobs-tab")).toBeTruthy();
    const link = await screen.findByTestId("audit-jobs-failed-link");
    expect(link.getAttribute("href")).toBe("/settings/audit?tab=failures&window=7d");
    await userEvent.selectOptions(screen.getByTestId("audit-jobs-type"), "posting_sync");
    await waitFor(() =>
      expect(link.getAttribute("href")).toBe(
        "/settings/audit?tab=failures&window=7d&job_type=posting_sync",
      ),
    );
  });

  it("links the AI activity tab into the failures view pre-filtered by the badge window", async () => {
    renderPage("/settings/audit?tab=ai");
    const link = await screen.findByTestId("audit-ai-failed-link");
    expect(link.getAttribute("href")).toBe("/settings/audit?tab=failures&window=24h");
    expect(link.textContent).toContain("failed AI call");
  });

  it("renders the failure drawer full-screen below sm per the library contract", async () => {
    vi.mocked(fetchAuditJobs).mockResolvedValue({
      total: 1,
      items: FAILED_GROUP_JOBS,
    });
    renderPage("/settings/audit?tab=failures");
    await screen.findByTestId("audit-failures-tab");
    await userEvent.click(screen.getByTestId("audit-failure-group-toggle-posting_extract"));
    await userEvent.click(screen.getByTestId("audit-failure-row-link-fail-1"));
    await screen.findByTestId("audit-failure-drawer");
    const overlay = screen
      .getByTestId("audit-failure-drawer")
      .closest('div[class*="inset-0"]');
    expect(overlay).not.toBeNull();
    expect(overlay?.className).toContain("fixed inset-0");
    expect(overlay?.className).toContain("sm:inset-0");
    expect(overlay?.className).toContain("sm:max-h-[90vh]");
  });
});
