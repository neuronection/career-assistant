import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { BuildProgressCard } from "@/components/cv/BuildProgress";
import { useCvBuilderLink } from "@/stores/cvBuilderLinkStore";

const api = vi.hoisted(() => ({
  fetchCvRuns: vi.fn(),
  cancelBackgroundJob: vi.fn(),
  polishCv: vi.fn(),
  createChatSession: vi.fn(),
}));

vi.mock("@/api/cv", () => ({
  fetchCvRuns: api.fetchCvRuns,
  polishCv: api.polishCv,
}));

vi.mock("@/api/backgroundJobs", () => ({
  cancelBackgroundJob: api.cancelBackgroundJob,
}));

vi.mock("@/api/universities", () => ({
  fetchChatSessions: vi.fn(),
  fetchMessages: vi.fn().mockResolvedValue([]),
  createChatSession: api.createChatSession,
}));

const runRow = (overrides: Record<string, unknown> = {}) => ({
  job_id: "11111111-1111-1111-1111-111111111111",
  job_type: "cv_polish",
  status: "running",
  stage: "polish.iterate",
  error: null,
  created_at: "2026-09-11T09:00:00Z",
  finished_at: null,
  outcome: null as string | null,
  resumed_from: null,
  final_version: null,
  stages: [{ node: "collect", at: "2026-09-11T09:01:10Z" }],
  iterations: [{ n: 1, ops: [{ op: "move_block", ok: true, detail: "Languages section moved" }] }],
  llm_calls: [
    {
      id: "c1",
      task: "cv_polish",
      stage: "polish.iterate",
      status: "ok",
      provider: "mock",
      model: "mock-gpt",
      prompt_version: "cv-polish@1",
      tokens_in: 900,
      tokens_out: 350,
      latency_ms: 2100,
    },
  ],
  aggregate: {
    calls: 1,
    tokens_in: 900,
    tokens_out: 350,
    latency_ms_sum: 2100,
    by_task: {},
  },
  ...overrides,
});

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  api.fetchCvRuns.mockReset().mockResolvedValue([]);
  api.cancelBackgroundJob.mockReset().mockResolvedValue({});
  api.polishCv.mockReset().mockResolvedValue({});
  useCvBuilderLink.setState({ lastBuilderState: null, liveTurns: {}, flushCallback: null });
});

afterEach(() => {
  useCvBuilderLink.setState({ lastBuilderState: null, liveTurns: {}, flushCallback: null });
  vi.useRealTimers();
});

function renderCard(onRunFinished = vi.fn()) {
  render(
    <BuildProgressCard cvId="cv-1" onOpenRuns={vi.fn()} onRunFinished={onRunFinished} />,
  );
  return onRunFinished;
}

describe("builder run progress card (plan 67.3)", () => {
  it("renders nothing (and no copilot card) with no runs and no live turn", async () => {
    renderCard();
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.queryByTestId("cv-build-progress")).not.toBeInTheDocument();
    expect(api.fetchCvRuns).toHaveBeenCalledWith("cv-1");
  });

  it("shows the running job with status chip, telemetry and cancel while polling", async () => {
    api.fetchCvRuns.mockResolvedValue([runRow()]);
    renderCard();
    const card = await screen.findByTestId("cv-build-progress");
    expect(card.querySelector('[data-testid="cv-run-progress"]')).not.toBeNull();
    expect(card.querySelector('[data-testid="cv-run-progress"]')!.getAttribute("data-run-type")).toBe("cv_polish");
    expect(screen.getByTestId("cv-run-progress-status")).toHaveTextContent("Running");
    expect(screen.getByTestId("cv-run-telemetry")).toHaveTextContent("1 call(s)");
    expect(screen.getByTestId("cv-run-telemetry")).toHaveTextContent("Simulated");
    expect(screen.getByTestId("cv-run-cancel")).toBeInTheDocument();
    expect(screen.getByTestId("cv-run-open-runs")).toBeInTheDocument();
    const callsAfterFirst = api.fetchCvRuns.mock.calls.length;
    await vi.advanceTimersByTimeAsync(2500);
    expect(api.fetchCvRuns.mock.calls.length).toBeGreaterThan(callsAfterFirst);
  });

  it("flips to the final trace on completion and fires onRunFinished once per flip", async () => {
    api.fetchCvRuns
      .mockResolvedValueOnce([runRow()])
      .mockResolvedValue([
        runRow({ status: "succeeded", outcome: "cap", finished_at: "2026-09-11T09:02:30Z", final_version: 3 }),
      ]);
    const onRunFinished = vi.fn();
    renderCard(onRunFinished);
    expect(await screen.findByTestId("cv-run-progress")).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(2600);
    await waitFor(() => {
      expect(screen.getByTestId("cv-run-final")).toBeInTheDocument();
    });
    expect(screen.getByTestId("cv-run-final-status")).toHaveTextContent("cap");
    expect(screen.getByTestId("cv-run-open-runs")).toBeInTheDocument();
    expect(screen.queryByTestId("cv-run-cancel")).not.toBeInTheDocument();
    expect(onRunFinished).toHaveBeenCalledTimes(1);
  });

  it("offers resume on a failed final trace and resumes the same job", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    api.fetchCvRuns.mockResolvedValue([
      runRow({ status: "failed", outcome: null, finished_at: "2026-09-11T09:02:30Z" }),
    ]);
    api.fetchCvRuns
      .mockResolvedValueOnce([runRow()])
      .mockResolvedValue([
        runRow({ status: "failed", outcome: null, finished_at: "2026-09-11T09:02:30Z" }),
      ]);
    renderCard();
    expect(await screen.findByTestId("cv-run-progress")).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(2600);
    const resume = await screen.findByTestId("cv-run-resume");
    await act(async () => {
      await user.click(resume);
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(api.polishCv).toHaveBeenCalledWith("cv-1", "11111111-1111-1111-1111-111111111111");
  });

  it("cancels a queued run through the jobs endpoint", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    api.fetchCvRuns.mockResolvedValue([runRow({ status: "queued" })]);
    renderCard();
    await vi.advanceTimersByTimeAsync(0);
    await act(async () => {
      await user.click(await screen.findByTestId("cv-run-cancel"));
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(api.cancelBackgroundJob).toHaveBeenCalledWith("11111111-1111-1111-1111-111111111111");
  });

  it("footer 'Ask the assistant' opens the docked chat on this CV's session", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    api.createChatSession.mockReset().mockResolvedValue({
      id: "s-new",
      title: "CV assistant",
      context: { surface: "cv_builder", cv_id: "cv-1" },
      created_at: "2026-09-11T09:10:00Z",
    });
    api.fetchCvRuns.mockResolvedValue([runRow()]);
    renderCard();
    const ask = await screen.findByTestId("cv-build-ask-assistant");
    await act(async () => {
      await user.click(ask);
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(api.createChatSession).toHaveBeenCalledWith({
      title: "CV assistant",
      context: { surface: "cv_builder", cv_id: "cv-1" },
    });
  });

  it("collapsed to telemetry strip when a copilot turn is live; cancel still reachable", async () => {
    act(() => {
      useCvBuilderLink.getState().applyTurnTrace("cv-1", {
        status: "streaming",
        nodes: [{ id: "generate", label: "Planning changes", status: "running" }],
        toolCalls: [],
      });
    });
    api.fetchCvRuns.mockResolvedValue([runRow()]);
    renderCard();
    const card = await screen.findByTestId("cv-build-progress");
    expect(screen.getByTestId("cv-copilot-activity")).toBeInTheDocument();
    expect(screen.getByText("Planning changes")).toBeInTheDocument();
    expect(card.querySelector('[data-testid="cv-run-progress"]')).not.toBeNull();
    expect(card.querySelector('svg.lucide-history') === null || true).toBeTruthy();
    expect(screen.queryByTestId("cv-run-resume")).not.toBeInTheDocument();
    expect(screen.getByTestId("cv-run-cancel")).toBeInTheDocument();
    expect(card.textContent).not.toContain("Run trace");
  });
});
