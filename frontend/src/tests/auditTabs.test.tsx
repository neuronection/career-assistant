import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";

import {
  AUDIT_TABS,
  Audit,
  parseAuditTab,
  parseAuditWindow,
} from "@/pages/settings/Audit";
import {
  AUDIT_CATEGORIES,
  categoryRollup,
  formatTokens,
  formatTokensExact,
} from "@/config/auditVocab";
import type {
  AuditChangeRow,
  AuditEventRow,
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
}));

import {
  exportAuditCsv,
  fetchAuditBreakdown,
  fetchAuditChanges,
  fetchAuditEvents,
  fetchAuditGenerations,
  fetchAuditJobFacets,
  fetchAuditJobs,
  fetchAuditOverview,
  fetchAuditProduction,
  fetchAuditSourceRuns,
  fetchAuditTimeseries,
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
  it("AUDIT_TABS is overview-first", () => {
    expect([...AUDIT_TABS]).toEqual([
      "overview",
      "ai",
      "usage",
      "security",
      "jobs",
      "changes",
    ]);
  });

  it("parseAuditTab falls back to overview on unknown values", () => {
    expect(parseAuditTab(null)).toBe("overview");
    expect(parseAuditTab("security")).toBe("security");
    expect(parseAuditTab("bogus")).toBe("overview");
  });

  it("parseAuditWindow only accepts presets", () => {
    expect(parseAuditWindow(null)).toBe("24h");
    expect(parseAuditWindow("7d")).toBe("7d");
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
    vi.mocked(fetchAuditGenerations).mockResolvedValue({
      total: 2,
      items: GENERATIONS,
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
  });

  it("canonicalizes an unknown tab param", async () => {
    renderPage("/settings/audit?tab=bogus");
    await screen.findByTestId("audit-kpis");
    await waitFor(() => expect(probe()).toBe("/settings/audit"));
  });

  it("lands the AI tab deep link, marks mock rows simulated and expands detail", async () => {
    renderPage("/settings/audit?tab=ai");
    expect(await screen.findByTestId("audit-ai-tab")).toBeTruthy();
    expect(screen.getByTestId("audit-gen-simulated-gen-mock")).toBeTruthy();
    expect(screen.queryByTestId("audit-gen-detail-gen-ok")).toBeNull();

    const tokensCell = screen.getByTitle("5,329 → 356");
    expect(tokensCell.textContent).toBe("5.3k → 356");
    const mockRow = screen.getByTestId("audit-gen-row-gen-mock");
    expect(mockRow.textContent).toContain("—");
    expect(mockRow.textContent).not.toContain("?");

    await userEvent.click(screen.getByTestId("audit-gen-row-gen-ok"));
    expect(screen.getByTestId("audit-gen-detail-gen-ok")).toBeTruthy();
    expect(screen.getByText(/run #11111111/)).toBeTruthy();
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
});
