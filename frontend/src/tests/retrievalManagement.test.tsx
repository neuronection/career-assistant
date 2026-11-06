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
  RetrievalModelProfile,
  RetrievalModelProfilesResponse,
  RetrievalTokenizerReport,
} from "@/api/retrieval";
import { RetrievalManagementSection } from "@/components/settings/RetrievalManagementSection";
import { useRetrievalDebugStore } from "@/stores/retrievalDebugStore";

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
    fetchRetrievalTokenizer: vi.fn(),
    fetchRetrievalModelProfiles: vi.fn(),
    saveRetrievalModelProfile: vi.fn(),
    deleteRetrievalModelProfile: vi.fn(),
    startRetrievalTokenizerFetch: vi.fn(),
    fetchRetrievalTokenizerFetch: vi.fn(),
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
    token_aware: false,
    tokenizer: null,
    chunk: null,
    ...overrides,
  };
}

function spacesResponse(
  overrides: Partial<RetrievalSpacesResponse> = {},
): RetrievalSpacesResponse {
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
    ...overrides,
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
    progress_detail: {
      phase: "queued",
      processed_documents: 0,
      total_documents: 20,
      processed_chunks: 0,
      pending_chunks: 40,
      total_chunks: 40,
      chunks_estimated: true,
      embedded_chunks: 0,
      skipped_chunks: 0,
      failed_chunks: 0,
      embedded_documents: 0,
      skipped_documents: 0,
      failed_documents: 0,
      tokens: null,
      tokens_estimated: false,
      embed_calls: 0,
      exact_tokenizer: true,
      done: false,
    },
    token_aware: false,
    tokenizer: null,
    chunk: null,
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

function modelProfile(
  overrides: Partial<RetrievalModelProfile> = {},
): RetrievalModelProfile {
  return {
    provider_class: "openai",
    model: "text-embedding-3-small",
    source: "curated",
    exact: true,
    override: false,
    identity: "tiktoken:cl100k_base#223921b76ee9",
    counted_identity: "tiktoken:cl100k_base#223921b76ee9",
    tokenizer_available: true,
    tokenizer_kind: "tiktoken",
    tokenizer_identifier: "cl100k_base",
    tokenizer_revision: null,
    tokenizer_artifact_sha256:
      "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7",
    max_input_tokens: 8191,
    max_input_assumed: false,
    degraded_reason: null,
    family: "openai",
    license: "openai-terms",
    source_url: "https://platform.openai.com/docs/guides/embeddings",
    repository: null,
    preset_revision: null,
    usable: true,
    usable_reason: null,
    batch_max_items: 2048,
    batch_max_tokens: 300000,
    chunk: { max_chunk_tokens: 512, overlap_tokens: 64, max_chars: 1600 },
    updated_by: null,
    updated_at: null,
    ...overrides,
  };
}

function modelProfilesResponse(
  overrides: Partial<RetrievalModelProfilesResponse> = {},
): RetrievalModelProfilesResponse {
  return {
    state: "ok",
    requested: null,
    assigned: { provider: "openai_compatible", model: "text-embedding-3-small" },
    resolution: modelProfile(),
    curated: [modelProfile()],
    unavailable_presets: [
      {
        family: "embeddinggemma",
        repository: "google/embeddinggemma-300m",
        revision: "57c266a740f537b4dc058e1b0cda161fd15afa75",
        license: "gemma",
        source_url: "https://huggingface.co/google/embeddinggemma-300m",
        max_input_tokens: 2048,
        models: ["embeddinggemma"],
        usable: false,
        usable_reason: "gated_repository",
      },
    ],
    overrides: [],
    bounds: {
      max_provider_class_length: 40,
      max_model_length: 200,
      max_identifier_length: 200,
      max_revision_length: 120,
      max_input_tokens: 1000000,
      max_batch_items: 4096,
      max_batch_tokens: 10000000,
      max_chunk_tokens: 1000000,
      max_chunk_chars: 1000000,
      supported_kinds: ["tiktoken", "hf_tokenizers", "heuristic"],
      supported_tiktoken_identifiers: ["cl100k_base"],
      hf_tokenizer_filename: "tokenizer.json",
      max_tokenizer_json_bytes: 33554432,
      requires_pinned_revision: true,
    },
    token_aware_writes: true,
    ...overrides,
  };
}

function tokenizerReport(): RetrievalTokenizerReport {
  return {
    state: "ok",
    model: {
      provider: "openai_compatible",
      model: "text-embedding-3-small",
      max_input_assumed: false,
    },
    tokenizer: {
      kind: "tiktoken",
      identifier: "cl100k_base",
      revision: null,
      artifact_sha256: "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7",
      exact: true,
      source: "curated",
      identity: "tiktoken:cl100k_base#223921b76ee9",
      max_input_tokens: 8191,
      max_input_assumed: false,
      degraded_reason: null,
    },
    profile: modelProfile(),
    chunking: {
      view: "body",
      max_chunk_chars: 1600,
      overlap_chars: 240,
      chunker_version: "1",
      composer_version: "1",
      token_aware: false,
      max_chunk_tokens: null,
      overlap_tokens: null,
      tokenizer_source: null,
    },
    reference: {
      state: "ok",
      samples: [
        {
          language: "english",
          label: "English",
          chars: 179,
          tokens: 32,
          chars_per_token: 5.594,
        },
        {
          language: "greek",
          label: "Greek",
          chars: 163,
          tokens: 153,
          chars_per_token: 1.065,
        },
      ],
      total_chars: 342,
      total_tokens: 185,
      chars_per_token: 1.849,
      exact: true,
      degraded_reason: null,
    },
    corpus: {
      state: "ok",
      documents: 12,
      records: 60,
      chars: 48000,
      tokens: 12000,
      chars_per_token: 4,
      max_record_tokens: 420,
      records_over_limit: 0,
      failed_documents: 0,
      limit_per_kind: 25,
      kinds: [],
      exact: true,
    },
    shadow: { writes: false },
  };
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
  localStorage.clear();
  useRetrievalDebugStore.setState({
    enabled: false,
    space: null,
    statuses: {},
    loading: false,
    error: null,
  });
  vi.mocked(retrievalApi.fetchRetrievalSpaces).mockResolvedValue(spacesResponse());
  vi.mocked(retrievalApi.fetchRetrievalHealth).mockResolvedValue(healthResponse());
  vi.mocked(retrievalApi.fetchRetrievalOverview).mockResolvedValue(overviewResponse());
  vi.mocked(retrievalApi.fetchRetrievalCoverage).mockResolvedValue(coverageResponse());
  vi.mocked(retrievalApi.fetchRetrievalQuality).mockResolvedValue(qualityResponse());
  vi.mocked(retrievalApi.fetchRetrievalRuns).mockResolvedValue(runsResponse());
  vi.mocked(retrievalApi.fetchRetrievalTokenizer).mockResolvedValue(tokenizerReport());
  vi.mocked(retrievalApi.fetchRetrievalModelProfiles).mockResolvedValue(
    modelProfilesResponse(),
  );
  vi.mocked(retrievalApi.saveRetrievalModelProfile).mockResolvedValue({
    state: "ok",
    profile: modelProfile({ source: "admin", override: true, exact: false }),
    token_aware_writes: true,
  });
  vi.mocked(retrievalApi.deleteRetrievalModelProfile).mockResolvedValue({
    state: "ok",
    deleted: true,
    resolution: modelProfile(),
    token_aware_writes: true,
  });
  vi.mocked(retrievalApi.startRetrievalTokenizerFetch).mockResolvedValue({
    state: "ok",
    job_id: "job-fetch-1",
    job_type: "tokenizer_fetch",
    status: "queued",
    progress: 0,
    stage: null,
    requested: {
      repository: "org/model",
      revision: "0123456789abcdef0123456789abcdef01234567",
    },
    deduplicated: false,
    idempotency_key: "key",
  });
  vi.mocked(retrievalApi.fetchRetrievalTokenizerFetch).mockResolvedValue({
    state: "ok",
    job_id: "job-fetch-1",
    status: "succeeded",
    progress: 100,
    stage: "done",
    heartbeat_at: "2026-11-04T10:00:00Z",
    error: null,
    result: {
      repository: "org/model",
      revision: "0123456789abcdef0123456789abcdef01234567",
      filename: "tokenizer.json",
      sha256: "b".repeat(64),
      size_bytes: 531,
      cached: false,
      files: { "tokenizer.json": 531 },
    },
    requested: {
      repository: "org/model",
      revision: "0123456789abcdef0123456789abcdef01234567",
    },
    created_at: "2026-11-04T10:00:00Z",
    finished_at: "2026-11-04T10:00:02Z",
  });
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

  it("toggles the per-browser retrieval debug marker", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByTestId("retrieval-active-space");
    const toggle = screen.getByTestId("retrieval-debug-toggle");
    expect(toggle).toHaveAttribute("aria-checked", "false");

    await user.click(toggle);
    expect(localStorage.getItem("ca:retrieval-debug")).toBe("1");
    expect(await screen.findByTestId("retrieval-debug-space")).toBeInTheDocument();

    await user.click(screen.getByTestId("retrieval-debug-clear"));
    expect(screen.getByTestId("retrieval-debug-count")).toBeInTheDocument();
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

  it("builds a token-aware v2 space from the resolved profile and chunk bounds", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByTestId("retrieval-active-space");

    await user.click(screen.getByTestId("retrieval-build-toggle"));
    await user.type(screen.getByTestId("retrieval-build-name"), "candidate-2");
    await user.type(screen.getByTestId("retrieval-build-provider"), "openai");
    await user.type(screen.getByTestId("retrieval-build-model"), "text-embedding-3-small");
    await screen.findByTestId("retrieval-build-profile");
    await waitFor(() =>
      expect(retrievalApi.fetchRetrievalModelProfiles).toHaveBeenCalledWith({
        provider: "openai",
        model: "text-embedding-3-small",
      }),
    );
    await user.click(screen.getByTestId("retrieval-build-submit"));

    await waitFor(() =>
      expect(retrievalApi.buildRetrievalSpace).toHaveBeenCalledWith({
        name: "candidate-2",
        provider: "openai",
        model: "text-embedding-3-small",
        dim: 1536,
        query_prefix: undefined,
        document_prefix: undefined,
        tokenizer_profile: {
          provider: "openai",
          model: "text-embedding-3-small",
        },
        chunk: { max_chunk_tokens: 512, overlap_tokens: 64, max_chars: 1600 },
      }),
    );
  });

  it("submits a legacy v1 build when token awareness is switched off", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByTestId("retrieval-active-space");

    await user.click(screen.getByTestId("retrieval-build-toggle"));
    await user.type(screen.getByTestId("retrieval-build-name"), "legacy");
    await user.type(screen.getByTestId("retrieval-build-provider"), "openai");
    await user.type(screen.getByTestId("retrieval-build-model"), "text-embedding-3-small");
    await user.click(
      screen.getByRole("switch", { name: "retrieval.buildProfile.tokenAware" }),
    );
    expect(screen.queryByTestId("retrieval-build-profile")).toBeNull();
    await user.click(screen.getByTestId("retrieval-build-submit"));

    await waitFor(() =>
      expect(retrievalApi.buildRetrievalSpace).toHaveBeenCalledWith({
        name: "legacy",
        provider: "openai",
        model: "text-embedding-3-small",
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

  it("previews the resolved tokenizer profile in the build form", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByTestId("retrieval-active-space");

    await user.click(screen.getByTestId("retrieval-build-toggle"));
    await user.type(screen.getByTestId("retrieval-build-provider"), "openai");
    await user.type(screen.getByTestId("retrieval-build-model"), "text-embedding-3-small");

    const preview = await screen.findByTestId("retrieval-build-profile");
    await waitFor(() =>
      expect(retrievalApi.fetchRetrievalModelProfiles).toHaveBeenCalledWith({
        provider: "openai",
        model: "text-embedding-3-small",
      }),
    );
    expect(preview.textContent).toContain("retrieval.buildProfile.line");
    expect(preview.textContent).toContain("retrieval.buildProfile.provenance");
    expect(preview.textContent).toContain("retrieval.buildProfile.v2Hint");
    expect(screen.getByTestId("retrieval-build-chunk-tokens")).toHaveValue(512);
  });

  it("warns visibly when the resolved build tokenizer is the fallback", async () => {
    const user = userEvent.setup();
    vi.mocked(retrievalApi.fetchRetrievalModelProfiles).mockResolvedValue(
      modelProfilesResponse({
        resolution: modelProfile({
          provider_class: "ollama",
          model: "unknown-embed",
          source: "fallback",
          exact: false,
          identity: "heuristic:utf8-heuristic-v1",
          counted_identity: "heuristic:utf8-heuristic-v1",
          tokenizer_kind: "heuristic",
          tokenizer_identifier: "utf8-heuristic-v1",
          tokenizer_artifact_sha256: null,
          max_input_tokens: 2048,
          max_input_assumed: true,
          degraded_reason: null,
          chunk: { max_chunk_tokens: 256, overlap_tokens: 32, max_chars: 800 },
        }),
      }),
    );
    renderSection();
    await screen.findByTestId("retrieval-active-space");
    await user.click(screen.getByTestId("retrieval-build-toggle"));
    await user.type(screen.getByTestId("retrieval-build-provider"), "ollama");
    await user.type(screen.getByTestId("retrieval-build-model"), "unknown-embed");
    const warning = await screen.findByTestId("retrieval-build-profile-warning");
    expect(warning.textContent).toContain("retrieval.profile.fallbackWarning");
  });

  it("rejects unsafe chunk bounds before submitting a v2 build", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByTestId("retrieval-active-space");
    await user.click(screen.getByTestId("retrieval-build-toggle"));
    await user.type(screen.getByTestId("retrieval-build-name"), "candidate-3");
    await user.type(screen.getByTestId("retrieval-build-provider"), "openai");
    await user.type(screen.getByTestId("retrieval-build-model"), "text-embedding-3-small");
    await screen.findByTestId("retrieval-build-profile");

    const overlap = screen.getByTestId("retrieval-build-chunk-overlap");
    await user.clear(overlap);
    await user.type(overlap, "256");
    expect(await screen.findByTestId("retrieval-build-chunk-error")).toHaveTextContent(
      "retrieval.buildProfile.chunkOverlapTooLarge",
    );
    expect(screen.getByTestId("retrieval-build-submit")).toBeDisabled();
    expect(retrievalApi.buildRetrievalSpace).not.toHaveBeenCalled();
  });

  it("renders the token-aware chunker on the space card and links the runbook", async () => {
    vi.mocked(retrievalApi.fetchRetrievalSpaces).mockResolvedValue(
      spacesResponse({
        spaces: [
          space({
            token_aware: true,
            tokenizer: {
              kind: "tiktoken",
              identifier: "cl100k_base",
              revision: null,
              artifact_sha256: "a".repeat(64),
              exact: true,
              max_input_tokens: 8191,
              source: "curated",
            },
            chunk: { max_chunk_tokens: 256, overlap_tokens: 32, max_chars: 1200 },
          }),
          ...spacesResponse().spaces.slice(1),
        ],
      }),
    );
    renderSection();
    await screen.findByTestId("retrieval-active-space");
    const cell = screen.getByTestId("retrieval-chunker-sp-active");
    expect(cell.textContent).toContain("retrieval.spaces.tokenAware");
    expect(cell.textContent).toContain("cl100k_base");
    expect(cell.textContent).toContain("retrieval.spaces.chunkBudget");
    expect(screen.getByTestId("retrieval-active-chunker").textContent).toContain(
      "cl100k_base",
    );
    expect(screen.getByTestId("retrieval-active-runbook").getAttribute("href")).toContain(
      "docs/dev/retrieval-ops.md",
    );
  });

  it("shows the effective profile and saves a bounded admin override", async () => {
    const user = userEvent.setup();
    renderSection();
    const card = await screen.findByTestId("retrieval-model-profile");
    expect(card.textContent).toContain("retrieval.profile.source.curated");
    expect(within(card).getByTestId("retrieval-profile-limit").textContent).toContain(
      "8191",
    );
    expect(within(card).getByTestId("retrieval-profile-batch").textContent).toContain(
      "retrieval.profile.batch",
    );
    expect(within(card).getByTestId("retrieval-profile-chunk").textContent).toContain(
      "retrieval.profile.chunk",
    );
    expect(within(card).queryByTestId("retrieval-profile-warning")).toBeNull();

    await user.click(within(card).getByTestId("retrieval-profile-save"));
    await waitFor(() =>
      expect(retrievalApi.saveRetrievalModelProfile).toHaveBeenCalledTimes(1),
    );
    expect(retrievalApi.saveRetrievalModelProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        provider_class: "openai",
        model: "text-embedding-3-small",
        tokenizer_kind: "tiktoken",
        tokenizer_identifier: "cl100k_base",
        max_input_tokens: 8191,
        batch_max_items: 2048,
        batch_max_tokens: 300000,
        chunk_max_tokens: 512,
        chunk_overlap_tokens: 64,
        chunk_max_chars: 1600,
      }),
    );
    expect(within(card).getByText("retrieval.profile.saved")).toBeTruthy();
  });

  it("labels the conservative fallback profile", async () => {
    vi.mocked(retrievalApi.fetchRetrievalModelProfiles).mockResolvedValue(
      modelProfilesResponse({
        resolution: modelProfile({
          provider_class: "ollama",
          model: "nomic-embed-text",
          source: "fallback",
          exact: false,
          override: false,
          identity: "heuristic:utf8-heuristic-v1",
          tokenizer_kind: "heuristic",
          tokenizer_identifier: "utf8-heuristic-v1",
          tokenizer_artifact_sha256: null,
          max_input_tokens: 2048,
          max_input_assumed: true,
          batch_max_items: 64,
          batch_max_tokens: 8192,
          chunk: { max_chunk_tokens: 256, overlap_tokens: 32, max_chars: 800 },
        }),
      }),
    );
    renderSection();
    const card = await screen.findByTestId("retrieval-model-profile");
    expect(card.textContent).toContain("retrieval.profile.source.fallback");
    expect(within(card).getByTestId("retrieval-profile-warning").textContent).toContain(
      "retrieval.profile.fallbackWarning",
    );
    expect(within(card).getByTestId("retrieval-profile-limit").textContent).toContain(
      "assumed",
    );
    expect(within(card).queryByTestId("retrieval-profile-reset")).toBeNull();
  });

  it("resets an admin override back to the curated profile", async () => {
    const user = userEvent.setup();
    vi.mocked(retrievalApi.fetchRetrievalModelProfiles).mockResolvedValue(
      modelProfilesResponse({
        resolution: modelProfile({ source: "admin", override: true }),
        overrides: [modelProfile({ source: "admin", override: true })],
      }),
    );
    renderSection();
    const card = await screen.findByTestId("retrieval-model-profile");
    expect(card.textContent).toContain("retrieval.profile.overridden");
    await user.click(within(card).getByTestId("retrieval-profile-reset"));
    await waitFor(() =>
      expect(retrievalApi.deleteRetrievalModelProfile).toHaveBeenCalledWith(
        "openai",
        "text-embedding-3-small",
      ),
    );
    expect(within(card).getByText("retrieval.profile.resetDone")).toBeTruthy();
  });

  it("fetches a pinned HF tokenizer and applies the verified checksum", async () => {
    const user = userEvent.setup();
    const revision = "0123456789abcdef0123456789abcdef01234567";
    vi.mocked(retrievalApi.fetchRetrievalModelProfiles).mockResolvedValue(
      modelProfilesResponse({
        resolution: modelProfile({
          source: "admin",
          override: true,
          exact: false,
          tokenizer_available: false,
          identity: `hf_tokenizers:org/model@${revision}`,
          counted_identity: "heuristic:utf8-heuristic-v1",
          tokenizer_kind: "hf_tokenizers",
          tokenizer_identifier: "org/model",
          tokenizer_revision: revision,
          tokenizer_artifact_sha256: null,
          max_input_tokens: 512,
          max_input_assumed: false,
          degraded_reason: "asset_missing",
          family: "nomic",
          license: "apache-2.0",
          source_url: "https://huggingface.co/org/model",
          repository: "org/model",
          preset_revision: revision,
          batch_max_items: 256,
          batch_max_tokens: 250000,
          chunk: { max_chunk_tokens: 512, overlap_tokens: 64, max_chars: 1600 },
        }),
      }),
    );
    renderSection();
    const card = await screen.findByTestId("retrieval-model-profile");
    expect(within(card).getByTestId("retrieval-profile-provenance").textContent).toContain(
      "retrieval.profile.license",
    );
    expect(within(card).getByTestId("retrieval-profile-unavailable").textContent).toContain(
      "retrieval.profile.assetMissing",
    );
    await user.click(within(card).getByText("retrieval.profile.edit"));
    await user.click(within(card).getByTestId("retrieval-profile-fetch"));
    await waitFor(() =>
      expect(retrievalApi.startRetrievalTokenizerFetch).toHaveBeenCalledWith({
        repository: "org/model",
        revision,
      }),
    );
    await waitFor(() =>
      expect(
        (within(card).getByTestId("retrieval-profile-sha256") as HTMLInputElement).value,
      ).toBe("b".repeat(64)),
    );
    expect(within(card).getByTestId("retrieval-profile-fetch-status").textContent).toContain(
      "retrieval.profile.fetchStatus",
    );
  });

  it("blocks saving an HF profile without a pinned revision and checksum", async () => {
    const user = userEvent.setup();
    vi.mocked(retrievalApi.fetchRetrievalModelProfiles).mockResolvedValue(
      modelProfilesResponse({
        resolution: modelProfile({
          source: "admin",
          override: true,
          exact: false,
          tokenizer_available: false,
          identity: "hf_tokenizers:org/model",
          counted_identity: "heuristic:utf8-heuristic-v1",
          tokenizer_kind: "hf_tokenizers",
          tokenizer_identifier: "org/model",
          tokenizer_revision: null,
          tokenizer_artifact_sha256: null,
          max_input_tokens: 512,
          degraded_reason: "asset_missing",
          family: "nomic",
          license: "apache-2.0",
          source_url: "https://huggingface.co/org/model",
          repository: "org/model",
          batch_max_items: 256,
          batch_max_tokens: 250000,
          chunk: { max_chunk_tokens: 512, overlap_tokens: 64, max_chars: 1600 },
        }),
      }),
    );
    renderSection();
    const card = await screen.findByTestId("retrieval-model-profile");
    await user.click(within(card).getByText("retrieval.profile.edit"));
    expect(within(card).getByTestId("retrieval-profile-save")).toBeDisabled();
    expect(within(card).getByTestId("retrieval-profile-fetch")).toBeDisabled();
  });

  it("shows a failed tokenizer fetch without pretending it succeeded", async () => {
    const user = userEvent.setup();
    const revision = "0123456789abcdef0123456789abcdef01234567";
    vi.mocked(retrievalApi.fetchRetrievalModelProfiles).mockResolvedValue(
      modelProfilesResponse({
        resolution: modelProfile({
          source: "admin",
          override: true,
          exact: false,
          tokenizer_available: false,
          identity: `hf_tokenizers:org/model@${revision}`,
          counted_identity: "heuristic:utf8-heuristic-v1",
          tokenizer_kind: "hf_tokenizers",
          tokenizer_identifier: "org/model",
          tokenizer_revision: revision,
          tokenizer_artifact_sha256: "b".repeat(64),
          max_input_tokens: 512,
          degraded_reason: "asset_missing",
          family: "nomic",
          license: "apache-2.0",
          source_url: "https://huggingface.co/org/model",
          repository: "org/model",
          batch_max_items: 256,
          batch_max_tokens: 250000,
          chunk: { max_chunk_tokens: 512, overlap_tokens: 64, max_chars: 1600 },
        }),
      }),
    );
    vi.mocked(retrievalApi.fetchRetrievalTokenizerFetch).mockResolvedValue({
      state: "ok",
      job_id: "job-fetch-1",
      status: "failed",
      progress: 40,
      stage: "failed",
      heartbeat_at: "2026-11-04T10:00:00Z",
      error: "checksum_mismatch: expected a, got b",
      result: null,
      requested: { repository: "org/model", revision },
      created_at: "2026-11-04T10:00:00Z",
      finished_at: "2026-11-04T10:00:02Z",
    });
    renderSection();
    const card = await screen.findByTestId("retrieval-model-profile");
    await user.click(within(card).getByText("retrieval.profile.edit"));
    await user.click(within(card).getByTestId("retrieval-profile-fetch"));
    await waitFor(() =>
      expect(within(card).getByRole("alert").textContent).toContain("checksum_mismatch"),
    );
  });

  it("labels an unavailable curated preset without claiming support", async () => {
    vi.mocked(retrievalApi.fetchRetrievalModelProfiles).mockResolvedValue(
      modelProfilesResponse({
        resolution: modelProfile({
          provider_class: "openai",
          model: "embeddinggemma",
          source: "fallback",
          exact: false,
          override: false,
          identity: "heuristic:utf8-heuristic-v1",
          counted_identity: "heuristic:utf8-heuristic-v1",
          tokenizer_kind: "heuristic",
          tokenizer_identifier: "utf8-heuristic-v1",
          tokenizer_artifact_sha256: null,
          max_input_tokens: 2048,
          max_input_assumed: true,
          family: "embeddinggemma",
          license: "gemma",
          source_url: "https://huggingface.co/google/embeddinggemma-300m",
          repository: "google/embeddinggemma-300m",
          usable: false,
          usable_reason: "gated_repository",
          batch_max_items: 64,
          batch_max_tokens: 8192,
          chunk: { max_chunk_tokens: 256, overlap_tokens: 32, max_chars: 800 },
        }),
      }),
    );
    renderSection();
    const card = await screen.findByTestId("retrieval-model-profile");
    const unavailable = within(card).getByTestId("retrieval-profile-unavailable");
    expect(unavailable.textContent).toContain("retrieval.profile.unavailable");
    expect(within(card).getByTestId("retrieval-profile-warning").textContent).toContain(
      "retrieval.profile.fallbackWarning",
    );
  });

  it("renders a queued run and offers cancel without implying completion", async () => {
    renderSection();
    await screen.findByTestId("retrieval-active-space");
    const row = await screen.findByTestId("retrieval-run-run-queued-1");
    expect(within(row).getByText("retrieval.status.queued")).toBeTruthy();
    expect(within(row).getByTestId("retrieval-cancel-run-queued-1")).toBeTruthy();
    const bar = within(row).getByTestId("retrieval-run-progress-run-queued-1-bar");
    expect(bar).toHaveAttribute("role", "progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "0");
    expect(
      within(row).getByTestId("retrieval-run-progress-run-queued-1-documents")
        .textContent,
    ).toContain("retrieval.progress.documents");
    expect(
      within(row).getByTestId("retrieval-run-progress-run-queued-1-pending")
        .textContent,
    ).toContain("retrieval.progress.chunksPending");
    expect(
      within(row).getByTestId("retrieval-run-progress-run-queued-1-estimated"),
    ).toBeTruthy();
  });

  it("renders the tokenizer and limits report as read-only evidence", async () => {
    renderSection();
    const card = await screen.findByTestId("retrieval-tokenizer-report");
    expect(within(card).getByTestId("retrieval-tokenizer-name").textContent).toContain(
      "cl100k_base",
    );
    expect(within(card).getByTestId("retrieval-tokenizer-name").textContent).toContain(
      "retrieval.tokenizer.exact",
    );
    expect(within(card).getByTestId("retrieval-tokenizer-limit").textContent).toContain(
      "8191",
    );
    expect(
      within(card).getByTestId("retrieval-tokenizer-sample-greek").textContent,
    ).toContain("153");
    expect(within(card).getByTestId("retrieval-tokenizer-corpus").textContent).toContain(
      "retrieval.tokenizer.corpusStats",
    );
    expect(
      within(card).queryByTestId("retrieval-tokenizer-warning"),
    ).toBeNull();
    expect(within(card).getByText("retrieval.tokenizer.shadow")).toBeTruthy();
  });
});
