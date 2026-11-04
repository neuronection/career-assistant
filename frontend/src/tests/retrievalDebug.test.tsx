import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchDocumentStatuses } from "@/api/retrieval";
import type { RetrievalDocumentStatus } from "@/api/retrieval";
import { useRetrievalDebugStore } from "@/stores/retrievalDebugStore";

vi.mock("@/api/retrieval", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/retrieval")>();
  return { ...actual, fetchDocumentStatuses: vi.fn() };
});

const mockedFetch = vi.mocked(fetchDocumentStatuses);
const STORAGE_KEY = "ca:retrieval-debug";

function status(sourceId: string, state: RetrievalDocumentStatus["state"] = "current") {
  return {
    source_id: sourceId,
    state,
    reason: null,
    records: 2,
    indexed_at: "2026-11-04T00:00:00Z",
  } satisfies RetrievalDocumentStatus;
}

function response(ids: string[]) {
  return {
    kind: "posting",
    space: {
      space_id: "space-1",
      name: "content",
      status: "active" as const,
      backend: "pgvector",
      model: "text-embedding-3-small",
      dim: 1536,
    },
    documents: ids.map((id) => status(id)),
  };
}

beforeEach(() => {
  localStorage.clear();
  mockedFetch.mockReset();
  useRetrievalDebugStore.setState({
    enabled: false,
    space: null,
    statuses: {},
    loading: false,
    error: null,
  });
});

describe("retrieval debug store", () => {
  it("seeds enabled from localStorage and persists the toggle", async () => {
    localStorage.setItem(STORAGE_KEY, "1");
    vi.resetModules();
    const fresh = await import("@/stores/retrievalDebugStore");
    expect(fresh.useRetrievalDebugStore.getState().enabled).toBe(true);

    fresh.useRetrievalDebugStore.getState().setEnabled(false);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(fresh.useRetrievalDebugStore.getState().enabled).toBe(false);

    fresh.useRetrievalDebugStore.getState().setEnabled(true);
    expect(localStorage.getItem(STORAGE_KEY)).toBe("1");
  });

  it("batches every new id into one request and skips already-known ids", async () => {
    useRetrievalDebugStore.getState().setEnabled(true);
    mockedFetch.mockResolvedValueOnce(response(["a", "b"]));
    await useRetrievalDebugStore.getState().load(["a", "b"]);

    expect(mockedFetch).toHaveBeenCalledTimes(1);
    expect(mockedFetch).toHaveBeenCalledWith("posting", ["a", "b"]);
    expect(Object.keys(useRetrievalDebugStore.getState().statuses).sort()).toEqual(["a", "b"]);
    expect(useRetrievalDebugStore.getState().space?.name).toBe("content");

    mockedFetch.mockResolvedValueOnce(response(["c"]));
    await useRetrievalDebugStore.getState().load(["a", "b", "c"]);

    expect(mockedFetch).toHaveBeenCalledTimes(2);
    expect(mockedFetch).toHaveBeenLastCalledWith("posting", ["c"]);
  });

  it("caps a batch at fifty ids", async () => {
    useRetrievalDebugStore.getState().setEnabled(true);
    const ids = Array.from({ length: 60 }, (_, index) => `id-${index}`);
    mockedFetch.mockResolvedValueOnce(response(ids.slice(0, 50)));
    await useRetrievalDebugStore.getState().load(ids);

    expect(mockedFetch).toHaveBeenCalledTimes(1);
    expect(mockedFetch.mock.calls[0][1]).toHaveLength(50);
  });

  it("never requests an id twice while another load is in flight", async () => {
    useRetrievalDebugStore.getState().setEnabled(true);
    let resolveFirst: (value: unknown) => void = () => {};
    mockedFetch.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFirst = resolve;
        }) as never,
    );
    mockedFetch.mockResolvedValueOnce(response(["c"]));

    const first = useRetrievalDebugStore.getState().load(["a", "b"]);
    const second = useRetrievalDebugStore.getState().load(["a", "b", "c"]);

    expect(mockedFetch).toHaveBeenCalledTimes(2);
    expect(mockedFetch).toHaveBeenNthCalledWith(1, "posting", ["a", "b"]);
    expect(mockedFetch).toHaveBeenNthCalledWith(2, "posting", ["c"]);
    resolveFirst(response(["a", "b"]));
    await Promise.all([first, second]);

    expect(Object.keys(useRetrievalDebugStore.getState().statuses).sort()).toEqual([
      "a",
      "b",
      "c",
    ]);
  });

  it("keeps the previous map when the request fails and records the error", async () => {
    useRetrievalDebugStore.getState().setEnabled(true);
    mockedFetch.mockResolvedValueOnce(response(["a"]));
    await useRetrievalDebugStore.getState().load(["a"]);

    mockedFetch.mockRejectedValueOnce(new Error("network down"));
    await useRetrievalDebugStore.getState().load(["b"]);

    expect(useRetrievalDebugStore.getState().error).toBe("network down");
    expect(useRetrievalDebugStore.getState().statuses.a.state).toBe("current");
    expect(useRetrievalDebugStore.getState().statuses.b).toBeUndefined();
  });

  it("does nothing while disabled and clears the cache on demand", async () => {
    await useRetrievalDebugStore.getState().load(["a"]);
    expect(mockedFetch).not.toHaveBeenCalled();

    useRetrievalDebugStore.getState().setEnabled(true);
    mockedFetch.mockResolvedValueOnce(response(["a"]));
    await useRetrievalDebugStore.getState().load(["a"]);
    useRetrievalDebugStore.getState().clear();

    expect(useRetrievalDebugStore.getState().statuses).toEqual({});
    expect(useRetrievalDebugStore.getState().space).toBeNull();
  });
});
