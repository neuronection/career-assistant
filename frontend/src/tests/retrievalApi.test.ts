import { afterEach, describe, expect, it, vi } from "vitest";

import {
  activateRetrievalSpace,
  buildRetrievalSpace,
  compareRetrievalQuality,
  dropRetrievalSpace,
  fetchRetrievalCoverage,
  reindexRetrievalSpace,
  retireRetrievalSpace,
  retrievalActionError,
  runRetrievalMaintenance,
} from "@/api/retrieval";

const apiGet = vi.fn();
const apiPost = vi.fn();

vi.mock("@/api/client", () => ({
  api: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
  apiDetail: (error: unknown) =>
    (error as { message?: string })?.message ?? String(error),
}));

function axiosError(status: number, data: unknown): Error {
  return Object.assign(new Error("request failed"), {
    isAxiosError: true,
    response: { status, data },
  });
}

function idempotencyKey(callIndex = 0): string {
  const config = apiPost.mock.calls[callIndex][2] as {
    headers: Record<string, string>;
  };
  return config.headers["Idempotency-Key"];
}

afterEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
});

describe("retrieval action API", () => {
  it("queues a reindex with the scope/budget body and a replay key", async () => {
    apiPost.mockResolvedValue({
      data: { accepted: true, status: "queued", run_id: "run-1", message: "reindex queued" },
    });
    await reindexRetrievalSpace({
      space: "space-1",
      kind: "posting",
      view: "summary",
      since: "2026-11-01T00:00:00Z",
      budget: 1200,
      limit: 50,
      force: true,
    });
    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(apiPost.mock.calls[0][0]).toBe("/admin/retrieval/reindex");
    expect(apiPost.mock.calls[0][1]).toEqual({
      space: "space-1",
      kind: "posting",
      view: "summary",
      since: "2026-11-01T00:00:00Z",
      budget: 1200,
      limit: 50,
      force: true,
    });
    expect(idempotencyKey()).toMatch(/^[0-9a-f-]{8,}$/);
  });

  it("sends maintenance with its action and dry-run flag plus a replay key", async () => {
    apiPost.mockResolvedValue({ data: { accepted: true, message: "maintenance queued" } });
    await runRetrievalMaintenance({
      space: "space-1",
      action: "orphan-sweep",
      dry_run: true,
      limit: 100,
    });
    expect(apiPost.mock.calls[0][0]).toBe("/admin/retrieval/maintenance");
    expect(apiPost.mock.calls[0][1]).toEqual({
      space: "space-1",
      action: "orphan-sweep",
      dry_run: true,
      limit: 100,
    });
    expect(idempotencyKey()).toMatch(/^[0-9a-f-]{8,}$/);
  });

  it("carries the replay key through every lifecycle action", async () => {
    apiPost.mockResolvedValue({ data: { accepted: true, message: "ok" } });
    await buildRetrievalSpace({
      name: "candidate",
      provider: "openai",
      model: "text-embedding-3-small",
      dim: 1536,
      query_prefix: "query: ",
      document_prefix: "passage: ",
    });
    await activateRetrievalSpace("space-1");
    await retireRetrievalSpace("space-1", "space-one");
    await dropRetrievalSpace("space-1", "space-one", true);

    expect(apiPost.mock.calls[0][0]).toBe("/admin/retrieval/spaces");
    expect(apiPost.mock.calls[1][0]).toBe("/admin/retrieval/spaces/space-1/activate");
    expect(apiPost.mock.calls[2][0]).toBe("/admin/retrieval/spaces/space-1/retire");
    expect(apiPost.mock.calls[2][1]).toEqual({ confirm_space_name: "space-one" });
    expect(apiPost.mock.calls[3][0]).toBe("/admin/retrieval/spaces/space-1/drop");
    expect(apiPost.mock.calls[3][1]).toEqual({
      confirm_space_name: "space-one",
      force: true,
    });
    for (let index = 0; index < 4; index += 1) {
      expect(idempotencyKey(index)).toMatch(/^[0-9a-f-]{8,}$/);
    }
  });

  it("runs the golden-query compare with candidate and baseline plus a replay key", async () => {
    apiPost.mockResolvedValue({ data: { accepted: true, message: "quality compare complete" } });
    await compareRetrievalQuality({ space: "candidate", compare_space: "baseline" });
    expect(apiPost.mock.calls[0][0]).toBe("/admin/retrieval/quality/compare");
    expect(apiPost.mock.calls[0][1]).toEqual({
      space: "candidate",
      compare_space: "baseline",
    });
    expect(idempotencyKey()).toMatch(/^[0-9a-f-]{8,}$/);
  });
});

describe("retrieval reads", () => {
  it("reads coverage for the chosen space", async () => {
    apiGet.mockResolvedValue({ data: { state: "never_reconciled" } });
    await fetchRetrievalCoverage("space-1");
    expect(apiGet).toHaveBeenCalledWith("/admin/retrieval/coverage", {
      params: { space: "space-1" },
    });
  });
});

describe("retrieval action errors", () => {
  it("keeps the structured 409 gate payload", () => {
    const payload = {
      action: "activate_space",
      accepted: false,
      audit_event: "vector.gate.failed",
      http_status: 409,
      deduplicated: false,
      run_id: "run-1",
      status: "failed",
      idempotency_key: "key-123456",
      message: "activation refused: coverage and quality must both pass",
      activation_gate: {
        space_id: "space-1",
        coverage: "fail",
        quality: "fail",
        allowed: false,
        reasons: ["coverage_fail", "quality_below_floor"],
      },
    };
    const info = retrievalActionError(axiosError(409, payload));
    expect(info.status).toBe(409);
    expect(info.detail).toBe(payload.message);
    expect(info.payload?.activation_gate?.reasons).toEqual([
      "coverage_fail",
      "quality_below_floor",
    ]);
  });

  it("falls back to the plain detail for a non-structured conflict", () => {
    const info = retrievalActionError(axiosError(409, { detail: "space is busy" }));
    expect(info.payload).toBeNull();
    expect(info.detail).toBe("request failed");
  });
});
