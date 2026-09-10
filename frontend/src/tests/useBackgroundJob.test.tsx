import { renderHook, waitFor, act } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { useBackgroundJob } from "@/hooks/useBackgroundJob";
import * as api from "@/api/backgroundJobs";
import type { BackgroundJob } from "@/api/backgroundJobs";

function job(overrides: Partial<BackgroundJob> = {}): BackgroundJob {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    job_type: "job_generate",
    status: "running",
    progress: 40,
    stage: "calling the model",
    error: null,
    result: null,
    payload: {},
    attempts: 1,
    max_attempts: 2,
    created_at: "2026-08-28T00:00:00Z",
    updated_at: "2026-08-28T00:00:00Z",
    finished_at: null,
    ...overrides,
  };
}

describe("useBackgroundJob", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("polls until terminal and fires the done callback", async () => {
    vi.spyOn(api, "fetchBackgroundJob")
      .mockResolvedValueOnce(job({ progress: 10, stage: "queued…" }))
      .mockResolvedValueOnce(
        job({
          status: "succeeded",
          progress: 100,
          stage: "done",
          result: { draft_count: 3 },
          finished_at: "2026-08-28T00:00:01Z",
        }),
      );
    const onDone = vi.fn();
    const { result } = renderHook(() => useBackgroundJob(onDone));

    act(() => result.current.track("abc", 5));

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(onDone.mock.calls[0][0].status).toBe("succeeded");
    expect(api.fetchBackgroundJob).toHaveBeenCalledTimes(2);
    expect(result.current.tracking).toBe(false);
  });

  it("keeps polling while the job is still running", async () => {
    const fetchMock = vi
      .spyOn(api, "fetchBackgroundJob")
      .mockResolvedValue(job({ progress: 55 }));
    const { result } = renderHook(() => useBackgroundJob());

    act(() => result.current.track("abc", 5));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3));

    expect(result.current.job?.progress).toBe(55);
    result.current.stop();
    const calls = fetchMock.mock.calls.length;
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock.mock.calls.length).toBe(calls);
  });

  it("reset clears the tracked job", async () => {
    vi.spyOn(api, "fetchBackgroundJob").mockResolvedValue(job());
    const { result } = renderHook(() => useBackgroundJob());

    act(() => result.current.track("abc", 5));
    await waitFor(() => expect(result.current.job).not.toBeNull());
    act(() => result.current.reset());
    expect(result.current.job).toBeNull();
  });
});
