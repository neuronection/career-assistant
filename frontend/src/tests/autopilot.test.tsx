import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { Autopilot } from "@/features/growth/pages/Autopilot";
import {
  createGoal,
  deleteGoal,
  fetchFindingsByRun,
  fetchGoals,
  fetchRunDetail,
  patchGoal,
  runGoal,
  sendFindingFeedback,
} from "@/api/autopilot";
import type {
  AutopilotGoal,
  AutopilotRunWithFindings,
  AutopilotRunDetail,
} from "@/api/autopilot";
import { useAuthStore } from "@/stores/authStore";

vi.mock("@/api/autopilot", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/autopilot")>();
  return {
    ...mod,
    fetchGoals: vi.fn(),
    fetchFindingsByRun: vi.fn(),
    fetchRunDetail: vi.fn(),
    createGoal: vi.fn(),
    patchGoal: vi.fn().mockResolvedValue({ id: "g1", status: "active" }),
    deleteGoal: vi.fn().mockResolvedValue(undefined),
    runGoal: vi.fn(),
    sendFindingFeedback: vi.fn(),
  };
});

const mockGoals = vi.mocked(fetchGoals);
const mockRuns = vi.mocked(fetchFindingsByRun);
const mockRun = vi.mocked(runGoal);
const mockFeedback = vi.mocked(sendFindingFeedback);
const mockCreate = vi.mocked(createGoal);
const mockPatch = vi.mocked(patchGoal);
const mockDelete = vi.mocked(deleteGoal);
const mockRunDetail = vi.mocked(fetchRunDetail);

function goal(overrides: Partial<AutopilotGoal> = {}): AutopilotGoal {
  return {
    id: "g1",
    goal_text: "Junior QA job, remote",
    constraints: {
      must_terms: ["programming"],
      never_terms: ["sales"],
      family_keys: [],
      source_keys: [],
      remote: true,
      salary_min: 30000,
      seniority: ["junior"],
      exclude_seen: true,
      cooldown_days: 7,
      top_n: 5,
    },
    budget: { max_tokens: null, max_calls: null },
    cadence: { type: "daily_at", params: { time: "08:00" } },
    status: "active",
    last_run_at: "2026-09-05T08:00:00Z",
    created_at: "2026-09-01T08:00:00Z",
    updated_at: "2026-09-01T08:00:00Z",
    last_run: null,
    open_findings: 2,
    ...overrides,
  };
}

function runWithFindings(
  overrides: Partial<AutopilotRunWithFindings> = {}
): AutopilotRunWithFindings {
  return {
    id: "r1",
    status: "completed",
    started_at: "2026-09-05T08:00:00Z",
    finished_at: "2026-09-05T08:00:12Z",
    tokens_used: 1234,
    searches_executed: [
      {
        step: "search",
        query: "qa automation",
        rationale: "broad sweep",
        found: 12,
        examined: 40,
        error: "",
      },
      { step: "filter", seen: 2, never: 1, cooldown: 0, kept: 9 },
      { step: "replan", queries: ["data analyst"], rationale: "thin pass", found: 0 },
    ],
    error: "",
    created_at: "2026-09-05T08:00:00Z",
    goal_id: "g1",
    findings: [
      {
        id: "f1",
        posting_id: "p1",
        ref: "AB12CD34",
        title: "QA Automation Engineer",
        org: "SynthCo",
        url: "https://syn.example/1",
        score: 7.8,
        why: "Strong skills overlap with programming at SynthCo.",
        evidence: {
          quotes: ["We need programming and problem-solving"],
          verified: true,
          must_coverage: { hits: 1, total: 2 },
        },
        feedback: null,
        dismissed_at: null,
        created_at: "2026-09-05T08:00:10Z",
      },
      {
        id: "f2",
        posting_id: "p2",
        ref: "EF56GH78",
        title: "Data Analyst",
        org: "ExtractCo",
        url: "",
        score: 6.1,
        why: "Fit 6.1/10 (skills 6.5/10).",
        evidence: {},
        feedback: null,
        dismissed_at: null,
        created_at: "2026-09-05T08:00:11Z",
      },
    ],
    ...overrides,
  };
}

function renderPage(initialEntry = "/autopilot") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Autopilot />
    </MemoryRouter>
  );
}

function traceStep(overrides: Partial<AutopilotRunDetail["steps"][number]> = {}) {
  return {
    step: "search",
    kind: "deterministic",
    iteration: 1,
    at: "2026-09-05T08:00:01Z",
    duration_ms: 120,
    args: { goal: "Junior QA job, remote" },
    output: { pool: 3 },
    error: "",
    abort: "",
    ...overrides,
  };
}

function runDetail(overrides: Partial<AutopilotRunDetail> = {}): AutopilotRunDetail {
  return {
    run: {
      id: "r1",
      status: "completed",
      started_at: "2026-09-05T08:00:00Z",
      finished_at: "2026-09-05T08:00:12Z",
      tokens_used: 1234,
      searches_executed: [],
      error: "",
      created_at: "2026-09-05T08:00:00Z",
      goal_id: "g1",
      goal_text: "Junior QA job, remote",
    },
    steps: [
      traceStep({ step: "plan", kind: "llm", output: { variants: 3 } }),
      traceStep({ step: "search", output: { searches: [1, 2], pool: 9 } }),
      traceStep({ step: "filter", output: { kept: 9, pool: 9 } }),
      traceStep({ step: "deliver", output: { findings: [1], status: "completed" } }),
    ],
    nodes: ["plan", "search", "filter", "replan", "evaluate", "graph_sweep", "budget_guard", "curate", "deliver"],
    ai_calls: [
      {
        id: "gen-77",
        task_type: "autopilot_run",
        run_stage: "autopilot.plan",
        provider: "mock",
        model: "mock-mini",
        status: "ok",
        tokens_in: 120,
        tokens_out: 40,
        latency_ms: 210.5,
        prompt_version: "v1",
      },
    ],
    findings: [],
    timeline: [],
    trace_available: true,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: { email: "a@b.c", is_admin: false } as never });
  mockGoals.mockResolvedValue([goal()]);
  mockRuns.mockResolvedValue([runWithFindings()]);
  mockRunDetail.mockResolvedValue(runDetail());
  mockRun.mockResolvedValue({
    run_id: "r2",
    status: "completed",
    findings: [{ posting_id: "p1" }],
  });
  mockFeedback.mockResolvedValue({
    learned_terms: ["synthco"],
    goal_paused: false,
  });
  mockCreate.mockResolvedValue({ id: "g2" });
});

describe("Autopilot page", () => {
  it("renders goals with constraint chips and cadence", async () => {
    renderPage();
    expect(await screen.findByText("Junior QA job, remote")).toBeInTheDocument();
    expect(screen.getByText("must: programming")).toBeInTheDocument();
    expect(screen.getByText("never: sales")).toBeInTheDocument();
    expect(screen.getByText(/daily at 08:00/)).toBeInTheDocument();
    expect(screen.getByText("≥ 30,000")).toBeInTheDocument();
  });

  it("renders findings grouped by run with why + quotes", async () => {
    renderPage();
    expect(await screen.findByText("QA Automation Engineer")).toBeInTheDocument();
    expect(screen.getByText(/Strong skills overlap/)).toBeInTheDocument();
    expect(
      screen.getByText(/We need programming and problem-solving/)
    ).toBeInTheDocument();
    expect(screen.getByText("7.8")).toBeInTheDocument();
    expect(screen.getByText("Must-haves 1/2")).toBeInTheDocument();
  });

  it("hides must-have coverage when the goal has no must terms", async () => {
    mockRuns.mockResolvedValue([
      runWithFindings({
        findings: [
          {
            ...runWithFindings().findings[0],
            id: "f3",
            evidence: { must_coverage: { hits: 0, total: 0 } },
          },
        ],
      }),
    ]);
    renderPage();
    await screen.findByText("QA Automation Engineer");
    expect(screen.queryByTestId("coverage-f3")).toBeNull();
  });

  it("run now refreshes and reports the outcome", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Junior QA job, remote");
    await user.click(screen.getByTestId("run-now-g1"));
    await waitFor(() => expect(mockRun).toHaveBeenCalledWith("g1"));
    expect(await screen.findByTestId("autopilot-notice")).toHaveTextContent(
      /Found 1 new match/
    );
    expect(mockGoals).toHaveBeenCalledTimes(2);
  });

  it("feedback shows the learned terms explicitly", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("QA Automation Engineer");
    await user.click(screen.getByTestId("feedback-hide-f1"));
    await waitFor(() =>
      expect(mockFeedback).toHaveBeenCalledWith("f1", "hide_like_this")
    );
    expect(await screen.findByTestId("autopilot-notice")).toHaveTextContent(
      /Learned: synthco/
    );
  });

  it("toggles the run's transparency timeline", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("QA Automation Engineer");
    expect(screen.queryByText(/everything open|“qa automation”/)).toBeNull();
    await user.click(screen.getByTestId("timeline-toggle-r1"));
    expect(screen.getByTestId("run-timeline-r1")).toHaveTextContent(
      "What I searched"
    );
    expect(screen.getByTestId("run-timeline-r1")).toHaveTextContent("kept 9");
    expect(screen.getByTestId("run-timeline-r1")).toHaveTextContent("40 examined");
    expect(screen.getByTestId("run-timeline-r1")).toHaveTextContent("broadened the search");
  });

  it("creates a goal through the modal", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Junior QA job, remote");
    await user.click(screen.getByTestId("new-goal"));
    const text = await screen.findByLabelText("Your goal");
    await user.type(text, "Remote data job");
    await user.click(screen.getByTestId("goal-save"));
    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    const input = mockCreate.mock.calls[0][0];
    expect(input.goal_text).toBe("Remote data job");
  });

  it("pauses a goal", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Junior QA job, remote");
    await user.click(screen.getByTestId("pause-goal-g1"));
    await waitFor(() =>
      expect(mockPatch).toHaveBeenCalledWith("g1", { status: "paused" })
    );
  });

  it("deletes a goal after confirmation", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Junior QA job, remote");
    await user.click(screen.getByTestId("delete-goal-g1"));
    expect(await screen.findByText("Delete this goal?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("g1"));
  });

  it("shows the empty state with a next action", async () => {
    mockGoals.mockResolvedValue([]);
    mockRuns.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText("No goals yet")).toBeInTheDocument();
    expect(screen.getByText("Describe your goal")).toBeInTheDocument();
  });

  it("opens the run detail modal from the Details affordance", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("QA Automation Engineer");
    await user.click(screen.getByTestId("run-details-r1"));
    expect(await screen.findByTestId("run-detail-modal")).toBeInTheDocument();
    await waitFor(() =>
      expect(mockRunDetail).toHaveBeenCalledWith("r1")
    );
    expect(screen.getByTestId("run-detail-steps")).toBeInTheDocument();
  });

  it("opens a run by ?run= deep link even when it is not in the loaded list", async () => {
    mockRuns.mockResolvedValue([]);
    renderPage("/autopilot?run=r-remote");
    expect(await screen.findByTestId("run-detail-modal")).toBeInTheDocument();
    await waitFor(() =>
      expect(mockRunDetail).toHaveBeenCalledWith("r-remote")
    );
    expect(screen.getByTestId("run-detail-steps")).toBeInTheDocument();
  });

  it("renders the step trace and the replan loop branch", async () => {
    mockRunDetail.mockResolvedValue(
      runDetail({
        steps: [
          traceStep({ step: "plan", kind: "llm" }),
          traceStep({ step: "search", output: { searches: [1], pool: 0 } }),
          traceStep({ step: "filter", output: { kept: 0, pool: 0 } }),
          traceStep({ step: "replan", kind: "llm", output: { queries: ["broad"] } }),
          traceStep({ step: "search", iteration: 2, output: { searches: [1, 2], pool: 4 } }),
          traceStep({ step: "filter", iteration: 2, output: { kept: 4, pool: 4 } }),
          traceStep({ step: "deliver", output: { findings: [1], status: "completed" } }),
        ],
      })
    );
    renderPage("/autopilot?run=r1");
    await screen.findByTestId("run-detail-modal");
    expect(screen.getByTestId("run-detail-branch")).toBeInTheDocument();
    const steps = screen.getAllByTestId(/^run-detail-step-\d+$/);
    expect(steps).toHaveLength(7);
    expect(steps[4]).toHaveAttribute("data-step", "search");
  });

  it("renders graph chips in the endpoint's documented order with states", async () => {
    mockRunDetail.mockResolvedValue(
      runDetail({
        steps: [
          traceStep({ step: "plan", kind: "llm" }),
          traceStep({ step: "search", output: { searches: [1], pool: 2 } }),
          traceStep({ step: "filter", output: { kept: 2, pool: 2 } }),
          traceStep({ step: "evaluate", output: { pool: 2 } }),
          traceStep({ step: "budget_guard", abort: "budget", output: { abort: "budget" } }),
          traceStep({ step: "deliver", output: { findings: [1], status: "budget_aborted" } }),
        ],
      })
    );
    renderPage("/autopilot?run=r1");
    await screen.findByTestId("run-detail-modal");
    const chips = screen.getAllByTestId(/^run-detail-node-/);
    expect(chips.map((chip) => chip.textContent)).toEqual([
      "Plan",
      "Search",
      "Filter",
      "Replan",
      "Evaluate",
      "Graph sweep",
      "Budget guard",
      "Curate",
      "Deliver",
    ]);
    expect(screen.getByTestId("run-detail-node-plan")).toHaveAttribute("data-state", "done");
    expect(screen.getByTestId("run-detail-node-budget_guard")).toHaveAttribute(
      "data-state",
      "aborted"
    );
    expect(screen.getByTestId("run-detail-node-curate")).toHaveAttribute(
      "data-state",
      "skipped"
    );
  });

  it("falls back to the timeline for pre-trace runs", async () => {
    mockRunDetail.mockResolvedValue(
      runDetail({
        steps: [],
        trace_available: false,
        timeline: [
          { step: "search", query: "qa", rationale: "broad sweep", found: 12, examined: 40 },
        ],
      })
    );
    renderPage("/autopilot?run=r1");
    await screen.findByTestId("run-detail-fallback");
    expect(screen.queryByTestId("run-detail-steps")).toBeNull();
    expect(screen.getByTestId("run-detail-fallback")).toHaveTextContent("search timeline");
  });

  it("links each AI call to the audit detail modal for admins", async () => {
    useAuthStore.setState({ user: { email: "a@b.c", is_admin: true } as never });
    renderPage("/autopilot?run=r1");
    await screen.findByTestId("run-detail-modal");
    const link = await screen.findByTestId("run-detail-call-link-gen-77");
    expect(link).toHaveAttribute("href", "/settings/audit?tab=ai&detail=gen-77");
  });

  it("hides the audit link from non-admins but keeps the call metadata", async () => {
    useAuthStore.setState({ user: { email: "a@b.c", is_admin: false } as never });
    renderPage("/autopilot?run=r1");
    await screen.findByTestId("run-detail-modal");
    await waitFor(() =>
      expect(screen.getByTestId("run-detail-call-gen-77")).toBeInTheDocument()
    );
    expect(screen.queryByTestId("run-detail-call-link-gen-77")).toBeNull();
  });

  it("shows the missing-run note instead of an empty modal", async () => {
    mockRunDetail.mockRejectedValue(new Error("404"));
    renderPage("/autopilot?run=r-gone");
    expect(await screen.findByTestId("run-detail-missing")).toBeInTheDocument();
  });
});
