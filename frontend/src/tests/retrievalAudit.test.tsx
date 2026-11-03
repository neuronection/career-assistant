import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";

import { Audit } from "@/pages/settings/Audit";
import type {
  RetrievalFailuresResponse,
  RetrievalOverview,
  RetrievalQuality,
  RetrievalQualityQueryResult,
  RetrievalQueryHealthResponse,
  RetrievalRunDetailResponse,
  RetrievalRunsResponse,
  RetrievalSpacesResponse,
  RetrievalUsageResponse,
} from "@/api/retrieval";
import type { AuditEventRow } from "@/api/audit";

const RAW_QUERY_SENTINEL = "RAW QUERY TEXT MUST NOT RENDER";
const RAW_DOCUMENT_SENTINEL = "RAW DOCUMENT TEXT MUST NOT RENDER";

vi.mock("@/api/retrieval", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/retrieval")>();
  return {
    ...actual,
    fetchRetrievalOverview: vi.fn(),
    fetchRetrievalSpaces: vi.fn(),
    fetchRetrievalHealth: vi.fn(),
    fetchRetrievalCoverage: vi.fn(),
    fetchRetrievalQuality: vi.fn(),
    fetchRetrievalRuns: vi.fn(),
    fetchRetrievalRun: vi.fn(),
    fetchRetrievalQueryHealth: vi.fn(),
    fetchRetrievalFailures: vi.fn(),
    fetchRetrievalUsage: vi.fn(),
  };
});

vi.mock("@/api/audit", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/audit")>();
  return {
    ...actual,
    fetchAuditEvents: vi.fn(),
  };
});

import {
  fetchRetrievalCoverage,
  fetchRetrievalFailures,
  fetchRetrievalHealth,
  fetchRetrievalOverview,
  fetchRetrievalQuality,
  fetchRetrievalQueryHealth,
  fetchRetrievalRun,
  fetchRetrievalRuns,
  fetchRetrievalSpaces,
  fetchRetrievalUsage,
} from "@/api/retrieval";
import { fetchAuditEvents } from "@/api/audit";

const BACKEND = {
  name: "pgvector",
  label: "PostgreSQL pgvector/HNSW",
  dialect: "postgresql",
  semantic_available: true,
};

const SPACES: RetrievalSpacesResponse = {
  state: "ok",
  count: 2,
  backend: BACKEND,
  spaces: [
    {
      space_id: "space-active",
      name: "content",
      status: "active",
      provider: "openai",
      model: "text-embedding-3-small",
      dim: 1536,
      backend: "pgvector",
      metric: "cosine",
      index_table: "vector_records_idx",
      documents: 120,
      records: 340,
      coverage: 0.997,
      stale: 1,
      failed: 0,
      created_at: "2026-11-01T10:00:00Z",
      activated_at: "2026-11-01T11:00:00Z",
      retired_at: null,
      last_reindex_at: "2026-11-03T08:00:00Z",
      last_error: null,
      gate: "pass",
      as_of: "2026-11-03T08:00:00Z",
    },
    {
      space_id: "space-build",
      name: "content-v2",
      status: "building",
      provider: "openai",
      model: "text-embedding-3-large",
      dim: 3072,
      backend: "pgvector",
      metric: "cosine",
      index_table: "vector_records_v2_idx",
      documents: 40,
      records: 80,
      coverage: null,
      stale: null,
      failed: null,
      created_at: "2026-11-03T09:00:00Z",
      activated_at: null,
      retired_at: null,
      last_reindex_at: null,
      last_error: null,
      gate: "unknown",
      as_of: null,
    },
  ],
};

const OVERVIEW: RetrievalOverview = {
  state: "ok",
  window: { preset: "24h", start: "2026-11-02T00:00:00Z", end: "2026-11-03T00:00:00Z" },
  spaces: { total: 2, active: 1, building: 1, retired: 0 },
  backend: BACKEND,
  documents: 120,
  records: 340,
  coverage: {
    state: "snapshot",
    coverage: 0.997,
    total: 120,
    embedded: 120,
    stale: 1,
    failed: 0,
    as_of: "2026-11-03T08:00:00Z",
    ann_sampled: true,
  },
  queries: {
    count: 12,
    p50_ms: 40,
    p95_ms: 180,
    zero_result_rate: 0.08,
    degraded_rate: 0.1,
    ann_sampled: true,
    latency_percentiles: "histogram_bucket_upper_bound",
  },
  embed: { calls: 24, errors: 1, tokens_in: 1200, tokens_out: 0 },
  runs: {
    total: 3,
    active: 1,
    unattributed: 0,
    scan_truncated: false,
    last_reindex_at: "2026-11-03T08:00:00Z",
    last_status: "succeeded",
  },
  changes: {
    state: "ok",
    reason: null,
    count: 4,
    recent: [
      {
        action: "vector.reindex.started",
        actor: "11111111-1111-1111-1111-111111111111",
        resource: "space:space-active",
        outcome: "ok",
        created_at: "2026-11-03T08:00:00Z",
      },
    ],
  },
  window_end: "2026-11-03T00:00:00Z",
};

const RUNS: RetrievalRunsResponse = {
  state: "ok",
  window: { preset: "24h", start: "2026-11-02T00:00:00Z", end: "2026-11-03T00:00:00Z" },
  total: 1,
  limit: 50,
  offset: 0,
  unattributed_runs: 1,
  scan_truncated: true,
  runs: [
    {
      run_id: "run-1",
      space_id: "space-active",
      job_type: "VECTOR_REINDEX",
      status: "failed",
      progress: 40,
      stage: "embedding",
      scope: { kind: "posting", view: "summary", since: null },
      budget_tokens: 2000,
      created_at: "2026-11-03T07:00:00Z",
      started_at: "2026-11-03T07:01:00Z",
      finished_at: "2026-11-03T07:05:00Z",
      heartbeat_at: "2026-11-03T07:04:00Z",
      error: "provider timeout",
      cancel_requested: false,
      idempotency_key: "idem-run-1",
      lock_key: "vector_space:space-active",
    },
  ],
};

const RUN_DETAIL: RetrievalRunDetailResponse = {
  state: "ok",
  result_state: "ok",
  failed_ids_limit: 500,
  detail: {
    run: RUNS.runs[0],
    duration_seconds: 240,
    result: {
      scanned: 50,
      embedded: 40,
      skipped: 6,
      failed: 4,
      failed_ids: ["doc-1", "doc-2"],
      failed_ids_truncated: true,
      gate: "fail",
    },
  },
};

const HEALTH = {
  ok: true,
  dialect: "postgresql",
  backend: "pgvector",
  semantic_available: true,
  extension: { version: "0.7.0" },
  capabilities: {
    ann: true,
    max_dim: 3072,
    max_recommended_rows: 1000000,
    scope_enforcement: "sql",
  },
  spaces: [
    {
      space_id: "space-active",
      name: "content",
      status: "active" as const,
      backend: "pgvector",
      index_table: "vector_records_idx",
      differs_from_process_backend: false,
      ok: true,
      detail: "ready",
    },
  ],
  detail: "ready",
};

const COVERAGE = {
  state: "ok" as const,
  space_id: "space-active",
  name: "content",
  coverage: {
    space_id: "space-active",
    as_of: "2026-11-03T08:00:00Z",
    total: 120,
    missing: 0,
    stale: 1,
    failed: 0,
    embedded: 120,
    coverage: 0.997,
    gate: "pass" as const,
    ann_recall: 0.98,
    ann_recall_k: 5,
    probe_size: 20,
  },
  kinds: [
    {
      kind: "posting",
      coverage: {
        space_id: "space-active",
        as_of: "2026-11-03T08:00:00Z",
        total: 120,
        missing: 0,
        stale: 1,
        failed: 0,
        embedded: 120,
        coverage: 0.997,
        gate: "pass" as const,
        ann_recall: 0.98,
        ann_recall_k: 5,
        probe_size: 20,
      },
    },
  ],
  document_kinds: ["posting"],
  missing_kinds: [],
  ann_sampled: true,
  as_of: "2026-11-03T08:00:00Z",
};

const QUALITY: RetrievalQuality = {
  state: "sampled",
  space_id: "space-build",
  name: "content-v2",
  sampled: true,
  set: {
    space_id: "space-build",
    set_version: 3,
    k: 5,
    floor_recall: 0.8,
    floor_precision: 0.5,
    query_count: 1,
    query_ids: ["gq-1"],
    revision_key: "rev-3",
  },
  quality: {
    space_id: "space-build",
    set_version: 3,
    k: 5,
    recall_at_k: 0.5,
    precision_at_k: 0.5,
    passed: false,
    queries: [
      {
        query_id: "gq-1",
        expected_document_ids: ["doc-a", "doc-b"],
        retrieved_document_ids: ["doc-a", "doc-c"],
        recall_at_k: 0.5,
        precision_at_k: 0.5,
        missing_document_ids: ["doc-b"],
        passed: false,
        // Simulates an accidental raw-text leak from an upstream payload.
        raw_query: RAW_QUERY_SENTINEL,
        raw_document: RAW_DOCUMENT_SENTINEL,
      } as unknown as RetrievalQualityQueryResult,
    ],
    floor_recall: 0.8,
    floor_precision: 0.5,
    generated_at: "2026-11-03T09:00:00Z",
  },
  compare: {
    old_space_id: "space-active",
    new_space_id: "space-build",
    set_version: 3,
    k: 5,
    old_recall_at_k: 0.9,
    old_precision_at_k: 0.7,
    new_recall_at_k: 0.5,
    new_precision_at_k: 0.5,
    passed: false,
    floor_recall: 0.8,
    floor_precision: 0.5,
    required_for_activation: true,
    queries: [
      {
        query_id: "gq-1",
        expected_document_ids: ["doc-a", "doc-b"],
        retrieved_document_ids: ["doc-a", "doc-c"],
        recall_at_k: 0.5,
        precision_at_k: 0.5,
        missing_document_ids: ["doc-b"],
        passed: false,
        raw_query: RAW_QUERY_SENTINEL,
        raw_document: RAW_DOCUMENT_SENTINEL,
      } as unknown as RetrievalQualityQueryResult,
    ],
    generated_at: "2026-11-03T09:00:00Z",
  },
  activation_gate: "fail",
  compare_run_id: "run-1",
  compare_set_version: 3,
  window: { preset: "24h", start: "2026-11-02T00:00:00Z", end: "2026-11-03T00:00:00Z" },
};

const QUERY_HEALTH: RetrievalQueryHealthResponse = {
  state: "ok",
  window: { preset: "24h", start: "2026-11-02T00:00:00Z", end: "2026-11-03T00:00:00Z" },
  candidates_avg: 12.5,
  candidate_percentiles: "unavailable",
  latency_percentiles: "histogram_bucket_upper_bound",
  query_health: {
    space_id: "space-active",
    window_start: "2026-11-02T00:00:00Z",
    window_end: "2026-11-03T00:00:00Z",
    p50_ms: 40,
    p95_ms: 180,
    candidate_p50: null,
    candidate_p95: null,
    zero_result_rate: 0.08,
    degraded_rate: 0.1,
    degraded_reasons: { embed_failed: 2 },
    per_view_hits: { summary: 10 },
    ann_recall: 0.98,
    ann_recall_k: 5,
    probe_size: 20,
    sampled: true,
    sample_size: 12,
    query_count: 12,
  },
};

const FAILURES: RetrievalFailuresResponse = {
  state: "ok",
  window: { preset: "24h", start: "2026-11-02T00:00:00Z", end: "2026-11-03T00:00:00Z" },
  truncated: true,
  groups: [
    {
      kind: "indexing",
      space_id: "space-active",
      count: 3,
      last_seen: "2026-11-03T07:05:00Z",
      document_ids: ["doc-1", "doc-2"],
      reason: "embed_failed",
      retryable: true,
      run_id: "run-1",
    },
  ],
};

const USAGE: RetrievalUsageResponse = {
  state: "ok",
  window: { preset: "24h", start: "2026-11-02T00:00:00Z", end: "2026-11-03T00:00:00Z" },
  untagged_calls: 2,
  groups_truncated: false,
  units: "tokens/calls",
  budget: { name: "embed budget", exhausted: false },
  usage: {
    window_start: "2026-11-02T00:00:00Z",
    window_end: "2026-11-03T00:00:00Z",
    rows: [
      {
        day: "2026-11-02",
        space_id: "space-active",
        kind: "posting",
        calls: 10,
        tokens_in: 1000,
        tokens_out: 0,
        reindex_calls: 2,
      },
      {
        day: "2026-11-03",
        space_id: "space-active",
        kind: "job",
        calls: 4,
        tokens_in: 400,
        tokens_out: 0,
        reindex_calls: 0,
      },
    ],
    budget: { window: "day", max_tokens: 5000, used_tokens: 1400 },
  },
};

const EVENTS: AuditEventRow[] = [
  {
    id: "evt-1",
    action: "vector.reindex.started",
    actor: "11111111-1111-1111-1111-111111111111",
    actor_email: "admin@example.com",
    resource: "space:space-active;kind=posting",
    outcome: "ok",
    created_at: "2026-11-03T08:00:00Z",
  },
  {
    id: "evt-2",
    action: "vector.run.stalled",
    actor: "11111111-1111-1111-1111-111111111111",
    actor_email: null,
    resource: "run:run-1;space=space-active",
    outcome: "error",
    created_at: "2026-11-03T08:05:00Z",
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

describe("audit retrieval tab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchRetrievalOverview).mockResolvedValue(OVERVIEW);
    vi.mocked(fetchRetrievalSpaces).mockResolvedValue(SPACES);
    vi.mocked(fetchRetrievalHealth).mockResolvedValue(HEALTH);
    vi.mocked(fetchRetrievalCoverage).mockResolvedValue(COVERAGE);
    vi.mocked(fetchRetrievalQuality).mockResolvedValue(QUALITY);
    vi.mocked(fetchRetrievalRuns).mockResolvedValue(RUNS);
    vi.mocked(fetchRetrievalRun).mockResolvedValue(RUN_DETAIL);
    vi.mocked(fetchRetrievalQueryHealth).mockResolvedValue(QUERY_HEALTH);
    vi.mocked(fetchRetrievalFailures).mockResolvedValue(FAILURES);
    vi.mocked(fetchRetrievalUsage).mockResolvedValue(USAGE);
    vi.mocked(fetchAuditEvents).mockResolvedValue({ total: 2, items: EVENTS });
  });

  it("renders the overview and canonicalizes the section-less default", async () => {
    renderPage("/settings/audit?tab=retrieval");
    expect(await screen.findByTestId("retrieval-overview")).toBeTruthy();
    expect(fetchRetrievalOverview).toHaveBeenCalledWith("24h");
    expect(screen.getAllByText("PostgreSQL pgvector/HNSW").length).toBeGreaterThan(0);
    expect(screen.getByText("text-embedding-3-small · 1536")).toBeTruthy();
    expect(screen.getByTestId("retrieval-overview-degraded")).toBeTruthy();
    expect(screen.queryByTestId("retrieval-overview-cold")).toBeNull();
    expect(screen.getAllByTestId("retrieval-overview-change").length).toBe(1);
    await waitFor(() => expect(probe()).toBe("/settings/audit?tab=retrieval"));
  });

  it("shows the honest cold/no-query overview state", async () => {
    vi.mocked(fetchRetrievalOverview).mockResolvedValue({
      ...OVERVIEW,
      coverage: {
        ...OVERVIEW.coverage,
        state: "never_reconciled",
        coverage: null,
        total: 0,
        embedded: 0,
        stale: null,
        failed: null,
        as_of: null,
        ann_sampled: false,
      },
      queries: {
        ...OVERVIEW.queries,
        count: 0,
        p50_ms: null,
        p95_ms: null,
        zero_result_rate: null,
        degraded_rate: null,
        latency_percentiles: "not_sampled",
      },
      changes: { state: "empty", reason: "audit_emitter_pending", count: 0, recent: [] },
    });
    renderPage("/settings/audit?tab=retrieval");
    await screen.findByTestId("retrieval-overview");
    expect(screen.getByTestId("retrieval-overview-cold")).toBeTruthy();
    expect(screen.getByTestId("retrieval-overview-no-queries")).toBeTruthy();
    expect(screen.queryByTestId("retrieval-overview-degraded")).toBeNull();
    expect(screen.getAllByText("Never reconciled").length).toBeGreaterThan(0);
  });

  it("syncs the section and 90d window, and lists spaces", async () => {
    renderPage("/settings/audit?tab=retrieval&section=spaces&window=90d");
    expect(await screen.findByTestId("retrieval-spaces")).toBeTruthy();
    expect(screen.getByTestId("audit-page-range")).toHaveValue("90d");
    expect(screen.getByTestId("retrieval-space-row-space-active")).toBeTruthy();
    expect(screen.getByTestId("retrieval-space-row-space-build")).toBeTruthy();
    expect(screen.getByText("Never reconciled")).toBeTruthy();
    expect(probe()).toBe("/settings/audit?tab=retrieval&section=spaces&window=90d");

    await userEvent.click(
      within(screen.getByTestId("audit-retrieval-tab")).getByRole("tab", {
        name: "Runs",
      }),
    );
    await screen.findByTestId("retrieval-runs");
    expect(fetchRetrievalRuns).toHaveBeenLastCalledWith(
      expect.objectContaining({ window: "90d", limit: 50 }),
    );
    await waitFor(() =>
      expect(probe()).toBe("/settings/audit?tab=retrieval&section=runs&window=90d"),
    );
  });

  it("opens a space drawer from ?detail= and closes back to the section", async () => {
    renderPage("/settings/audit?tab=retrieval&section=spaces&detail=space-active");
    expect(await screen.findByTestId("retrieval-space-drawer")).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByTestId("retrieval-space-meta").textContent).toContain(
        "text-embedding-3-small",
      ),
    );
    expect(screen.getByTestId("retrieval-space-coverage").textContent).toContain(
      "99.7%",
    );
    expect(screen.getByTestId("retrieval-space-tools-link")).toHaveAttribute(
      "href",
      "/settings/tools?section=retrieval",
    );
    await userEvent.keyboard("{Escape}");
    await waitFor(() =>
      expect(probe()).toBe("/settings/audit?tab=retrieval&section=spaces"),
    );
  });

  it("filters runs and opens the run drawer with bounded failed ids", async () => {
    renderPage("/settings/audit?tab=retrieval&section=runs");
    expect(await screen.findByTestId("retrieval-run-row-run-1")).toBeTruthy();
    expect(screen.getByTestId("retrieval-runs-unattributed")).toBeTruthy();
    expect(screen.getByTestId("retrieval-runs-scan-truncated")).toBeTruthy();

    await userEvent.selectOptions(
      screen.getByTestId("retrieval-runs-status-filter"),
      "failed",
    );
    await waitFor(() =>
      expect(fetchRetrievalRuns).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "failed", window: "24h" }),
      ),
    );

    await userEvent.click(screen.getByTestId("retrieval-run-row-run-1"));
    expect(await screen.findByTestId("retrieval-run-drawer")).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByTestId("retrieval-run-meta").textContent).toContain(
        "embedding",
      ),
    );
    expect(screen.getByTestId("retrieval-run-result").textContent).toContain(
      "Scanned",
    );
    expect(screen.getByTestId("retrieval-run-failed-ids").textContent).toContain(
      "doc-1",
    );
    expect(screen.getByTestId("retrieval-run-failed-truncated")).toBeTruthy();
    expect(screen.getByTestId("retrieval-run-error").textContent).toContain(
      "provider timeout",
    );
    expect(screen.getByTestId("retrieval-run-tools-link")).toHaveAttribute(
      "href",
      "/settings/tools?section=retrieval",
    );
    expect(probe()).toContain(
      "section=runs&detail=run-1",
    );
  });

  it("renders the quality compare and opens a golden-query drawer without raw text", async () => {
    renderPage("/settings/audit?tab=retrieval&section=quality");
    expect(await screen.findByTestId("retrieval-quality-compare")).toBeTruthy();
    expect(fetchRetrievalQuality).toHaveBeenCalledWith(undefined, "24h");
    expect(screen.getByText("Baseline space-ac")).toBeTruthy();
    expect(screen.queryByTestId("retrieval-quality-stale")).toBeNull();

    await userEvent.click(screen.getByTestId("retrieval-quality-query-row-gq-1"));
    expect(await screen.findByTestId("retrieval-quality-drawer")).toBeTruthy();
    expect(screen.getByTestId("retrieval-quality-expected").textContent).toContain(
      "doc-a",
    );
    expect(screen.getByTestId("retrieval-quality-retrieved").textContent).toContain(
      "doc-c",
    );
    expect(screen.getByTestId("retrieval-quality-missing").textContent).toContain(
      "doc-b",
    );
    const drawerText = screen.getByTestId("retrieval-quality-drawer").textContent ?? "";
    expect(drawerText).not.toContain(RAW_QUERY_SENTINEL);
    expect(drawerText).not.toContain(RAW_DOCUMENT_SENTINEL);
    expect(probe()).toContain("section=quality&detail=gq-1");
  });

  it("renders the no-golden-set and not-sampled quality states", async () => {
    vi.mocked(fetchRetrievalQuality).mockResolvedValueOnce({
      ...QUALITY,
      state: "no_golden_set",
      sampled: false,
      set: null,
      quality: null,
      compare: undefined,
      activation_gate: undefined,
    });
    const first = renderPage("/settings/audit?tab=retrieval&section=quality");
    expect(await screen.findByTestId("retrieval-quality-no-golden")).toBeTruthy();
    first.unmount();

    vi.mocked(fetchRetrievalQuality).mockResolvedValueOnce({
      ...QUALITY,
      state: "not_sampled",
      sampled: false,
      quality: null,
      compare: undefined,
      reason: "compare_not_run",
      activation_gate: undefined,
    });
    renderPage("/settings/audit?tab=retrieval&section=quality");
    expect(await screen.findByTestId("retrieval-quality-not-sampled")).toBeTruthy();
  });

  it("renders query health and opens a structured reason drawer", async () => {
    renderPage("/settings/audit?tab=retrieval&section=query-health&window=90d");
    expect(await screen.findByTestId("retrieval-query-ok")).toBeTruthy();
    expect(fetchRetrievalQueryHealth).toHaveBeenCalledWith({ window: "90d" });
    expect(screen.getByTestId("retrieval-query-tiles").textContent).toContain("40ms");
    expect(screen.getByTestId("retrieval-query-views").textContent).toContain(
      "Summary",
    );

    await userEvent.click(screen.getByTestId("retrieval-query-reason-embed_failed"));
    expect(await screen.findByTestId("retrieval-query-drawer")).toBeTruthy();
    const text = screen.getByTestId("retrieval-query-drawer").textContent ?? "";
    expect(text).toContain("embed_failed");
    expect(text).toContain("16.7%");
    expect(text).not.toContain(RAW_QUERY_SENTINEL);
    expect(probe()).toContain("section=query-health");
    expect(probe()).toContain("detail=embed_failed");
  });

  it("renders query-health empty and never-sampled states", async () => {
    vi.mocked(fetchRetrievalQueryHealth).mockResolvedValueOnce({
      state: "empty",
      reason: "no_space_selected",
      window: QUERY_HEALTH.window,
      query_health: null,
      candidates_avg: null,
      candidate_percentiles: "not_sampled",
      latency_percentiles: "not_sampled",
    });
    const first = renderPage("/settings/audit?tab=retrieval&section=query-health");
    expect(await screen.findByTestId("retrieval-query-empty")).toBeTruthy();
    first.unmount();

    vi.mocked(fetchRetrievalQueryHealth).mockResolvedValueOnce({
      ...QUERY_HEALTH,
      state: "not_sampled",
      query_health: {
        ...QUERY_HEALTH.query_health!,
        sampled: false,
        query_count: 0,
        sample_size: 0,
        p50_ms: null,
        p95_ms: null,
        zero_result_rate: null,
        degraded_rate: null,
        ann_recall: null,
        ann_recall_k: null,
        probe_size: null,
        degraded_reasons: {},
        per_view_hits: {},
      },
    });
    renderPage("/settings/audit?tab=retrieval&section=query-health");
    expect(await screen.findByTestId("retrieval-query-not-sampled")).toBeTruthy();
  });

  it("renders failures and the structured failure drawer", async () => {
    renderPage("/settings/audit?tab=retrieval&section=failures");
    expect(await screen.findByTestId("retrieval-failures")).toBeTruthy();
    expect(screen.getByTestId("retrieval-failures-truncated")).toBeTruthy();
    const group = screen.getByTestId(
      "retrieval-failure-group-indexing:space-active:run-1",
    );
    expect(group.textContent).toContain("Embed failed");
    expect(group.textContent).not.toContain("provider timeout");

    await userEvent.click(group);
    expect(await screen.findByTestId("retrieval-failure-drawer")).toBeTruthy();
    const text = screen.getByTestId("retrieval-failure-drawer").textContent ?? "";
    expect(text).toContain("embed_failed");
    expect(text).toContain("doc-1");
    expect(text).not.toContain(RAW_DOCUMENT_SENTINEL);
    expect(text).not.toContain("provider timeout");
    expect(screen.getByTestId("retrieval-failure-run-link")).toHaveAttribute(
      "href",
      "/settings/audit?tab=retrieval&section=runs&detail=run-1",
    );
    expect(screen.getByTestId("retrieval-failure-retry-link")).toHaveAttribute(
      "href",
      "/settings/tools?section=retrieval",
    );
  });

  it("renders the empty failures state", async () => {
    vi.mocked(fetchRetrievalFailures).mockResolvedValueOnce({
      state: "empty",
      window: FAILURES.window,
      groups: [],
      truncated: false,
    });
    renderPage("/settings/audit?tab=retrieval&section=failures");
    expect(await screen.findByTestId("retrieval-failures-empty")).toBeTruthy();
  });

  it("renders usage by day/space/kind with budget and untagged calls", async () => {
    renderPage("/settings/audit?tab=retrieval&section=usage");
    expect(await screen.findByTestId("retrieval-usage")).toBeTruthy();
    expect(screen.getAllByTestId("retrieval-usage-row").length).toBe(2);
    expect(screen.getByTestId("retrieval-usage-budget").textContent).toContain(
      "1,400 of 5,000 tokens used",
    );
    expect(screen.getByTestId("retrieval-usage-tiles").textContent).toContain(
      "Untagged calls",
    );
    expect(screen.getByTestId("retrieval-usage").textContent).not.toContain("$");
  });

  it("renders the empty usage state", async () => {
    vi.mocked(fetchRetrievalUsage).mockResolvedValueOnce({
      state: "empty",
      window: USAGE.window,
      untagged_calls: 0,
      groups_truncated: false,
      budget: null,
      units: "tokens/calls",
      usage: {
        window_start: USAGE.usage.window_start,
        window_end: USAGE.usage.window_end,
        rows: [],
        budget: null,
      },
    });
    renderPage("/settings/audit?tab=retrieval&section=usage");
    expect(await screen.findByTestId("retrieval-usage-empty")).toBeTruthy();
  });

  it("renders vector audit changes and links run/space resources", async () => {
    renderPage("/settings/audit?tab=retrieval&section=changes");
    expect(await screen.findByTestId("retrieval-changes")).toBeTruthy();
    expect(fetchAuditEvents).toHaveBeenCalledWith(
      expect.objectContaining({ group: "vector", window: "24h", limit: 50, offset: 0 }),
    );
    expect(screen.getAllByTestId(/retrieval-change-row-/).length).toBe(2);
    expect(screen.getByTestId("retrieval-change-link-evt-1")).toHaveAttribute(
      "href",
      "/settings/audit?tab=retrieval&section=spaces&detail=space-active",
    );
    expect(screen.getByTestId("retrieval-change-link-evt-2")).toHaveAttribute(
      "href",
      "/settings/audit?tab=retrieval&section=runs&detail=run-1",
    );
  });

  it("caps the changes window at 30d and says so", async () => {
    renderPage("/settings/audit?tab=retrieval&section=changes&window=90d");
    expect(await screen.findByTestId("retrieval-changes")).toBeTruthy();
    expect(fetchAuditEvents).toHaveBeenCalledWith(
      expect.objectContaining({ group: "vector", window: "30d" }),
    );
    expect(screen.getByText(/capped at 30d/)).toBeTruthy();
  });

  it("keeps the retrieval preference when switching tabs but never sends 90d to audit", async () => {
    renderPage("/settings/audit?tab=retrieval&window=90d");
    await screen.findByTestId("retrieval-overview");
    expect(screen.getByTestId("audit-page-range")).toHaveValue("90d");

    await userEvent.click(screen.getByRole("tab", { name: "Security & access" }));
    await screen.findByTestId("audit-security-tab");
    await waitFor(() =>
      expect(probe()).toBe("/settings/audit?tab=security"),
    );
    expect(screen.getByTestId("audit-page-range")).toHaveValue("24h");
    await waitFor(() =>
      expect(fetchAuditEvents).toHaveBeenLastCalledWith(
        expect.objectContaining({ window: "24h" }),
      ),
    );
  });

  it("drops a detail param that the active section cannot display", async () => {
    renderPage("/settings/audit?tab=retrieval&section=usage&detail=run-1");
    expect(await screen.findByTestId("retrieval-usage")).toBeTruthy();
    await waitFor(() =>
      expect(probe()).toBe("/settings/audit?tab=retrieval&section=usage"),
    );
  });
});
