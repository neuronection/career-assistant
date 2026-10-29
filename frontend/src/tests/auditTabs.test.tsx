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
import { categoryRollup } from "@/config/auditVocab";
import type {
  AuditEventRow,
  AIGenerationRow,
  AuditOverview,
  AuditSeries,
} from "@/api/audit";

vi.mock("@/api/audit", () => ({
  fetchAuditOverview: vi.fn(),
  fetchAuditTimeseries: vi.fn(),
  fetchAuditBreakdown: vi.fn(),
  fetchAuditEvents: vi.fn(),
  fetchAuditGenerations: vi.fn(),
}));

import {
  fetchAuditBreakdown,
  fetchAuditEvents,
  fetchAuditGenerations,
  fetchAuditOverview,
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
    tokens_in: 100,
    tokens_out: 20,
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
    expect([...AUDIT_TABS]).toEqual(["overview", "ai", "security"]);
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
  });

  it("renders the overview KPIs, categories and failure feed", async () => {
    renderPage("/settings/audit");
    expect(await screen.findByTestId("audit-kpis")).toBeTruthy();
    expect(screen.getAllByTestId("stat-tile").length).toBe(6);
    expect(await screen.findByTestId("audit-categories")).toBeTruthy();
    expect(screen.getAllByTestId("audit-category-row").length).toBe(2);
    expect(screen.getAllByTestId("audit-failure-row").length).toBe(2);
    expect(screen.getByText("match_score")).toBeTruthy();
    expect(fetchAuditOverview).toHaveBeenCalledWith("24h");
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
      expect.objectContaining({ group: "all", window: "7d" }),
    );
  });
});
