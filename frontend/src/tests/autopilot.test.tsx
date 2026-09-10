import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { Autopilot } from "@/pages/Autopilot";
import {
  createGoal,
  deleteGoal,
  fetchFindingsByRun,
  fetchGoals,
  patchGoal,
  runGoal,
  sendFindingFeedback,
} from "@/api/autopilot";
import type { AutopilotGoal, AutopilotRunWithFindings } from "@/api/autopilot";

vi.mock("@/api/autopilot", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/autopilot")>();
  return {
    ...mod,
    fetchGoals: vi.fn(),
    fetchFindingsByRun: vi.fn(),
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
        error: "",
      },
      { step: "filter", seen: 2, never: 1, cooldown: 0, kept: 9 },
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
        evidence: { quotes: ["We need programming and problem-solving"], verified: true },
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

function renderPage() {
  return render(
    <MemoryRouter>
      <Autopilot />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGoals.mockResolvedValue([goal()]);
  mockRuns.mockResolvedValue([runWithFindings()]);
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
});
