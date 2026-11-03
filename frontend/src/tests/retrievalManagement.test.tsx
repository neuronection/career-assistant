import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import * as retrievalApi from "@/api/retrieval";
import type {
  RetrievalActionResponse,
  RetrievalCoverage,
  RetrievalHealth,
  RetrievalOverview,
  RetrievalQuality,
  RetrievalRun,
  RetrievalRunsResponse,
  RetrievalSpace,
  RetrievalSpacesResponse,
} from "@/api/retrieval";
import { RetrievalManagementSection } from "@/components/settings/RetrievalManagementSection";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      let out = key;
      for (const [name, value] of Object.entries(params ?? {})) {
        out = out.split(`{{${name}}}`).join(String(value));
      }
      return out;
    },
    i18n: { language: "en" },
  }),
}));

vi.mock("@/api/retrieval", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/retrieval")>();
  return {
    ...actual,
    fetchRetrievalSpaces: vi.fn(),
    fetchRetrievalHealth: vi.fn(),
    fetchRetrievalOverview: vi.fn(),
    fetchRetrievalCoverage: vi.fn(),
    fetchRetrievalQuality: vi.fn(),
    fetchRetrievalRuns: vi.fn(),
    reindexRetrievalSpace: vi.fn(),
    cancelRetrievalRun: vi.fn(),
    retryRetrievalRun: vi.fn(),
    buildRetrievalSpace: vi.fn(),
    activateRetrievalSpace: vi.fn(),
    retireRetrievalSpace: vi.fn(),
    dropRetrievalSpace: vi.fn(),
    runRetrievalMaintenance: vi.fn(),
    compareRetrievalQuality: vi.fn(),
  };
});

function space(overrides: Partial<RetrievalSpace> = {}): RetrievalSpace {
  return {
    space_id: "sp-active",
    name: "content",
    status: "active",
    provider: "openai",
    model: "text-embedding-3-small",
    dim: 1536,
    backend: "pgvector",
    metric: "cosine",
    index_table: "vector_content",
    documents: 12,
    records: 60,
    coverage: 0.998,
    stale: 0,
    failed: 0,
    created_at: "2026-10-01T10:00:00Z",
    activated_at: "2026-10-02T10:00:00Z",
    retired_at: null,
    last_reindex_at: "2026-11-03T10:00:00Z",
    last_error: null,
    gate: "pass",
    as_of: "2026-11-03T10:00:00Z",
    ...overrides,
  };
}

function spacesResponse(): RetrievalSpacesResponse {
  return {
    state: "ok",
    count: 3,
    spaces: [
      space(),
      space({
        space_id: "sp-build",
        name: "candidate",
        status: "building",
        model: "text-embedding-3-large",
        gate: "unknown",
        coverage: null,
        as_of: null,
        activated_at: null,
      }),
      space({
        space_id: "sp-retired",
        name: "old-space",
        status: "retired",
        model: "old-model",
        dim: 768,
        gate: "unknown",
        coverage: null,
        activated_at: "2026-09-01T10:00:00Z",
        retired_at: "2026-10-20T10:00:00Z",
      }),
    ],
    backend: {
      name: "pgvector",
      label: "PostgreSQL pgvector/HNSW",
      dialect: "postgresql",
      semantic_available: true,
    },
  };
}

function healthResponse(): RetrievalHealth {
  return {
    ok: true,
    dialect: "postgresql",
    backend: "pgvector",
    semantic_available: true,
    extension: { version: "0.8" },
    capabilities: {
      ann: true,
      max_dim: 3072,
      max_recommended_rows: 5_000_000,
      scope_enforcement: "sql",
    },
    spaces: [
      {
        space_id: "sp-active",
        name: "content",
        status: "active",
        backend: "pgvector",
        index_table: "vector_content",
        differs_from_process_backend: false,
        ok: true,
        detail: "healthy",
      },
    ],
    detail: "1 space(s)",
  };
}

function overviewResponse(): RetrievalOverview {
  return {
    state: "ok",
    window: { preset: "24h", start: "2026-11-03T00:00:00Z", end: "2026-11-03T12:00:00Z" },
    spaces: { total: 3, active: 1, building: 1, retired: 1 },
    backend: {
      name: "pgvector",
      label: "PostgreSQL pgvector/HNSW",
      dialect: "postgresql",
      semantic_available: true,
    },
    documents: 12,
    records: 60,
    coverage: {
      state: "snapshot",
      coverage: 0.998,
      total: 12,
      embedded: 12,
      stale: 0,
      failed: 0,
      as_of: "2026-11-03T10:00:00Z",
      ann_sampled: true,
    },
    queries: {
      count: 20,
      p50_ms: 10,
      p95_ms: 20,
      zero_result_rate: 0,
      degraded_rate: 0,
      ann_sampled: true,
      latency_percentiles: "histogram_bucket_upper_bound",
    },
    embed: { calls: 12, errors: 0, tokens_in: 1000, tokens_out: 0 },
    runs: {
      total: 1,
      active: 1,
      unattributed: 0,
      scan_truncated: false,
      last_reindex_at: "2026-11-03T10:00:00Z",
      last_status: "running",
    },
    changes: { state: "empty", reason: "audit_emitter_pending", count: 0, recent: [] },
    window_end: "2026-11-03T12:00:00Z",
  };
}

function coverageResponse(): RetrievalCoverage {
  return {
    state: "ok",
    space_id: "sp-active",
    name: "content",
    coverage: {
      space_id: "sp-active",
      as_of: "2026-11-03T10:00:00Z",
      total: 12,
      missing: 0,
      stale: 0,
      failed: 0,
      embedded: 12,
      coverage: 0.998,
      gate: "pass",
      ann_recall: 0.99,
      ann_recall_k: 10,
      probe_size: 100,
    },
    kinds: [],
    document_kinds: ["posting"],
    missing_kinds: [],
    ann_sampled: true,
    as_of: "2026-11-03T10:00:00Z",
  };
}

function qualityResponse(overrides: Partial<RetrievalQuality> = {}): RetrievalQuality {
  return {
    state: "not_sampled",
    space_id: "sp-active",
    name: "content",
    sampled: false,
    set: {
      space_id: "sp-active",
      set_version: 1,
      k: 5,
      floor_recall: 0.8,
      floor_precision: 0.5,
      query_count: 3,
      query_ids: ["q1", "q2", "q3"],
      revision_key: "rev-1",
    },
    quality: null,
    window: { preset: "24h", start: "2026-11-03T00:00:00Z", end: "2026-11-03T12:00:00Z" },
    ...overrides,
  };
}

function run(overrides: Partial<RetrievalRun> = {}): RetrievalRun {
  return {
    run_id: "run-queued-1",
    space_id: "sp-active",
    job_type: "VECTOR_REINDEX",
    status: "queued",
    progress: 0,
    stage: "queued",
    scope: { kind: "posting", view: "summary", since: null },
    budget_tokens: 2000,
    created_at: "2026-11-03T10:00:00Z",
    started_at: null,
    finished_at: null,
    heartbeat_at: null,
    error: null,
    cancel_requested: false,
    idempotency_key: "key-1",
    lock_key: "vector_space:1",
    ...overrides,
  };
}

function runsResponse(): RetrievalRunsResponse {
  return {
    state: "ok",
    window: { preset: "7d", start: "2026-10-27T00:00:00Z", end: "2026-11-03T12:00:00Z" },
    total: 1,
    limit: 6,
    offset: 0,
    unattributed_runs: 0,
    scan_truncated: false,
    runs: [run()],
  };
}

function actionResponse(
  overrides: Partial<RetrievalActionResponse> = {},
): RetrievalActionResponse {
  return {
    action: "reindex",
    accepted: true,
    audit_event: "vector.reindex.started",
    http_status: 202,
    deduplicated: false,
    run_id: "run-new",
    status: "queued",
    idempotency_key: "key-new",
    message: "reindex queued",
    ...overrides,
  };
}

function structuredRefusal(): Error {
  return Object.assign(new Error("activation refused"), {
    isAxiosError: true,
    response: {
      status: 409,
      data: {
        action: "activate_space",
        accepted: false,
        audit_event: "vector.gate.failed",
        http_status: 409,
        deduplicated: false,
        run_id: "run-gate",
        status: "failed",
        idempotency_key: "key-gate",
        message: "activation refused: coverage and quality must both pass",
        activation_gate: {
          space_id: "sp-build",
          coverage: "pass",
          quality: "fail",
          allowed: false,
          reasons: ["quality_below_floor", "quality_no_golden_set"],
        },
      },
    },
  });
}

function renderSection() {
  return render(
    <MemoryRouter>
      <RetrievalManagementSection />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(retrievalApi.fetchRetrievalSpaces).mockResolvedValue(spacesResponse());
  vi.mocked(retrievalApi.fetchRetrievalHealth).mockResolvedValue(healthResponse());
  vi.mocked(retrievalApi.fetchRetrievalOverview).mockResolvedValue(overviewResponse());
  vi.mocked(retrievalApi.fetchRetrievalCoverage).mockResolvedValue(coverageResponse());
  vi.mocked(retrievalApi.fetchRetrievalQuality).mockResolvedValue(qualityResponse());
  vi.mocked(retrievalApi.fetchRetrievalRuns).mockResolvedValue(runsResponse());
  vi.mocked(retrievalApi.reindexRetrievalSpace).mockResolvedValue(actionResponse());
  vi.mocked(retrievalApi.cancelRetrievalRun).mockResolvedValue(
    actionResponse({ action: "cancel_run", message: "cancellation requested" }),
  );
  vi.mocked(retrievalApi.retryRetrievalRun).mockResolvedValue(
    actionResponse({ action: "retry_run", message: "retry queued" }),
  );
  vi.mocked(retrievalApi.buildRetrievalSpace).mockResolvedValue(
    actionResponse({ action: "build_space", message: "building space provisioned", status: "succeeded" }),
  );
  vi.mocked(retrievalApi.activateRetrievalSpace).mockResolvedValue(
    actionResponse({ action: "activate_space", message: "space activated", status: "succeeded" }),
  );
  vi.mocked(retrievalApi.retireRetrievalSpace).mockResolvedValue(
    actionResponse({ action: "retire_space", message: "space retired", status: "succeeded" }),
  );
  vi.mocked(retrievalApi.dropRetrievalSpace).mockResolvedValue(
    actionResponse({ action: "drop_space", message: "space dropped", status: "succeeded" }),
  );
  vi.mocked(retrievalApi.runRetrievalMaintenance).mockResolvedValue(
    actionResponse({ action: "maintenance", message: "maintenance queued" }),
  );
  vi.mocked(retrievalApi.compareRetrievalQuality).mockResolvedValue(
    actionResponse({
      action: "quality_compare",
      message: "quality compare complete",
      status: "succeeded",
      quality: {
        old_space_id: "sp-active",
        new_space_id: "sp-build",
        set_version: 1,
        k: 5,
        old_recall_at_k: 0.9,
        old_precision_at_k: 0.8,
        new_recall_at_k: 0.95,
        new_precision_at_k: 0.85,
        passed: true,
        floor_recall: 0.8,
        floor_precision: 0.5,
        required_for_activation: true,
        queries: [],
        generated_at: "2026-11-03T12:00:00Z",
      },
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RetrievalManagementSection", () => {
  it("renders the active space, backend label, spaces and the Audit handoff", async () => {
    renderSection();
    expect(await screen.findByTestId("retrieval-active-space")).toBeTruthy();
    expect(screen.getByTestId("retrieval-active-backend").textContent).toContain(
      "PostgreSQL pgvector/HNSW",
    );
    expect(screen.getByTestId("retrieval-active-model").textContent).toContain(
      "text-embedding-3-small",
    );
    expect(screen.getByTestId("retrieval-audit-link").getAttribute("href")).toBe(
      "/settings/audit?tab=retrieval&section=overview",
    );
    expect(screen.getByTestId("retrieval-spaces-table")).toBeTruthy();
    expect(screen.getByTestId("retrieval-space-content")).toBeTruthy();
    expect(screen.getByTestId("retrieval-space-candidate")).toBeTruthy();
    expect(screen.getByTestId("retrieval-space-old-space")).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByTestId("retrieval-quality-state").textContent).toContain(
        "retrieval.state.not_sampled",
      ),
    );
  });

  it("queues a reindex with the scope controls and says it is not finished", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByTestId("retrieval-active-space");

    await user.selectOptions(screen.getByTestId("retrieval-reindex-kind"), "posting");
    await user.selectOptions(screen.getByTestId("retrieval-reindex-view"), "summary");
    await user.type(screen.getByTestId("retrieval-reindex-since"), "2026-11-01T00:00:00Z");
    await user.click(screen.getByTestId("retrieval-reindex-submit"));

    await waitFor(() =>
      expect(retrievalApi.reindexRetrievalSpace).toHaveBeenCalledWith(
        expect.objectContaining({
          space: "sp-active",
          kind: "posting",
          view: "summary",
          since: "2026-11-01T00:00:00Z",
          budget: 2000,
          limit: 200,
          force: false,
        }),
      ),
    );
    expect((await screen.findByTestId("retrieval-notice-reindex")).textContent).toContain(
      "reindex queued",
    );
    expect(screen.getByTestId("retrieval-queued-run")).toBeTruthy();
    expect(screen.getByTestId("retrieval-notice-reindex").textContent).toContain(
      "retrieval.action.notFinished",
    );
  });

  it("builds a space with the provider/model/dimension payload", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByTestId("retrieval-active-space");

    await user.click(screen.getByTestId("retrieval-build-toggle"));
    await user.type(screen.getByTestId("retrieval-build-name"), "candidate-2");
    await user.type(screen.getByTestId("retrieval-build-provider"), "openai");
    await user.type(screen.getByTestId("retrieval-build-model"), "text-embedding-3-large");
    await user.click(screen.getByTestId("retrieval-build-submit"));

    await waitFor(() =>
      expect(retrievalApi.buildRetrievalSpace).toHaveBeenCalledWith({
        name: "candidate-2",
        provider: "openai",
        model: "text-embedding-3-large",
        dim: 1536,
        query_prefix: undefined,
        document_prefix: undefined,
      }),
    );
  });

  it("activates a building space", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByTestId("retrieval-active-space");
    await user.click(screen.getByTestId("retrieval-activate-candidate"));
    await waitFor(() =>
      expect(retrievalApi.activateRetrievalSpace).toHaveBeenCalledWith("sp-build"),
    );
  });

  it("surfaces a structured 409 activation refusal with the gate reasons", async () => {
    const user = userEvent.setup();
    vi.mocked(retrievalApi.activateRetrievalSpace).mockRejectedValueOnce(structuredRefusal());
    renderSection();
    await screen.findByTestId("retrieval-active-space");
    await user.click(screen.getByTestId("retrieval-activate-candidate"));

    const notice = await screen.findByTestId("retrieval-notice-spaces");
    expect(notice.textContent).toContain("activation refused");
    expect(screen.getByTestId("retrieval-gate-refusal").textContent).toContain(
      "quality_below_floor",
    );
  });

  it("requires the typed space name before retiring", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByTestId("retrieval-active-space");
    await user.click(screen.getByTestId("retrieval-retire-candidate"));

    const submit = await screen.findByTestId("retrieval-typed-confirm-submit");
    expect(submit).toBeDisabled();
    await user.type(screen.getByTestId("retrieval-typed-confirm"), "candidate");
    expect(submit).not.toBeDisabled();
    await user.click(submit);
    await waitFor(() =>
      expect(retrievalApi.retireRetrievalSpace).toHaveBeenCalledWith("sp-build", "candidate"),
    );
  });

  it("drops a retired space only after the typed name matches", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByTestId("retrieval-active-space");
    await user.click(screen.getByTestId("retrieval-danger-drop-old-space"));

    const submit = await screen.findByTestId("retrieval-typed-confirm-submit");
    expect(submit).toBeDisabled();
    await user.type(screen.getByTestId("retrieval-typed-confirm"), "wrong");
    expect(submit).toBeDisabled();
    await user.clear(screen.getByTestId("retrieval-typed-confirm"));
    await user.type(screen.getByTestId("retrieval-typed-confirm"), "old-space");
    await user.click(submit);
    await waitFor(() =>
      expect(retrievalApi.dropRetrievalSpace).toHaveBeenCalledWith("sp-retired", "old-space"),
    );
  });

  it("queues maintenance with the action and dry-run flag", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByTestId("retrieval-active-space");
    await user.selectOptions(screen.getByTestId("retrieval-maintenance-action"), "vacuum");
    await user.click(screen.getByRole("switch", { name: "retrieval.field.dryRun" }));
    await user.click(screen.getByTestId("retrieval-maintenance-submit"));
    await waitFor(() =>
      expect(retrievalApi.runRetrievalMaintenance).toHaveBeenCalledWith(
        expect.objectContaining({
          space: "sp-active",
          action: "vacuum",
          dry_run: true,
        }),
      ),
    );
  });

  it("runs the golden-query compare on candidate vs baseline", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByTestId("retrieval-active-space");
    await user.click(screen.getByTestId("retrieval-quality-submit"));
    await waitFor(() =>
      expect(retrievalApi.compareRetrievalQuality).toHaveBeenCalledWith({
        space: "sp-build",
        compare_space: "sp-active",
      }),
    );
    expect((await screen.findByTestId("retrieval-quality-compare")).textContent).toContain(
      "95.0%",
    );
  });

  it("exports aggregate status JSON without raw text", async () => {
    const user = userEvent.setup();
    const createObjectURL = vi.fn((_blob: Blob) => "blob:retrieval");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    renderSection();
    await screen.findByTestId("retrieval-active-space");
    await user.click(screen.getByTestId("retrieval-export"));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
    const blob = createObjectURL.mock.calls[0][0];
    const text = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(blob);
    });
    expect(text).toContain('"spaces"');
    expect(text).not.toContain("document_text");
    expect(text).not.toContain("query_text");
    expect(text).not.toContain("prompt");
    expect(screen.getByTestId("retrieval-notice-danger").textContent).toContain(
      "retrieval.action.exported",
    );
    click.mockRestore();
  });

  it("renders a queued run and offers cancel without implying completion", async () => {
    renderSection();
    await screen.findByTestId("retrieval-active-space");
    const row = await screen.findByTestId("retrieval-run-run-queued-1");
    expect(within(row).getByText("retrieval.status.queued")).toBeTruthy();
    expect(within(row).getByTestId("retrieval-cancel-run-queued-1")).toBeTruthy();
  });
});
