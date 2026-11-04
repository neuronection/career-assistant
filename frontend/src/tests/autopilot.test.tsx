import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { Autopilot } from "@/features/growth/pages/Autopilot";
import { AutopilotRunPage } from "@/features/growth/pages/AutopilotRunPage";
import {
  createGoal,
  DEFAULT_PROFILE_USAGE,
  deleteGoal,
  fetchFindingsFeed,
  fetchGoals,
  fetchProfileContext,
  fetchRunDetail,
  fetchRunsRail,
  patchGoal,
  runGoal,
  sendFindingFeedback,
} from "@/api/autopilot";
import type {
  AutopilotFindingFeedItem,
  AutopilotGoal,
  AutopilotRunDetail,
  ProfileContextSnapshot,
  RunsRailRow,
} from "@/api/autopilot";
import { markApplied } from "@/api/postings";
import { dismissRunFindings } from "@/api/autopilot";
import { useAuthStore } from "@/stores/authStore";

vi.mock("@/api/postings", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/postings")>();
  return { ...mod, markApplied: vi.fn().mockResolvedValue(undefined) };
});

vi.mock("@/api/autopilot", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/autopilot")>();
  return {
    ...mod,
    fetchGoals: vi.fn(),
    fetchFindingsFeed: vi.fn(),
    fetchRunsRail: vi.fn(),
    fetchRunDetail: vi.fn(),
    createGoal: vi.fn(),
    patchGoal: vi.fn().mockResolvedValue({ id: "g1", status: "active" }),
    deleteGoal: vi.fn().mockResolvedValue(undefined),
    runGoal: vi.fn(),
    sendFindingFeedback: vi.fn(),
    fetchProfileContext: vi.fn(),
    dismissRunFindings: vi.fn().mockResolvedValue({ dismissed: 3 }),
  };
});

const mockGoals = vi.mocked(fetchGoals);
const mockFeed = vi.mocked(fetchFindingsFeed);
const mockRail = vi.mocked(fetchRunsRail);
const mockRun = vi.mocked(runGoal);
const mockFeedback = vi.mocked(sendFindingFeedback);
const mockCreate = vi.mocked(createGoal);
const mockPatch = vi.mocked(patchGoal);
const mockDelete = vi.mocked(deleteGoal);
const mockRunDetail = vi.mocked(fetchRunDetail);
const mockProfileContext = vi.mocked(fetchProfileContext);
const mockMarkApplied = vi.mocked(markApplied);
const mockDismiss = vi.mocked(dismissRunFindings);

function snapshot(overrides: Partial<ProfileContextSnapshot> = {}): ProfileContextSnapshot {
  return {
    skills: [{ key: "programming", level: 4 }],
    education_level: "high_school",
    languages: [{ code: "en", level: "advanced" }],
    country: "Greece",
    city: "Athens",
    stage: "student",
    stage_source: "profile",
    lifestyle_count: 1,
    target_seniority: [],
    ...overrides,
  };
}

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
      profile: { ...DEFAULT_PROFILE_USAGE },
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

function feedItem(overrides: Partial<AutopilotFindingFeedItem> = {}): AutopilotFindingFeedItem {
  return {
    id: "f1",
    score: 7.8,
    why: "Strong skills overlap with programming at SynthCo.",
    quotes: ["We need programming and problem-solving"],
    must_coverage: { hits: 1, total: 2 },
    disabled_dims: 0,
    dismissed_at: null,
    feedback: null,
    created_at: "2026-09-05T08:00:10Z",
    run_id: "r1",
    run_status: "completed",
    goal_id: "g1",
    goal_text: "Junior QA job, remote",
    applied: false,
    posting: {
      id: "p1",
      ref: "AB12CD34",
      title: "QA Automation Engineer",
      org: "SynthCo",
      url: "https://syn.example/1",
      location: { city: "Athens", country: "Greece" },
      salary: null,
      posted_at: "2026-09-04T08:00:00Z",
      remote: "remote",
      status: "new",
      expires_at: null,
      source: "board-postings",
      extracted: true,
      seniority: "junior",
    },
    ...overrides,
  };
}

function railRow(overrides: Partial<RunsRailRow> = {}): RunsRailRow {
  return {
    id: "r1",
    goal_id: "g1",
    goal_text: "Junior QA job, remote",
    status: "completed",
    created_at: "2026-09-05T08:00:00Z",
    finished_at: "2026-09-05T08:00:12Z",
    tokens_used: 1234,
    findings_count: 2,
    examined_sum: 40,
    ...overrides,
  };
}

const EMPTY_FACETS = {
  goal: {},
  source: {},
  seniority: {},
  state: { open: 0, dismissed: 0 },
};

function feedResponse(
  items: AutopilotFindingFeedItem[],
  nextCursor: string | null = null
) {
  return { items, next_cursor: nextCursor, facets: { ...EMPTY_FACETS } };
}

function renderPage(initialEntry = "/autopilot") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/autopilot" element={<Autopilot />} />
        <Route path="/autopilot/runs/:runId" element={<AutopilotRunPage />} />
      </Routes>
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
  mockFeed.mockResolvedValue(feedResponse([feedItem()]));
  mockRail.mockResolvedValue([railRow()]);
  mockRunDetail.mockResolvedValue(runDetail());
  mockProfileContext.mockResolvedValue(snapshot());
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

describe("Autopilot workspace feed", () => {
  it("renders the flat findings feed with the evidence row", async () => {
    renderPage();
    expect(await screen.findByText("QA Automation Engineer")).toBeInTheDocument();
    expect(screen.getByText(/Strong skills overlap/)).toBeInTheDocument();
    expect(
      screen.getByText(/We need programming and problem-solving/)
    ).toBeInTheDocument();
    expect(screen.getByTestId("coverage-f1")).toHaveTextContent("Must-haves 1/2");
    expect(screen.getByTestId("finding-evidence-f1")).toBeInTheDocument();
    expect(screen.getByTestId("finding-run-f1")).toBeInTheDocument();
    expect(mockFeed).toHaveBeenCalledWith(
      expect.objectContaining({ state: "open", latest_per_posting: true })
    );
  });

  it("renders the applied badge and the closed-posting marker from the join", async () => {
    mockFeed.mockResolvedValue(
      feedResponse([
        feedItem({ applied: true }),
        feedItem({
          id: "f2",
          posting: {
            ...feedItem().posting,
            id: "p2",
            ref: "EF56GH78",
            title: "Closed Role",
            status: "expired",
          },
        }),
      ])
    );
    renderPage();
    expect(await screen.findByTestId("finding-applied-f1")).toBeInTheDocument();
    expect(screen.getByTestId(`finding-apply-f1`)).toBeDisabled();
    expect(screen.getByTestId("finding-state-f2")).toBeInTheDocument();
  });

  it("renders the plan-169 estimate footnote on unextracted cards", async () => {
    mockFeed.mockResolvedValue(
      feedResponse([
        feedItem({
          id: "f3",
          posting: { ...feedItem().posting, extracted: false },
          must_coverage: null,
        }),
      ])
    );
    renderPage();
    expect(await screen.findByTestId("finding-estimate-f3")).toBeInTheDocument();
    expect(screen.queryByTestId("coverage-f3")).toBeNull();
  });

  it("renders the runs rail rows with counts", async () => {
    mockRail.mockResolvedValue([
      railRow({ findings_count: 3, examined_sum: 52, tokens_used: 250 }),
      railRow({
        id: "r0",
        status: "budget_aborted",
        findings_count: 0,
        examined_sum: 7,
        tokens_used: 0,
      }),
    ]);
    renderPage();
    expect(await screen.findByTestId("runs-rail-row-r1")).toBeInTheDocument();
    expect(screen.getByTestId("runs-rail-counts-r1")).toHaveTextContent(
      "3 findings"
    );
    expect(screen.getByTestId("runs-rail-counts-r1")).toHaveTextContent(
      "52 examined"
    );
    expect(screen.getByTestId("runs-rail-counts-r0")).toHaveTextContent(
      "7 examined"
    );
    expect(screen.getByTestId("runs-rail-count")).toHaveTextContent("2");
  });

  it("switches between flat and by-run views through the URL", async () => {
    const user = userEvent.setup();
    mockFeed.mockResolvedValue(
      feedResponse([feedItem(), feedItem({ id: "f2", run_id: "r2" })])
    );
    renderPage();
    await screen.findByTestId("finding-title-f1");
    await user.click(screen.getByRole("button", { name: "By run" }));
    await waitFor(() =>
      expect(mockFeed).toHaveBeenCalledWith(
        expect.objectContaining({ latest_per_posting: false })
      )
    );
    expect(await screen.findByTestId("feed-run-group-r1")).toBeInTheDocument();
    expect(screen.getByTestId("feed-run-group-r2")).toBeInTheDocument();
  });

  it("renders facet counts on the rail chips", async () => {
    mockFeed.mockResolvedValue({
      items: [feedItem()],
      next_cursor: null,
      facets: {
        goal: { g1: 3 },
        source: { "board-postings": 2, other: 1 },
        seniority: { junior: 2, mid: 1 },
        state: { open: 3, dismissed: 1 },
      },
    });
    renderPage();
    await screen.findByTestId("finding-title-f1");
    expect(screen.getByTestId("findings-rail")).toBeInTheDocument();
    expect(screen.getByTestId("autopilot-filters")).toHaveClass("ca-stats-rail");
    await userEvent.setup().click(screen.getByRole("button", { name: "Source" }));
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /Seniority/ }));
    expect(screen.getByTestId("source-board-postings")).toHaveTextContent("· 2");
    expect(screen.getByTestId("seniority-mid")).toHaveTextContent("· 1");
  });

  it("rides the filter set through the URL and refetches", async () => {
    renderPage(
      "/autopilot?state=all&latest=0&min_score=7&org=acme&seniority=junior&posted_within=7d&sort=score"
    );
    await screen.findByTestId("findings-rail");
    await waitFor(() =>
      expect(mockFeed).toHaveBeenCalledWith(
        expect.objectContaining({
          state: "all",
          latest_per_posting: false,
          min_score: 7,
          org: "acme",
          seniority: "junior",
          posted_within: "7d",
          sort: "score",
        })
      )
    );
    expect(screen.getByTestId("findings-filter-count")).toBeInTheDocument();
  });

  it("toggles dedupe, hide-applied and remote from the rail", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("findings-rail");
    await user.click(screen.getByRole("button", { name: "State" }));
    await user.click(screen.getByTestId("findings-latest-toggle"));
    await waitFor(() =>
      expect(mockFeed).toHaveBeenCalledWith(
        expect.objectContaining({ latest_per_posting: false })
      )
    );
    await user.click(screen.getByTestId("findings-hide-applied-toggle"));
    await waitFor(() =>
      expect(mockFeed).toHaveBeenCalledWith(
        expect.objectContaining({ hide_applied: true })
      )
    );
    await user.click(screen.getByRole("button", { name: "Location" }));
    await user.click(screen.getByTestId("findings-remote-toggle"));
    await waitFor(() =>
      expect(mockFeed).toHaveBeenCalledWith(
        expect.objectContaining({ remote: true })
      )
    );
  });

  it("marks a finding applied through the postings path and flips the badge", async () => {
    const user = userEvent.setup();
    renderPage();
    const apply = await screen.findByTestId("finding-apply-f1");
    await user.click(apply);
    await waitFor(() =>
      expect(mockMarkApplied).toHaveBeenCalledWith("p1", "https://syn.example/1")
    );
    expect(await screen.findByTestId("finding-applied-f1")).toBeInTheDocument();
    expect(screen.getByTestId("finding-apply-f1")).toBeDisabled();
  });

  it("shows the filtered empty state with a clear action", async () => {
    const user = userEvent.setup();
    mockFeed.mockResolvedValue(feedResponse([]));
    renderPage("/autopilot?min_score=9");
    expect(await screen.findByTestId("feed-clear-filters")).toBeInTheDocument();
    await user.click(screen.getByTestId("feed-clear-filters"));
    await waitFor(() =>
      expect(mockFeed).toHaveBeenLastCalledWith(
        expect.objectContaining({ min_score: undefined })
      )
    );
  });

  it("filters the feed through the goal switcher", async () => {
    const user = userEvent.setup();
    mockGoals.mockResolvedValue([goal(), goal({ id: "g2", goal_text: "Data job" })]);
    renderPage();
    await screen.findByText("QA Automation Engineer");
    await user.click(screen.getByTestId("goal-chip-g2"));
    await waitFor(() =>
      expect(mockFeed).toHaveBeenCalledWith(
        expect.objectContaining({ goal_id: "g2" })
      )
    );
  });

  it("loads the next cursor page into the feed", async () => {
    const user = userEvent.setup();
    mockFeed
      .mockResolvedValueOnce(feedResponse([feedItem()], "cursor-1"))
      .mockResolvedValueOnce(
        feedResponse(
          [feedItem({ id: "f2", posting: { ...feedItem().posting, title: "Second Wave" } })],
          null
        )
      );
    renderPage();
    await screen.findByTestId("finding-title-f1");
    await user.click(screen.getByTestId("feed-load-more"));
    expect(await screen.findByText("Second Wave")).toBeInTheDocument();
    expect(mockFeed).toHaveBeenLastCalledWith(
      expect.objectContaining({ cursor: "cursor-1" })
    );
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
});

describe("Autopilot goals", () => {
  it("renders the selected goal's chips and cadence in the goal bar", async () => {
    renderPage("/autopilot?goal=g1");
    expect(await screen.findByTestId("goal-card-g1")).toHaveTextContent(
      "Junior QA job, remote"
    );
    expect(screen.getByText("must: programming")).toBeInTheDocument();
    expect(screen.getByText("never: sales")).toBeInTheDocument();
    expect(screen.getByText(/daily at 08:00/)).toBeInTheDocument();
    expect(screen.getByText("≥ 30,000")).toBeInTheDocument();
  });

  it("creates a goal through the modal", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("QA Automation Engineer");
    await user.click(screen.getByTestId("new-goal"));
    const text = await screen.findByLabelText("Your goal");
    await user.type(text, "Remote data job");
    await user.click(screen.getByTestId("goal-save"));
    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    const input = mockCreate.mock.calls[0][0];
    expect(input.goal_text).toBe("Remote data job");
  });

  it("runs the selected goal now and refreshes", async () => {
    const user = userEvent.setup();
    renderPage("/autopilot?goal=g1");
    await screen.findByTestId("goal-card-g1");
    await user.click(screen.getByTestId("run-now-g1"));
    await waitFor(() => expect(mockRun).toHaveBeenCalledWith("g1"));
    expect(await screen.findByTestId("autopilot-notice")).toHaveTextContent(
      /Found 1 new match/
    );
  });

  it("pauses a goal", async () => {
    const user = userEvent.setup();
    renderPage("/autopilot?goal=g1");
    await screen.findByTestId("goal-card-g1");
    await user.click(screen.getByTestId("pause-goal-g1"));
    await waitFor(() =>
      expect(mockPatch).toHaveBeenCalledWith("g1", { status: "paused" })
    );
  });

  it("deletes a goal after confirmation", async () => {
    const user = userEvent.setup();
    renderPage("/autopilot?goal=g1");
    await screen.findByTestId("goal-card-g1");
    await user.click(screen.getByTestId("delete-goal-g1"));
    expect(await screen.findByText("Delete this goal?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("g1"));
  });

  it("shows the empty state with a next action", async () => {
    mockGoals.mockResolvedValue([]);
    mockFeed.mockResolvedValue(feedResponse([]));
    renderPage();
    expect(await screen.findByText("No goals yet")).toBeInTheDocument();
    expect(screen.getByText("Describe your goal")).toBeInTheDocument();
  });

  it("round-trips the profile usage block through the modal", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("QA Automation Engineer");
    await user.click(screen.getByTestId("new-goal"));
    const text = await screen.findByLabelText("Your goal");
    await user.type(text, "Remote data job");
    await user.click(screen.getByTestId("usage-section-toggle"));
    await user.click(screen.getByTestId("toggle-skills"));
    await user.click(screen.getByTestId("goal-save"));
    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    const payload = mockCreate.mock.calls[0][0];
    expect(payload.constraints?.profile?.use_skills).toBe(false);
    expect(payload.constraints?.profile?.use_education).toBe(true);
    expect(payload.constraints?.profile?.stage_source).toBe("profile");
    expect(fetchProfileContext).toHaveBeenCalledWith(
      expect.objectContaining({ use_skills: false }),
      []
    );
  });

  it("saves defaults that match today's behavior when the section stays closed", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("QA Automation Engineer");
    await user.click(screen.getByTestId("new-goal"));
    const text = await screen.findByLabelText("Your goal");
    await user.type(text, "Remote data job");
    await user.click(screen.getByTestId("goal-save"));
    await waitFor(() => expect(mockCreate).toHaveBeenCalled());
    const payload = mockCreate.mock.calls[0][0];
    expect(payload.constraints?.profile).toEqual({ ...DEFAULT_PROFILE_USAGE });
  });

  it("shows a live usage summary that reflects the toggles", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByTestId("new-goal"));
    await user.click(screen.getByTestId("usage-section-toggle"));
    const summary = await screen.findByTestId("usage-summary");
    await waitFor(() => {
      expect(summary.textContent).toContain("Skills: programming");
      expect(summary.textContent).toContain("Education: high_school");
      expect(summary.textContent).toContain("Languages: en");
      expect(summary.textContent).toContain("Stage: student");
      expect(summary.textContent).toContain("Location: Athens");
    });

    mockProfileContext.mockResolvedValue(
      snapshot({ stage: "early_career", stage_source: "goal" })
    );
    await user.click(screen.getByRole("button", { name: "From this goal's seniority" }));
    await waitFor(() => expect(summary.textContent).toContain("Stage: early_career"));

    mockProfileContext.mockResolvedValue(
      snapshot({ stage: "student", stage_source: "profile" })
    );
    await user.click(screen.getByTestId("toggle-experience"));
    await waitFor(() => {
      expect(summary.textContent).toContain("Experience: not used");
      expect(summary.textContent).not.toContain("Stage: early_career");
    });

    await user.click(screen.getByTestId("toggle-experience"));
    await waitFor(() => expect(summary.textContent).toContain("Stage: from your profile"));
  });

  it("shows the searching-from-goal-only note when an input is switched off", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByTestId("new-goal"));
    await user.click(screen.getByTestId("usage-section-toggle"));
    expect(screen.queryByTestId("usage-goal-only")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("toggle-skills"));
    expect(await screen.findByTestId("usage-goal-only")).toBeInTheDocument();
  });

  it("renders disabled-usage chips on the goal bar", async () => {
    mockGoals.mockResolvedValue([
      goal({
        id: "g2",
        constraints: {
          must_terms: [],
          never_terms: [],
          family_keys: [],
          source_keys: [],
          remote: null,
          salary_min: null,
          seniority: [],
          exclude_seen: true,
          cooldown_days: 7,
          top_n: 5,
          profile: {
            use_skills: false,
            use_education: true,
            use_languages: true,
            use_location: true,
            use_experience: true,
            use_lifestyle: true,
            stage_source: "goal",
          },
        },
      }),
    ]);
    renderPage("/autopilot?goal=g2");
    const card = await screen.findByTestId("goal-card-g2");
    expect(card.textContent).toContain("no skills");
    expect(card.textContent).toContain("stage from goal");
    expect(card.textContent).not.toContain("no education");
  });
});

describe("Autopilot run quick-peek modal", () => {
  it("opens the quick-peek modal from the finding's run provenance", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("finding-title-f1");
    await user.click(screen.getByTestId("finding-run-f1"));
    expect(await screen.findByTestId("run-detail-modal")).toBeInTheDocument();
    await waitFor(() => expect(mockRunDetail).toHaveBeenCalledWith("r1"));
    expect(screen.getByTestId("run-detail-steps")).toBeInTheDocument();
  });

  it("links the quick-peek to the full run page", async () => {
    renderPage();
    await screen.findByTestId("finding-title-f1");
    await userEvent.setup().click(screen.getByTestId("finding-run-f1"));
    const openFull = await screen.findByTestId("run-detail-open-full");
    expect(openFull).toHaveAttribute("href", "/autopilot/runs/r1");
  });

  it("navigates a ?run= deep link to the run page", async () => {
    renderPage("/autopilot?run=r-remote");
    expect(await screen.findByTestId("autopilot-run-page")).toBeInTheDocument();
    await waitFor(() => expect(mockRunDetail).toHaveBeenCalledWith("r-remote"));
    expect(screen.getByTestId("run-detail-steps")).toBeInTheDocument();
  });
});

describe("Autopilot run page", () => {
  it("renders a run by id, even one absent from every loaded list", async () => {
    renderPage("/autopilot/runs/r-lone");
    expect(await screen.findByTestId("autopilot-run-page")).toBeInTheDocument();
    await waitFor(() => expect(mockRunDetail).toHaveBeenCalledWith("r-lone"));
    expect(screen.getByTestId("run-detail-steps")).toBeInTheDocument();
    expect(screen.getByTestId("run-page-back")).toHaveAttribute("href", "/autopilot");
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
    renderPage("/autopilot/runs/r1");
    await screen.findByTestId("autopilot-run-page");
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
    renderPage("/autopilot/runs/r1");
    await screen.findByTestId("autopilot-run-page");
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
    renderPage("/autopilot/runs/r1");
    await screen.findByTestId("run-detail-fallback");
    expect(screen.queryByTestId("run-detail-steps")).toBeNull();
    expect(screen.getByTestId("run-timeline-r1")).toBeInTheDocument();
    expect(screen.getByTestId("run-timeline-r1")).toHaveTextContent("40 examined");
  });

  it("links the run's findings into the feed filtered by run_id", async () => {
    mockRunDetail.mockResolvedValue(
      runDetail({
        findings: [
          {
            id: "f1",
            posting_id: "p1",
            ref: "AB12CD34",
            title: "QA Automation Engineer",
            org: "SynthCo",
            url: "",
            score: 7.8,
            why: "why",
            evidence: {},
            feedback: null,
            dismissed_at: null,
            created_at: "2026-09-05T08:00:10Z",
          },
        ],
      })
    );
    renderPage("/autopilot/runs/r1");
    await screen.findByTestId("autopilot-run-page");
    const link = await screen.findByTestId("run-findings-feed-link");
    expect(link).toHaveAttribute("href", "/autopilot?run_id=r1");
  });

  it("links each AI call to the audit detail modal for admins", async () => {
    useAuthStore.setState({ user: { email: "a@b.c", is_admin: true } as never });
    renderPage("/autopilot/runs/r1");
    await screen.findByTestId("autopilot-run-page");
    const link = await screen.findByTestId("run-detail-call-link-gen-77");
    expect(link).toHaveAttribute("href", "/settings/audit?tab=ai&detail=gen-77");
  });

  it("hides the audit link from non-admins but keeps the call metadata", async () => {
    useAuthStore.setState({ user: { email: "a@b.c", is_admin: false } as never });
    renderPage("/autopilot/runs/r1");
    await screen.findByTestId("autopilot-run-page");
    await waitFor(() =>
      expect(screen.getByTestId("run-detail-call-gen-77")).toBeInTheDocument()
    );
    expect(screen.queryByTestId("run-detail-call-link-gen-77")).toBeNull();
  });

  it("dismisses all of the run's findings after confirmation", async () => {
    const user = userEvent.setup();
    mockRunDetail.mockResolvedValue(
      runDetail({
        findings: [
          {
            id: "fopen",
            posting_id: "p1",
            ref: "AB12CD34",
            title: "Open finding",
            org: "SynthCo",
            url: "",
            score: 7.0,
            why: "why",
            evidence: {},
            feedback: null,
            dismissed_at: null,
            created_at: "2026-09-05T08:00:10Z",
          },
        ],
      })
    );
    renderPage("/autopilot/runs/r1");
    await screen.findByTestId("autopilot-run-page");
    const callsBefore = mockRunDetail.mock.calls.length;
    await user.click(screen.getByTestId("run-dismiss-all"));
    await user.click(await screen.findByRole("button", { name: "Dismiss all from this run" }));
    await waitFor(() => expect(mockDismiss).toHaveBeenCalledWith("r1"));
    await waitFor(() => expect(mockRunDetail.mock.calls.length).toBeGreaterThan(callsBefore));
  });

  it("hides the dismiss-all action when no open findings remain", async () => {
    mockRunDetail.mockResolvedValue(
      runDetail({
        findings: [
          {
            id: "fd1",
            posting_id: "p1",
            ref: "AB12CD34",
            title: "Closed out",
            org: "SynthCo",
            url: "",
            score: 7.0,
            why: "why",
            evidence: {},
            feedback: null,
            dismissed_at: "2026-09-06T08:00:00Z",
            created_at: "2026-09-05T08:00:10Z",
          },
        ],
      })
    );
    renderPage("/autopilot/runs/r1");
    await screen.findByTestId("autopilot-run-page");
    expect(screen.queryByTestId("run-dismiss-all")).toBeNull();
  });

  it("shows the missing-run note for a foreign or missing id", async () => {
    mockRunDetail.mockRejectedValue(new Error("404"));
    renderPage("/autopilot/runs/r-gone");
    expect(await screen.findByTestId("run-detail-missing")).toBeInTheDocument();
  });

  it("renders the plan inputs panel with languages and stage", async () => {
    const detail = runDetail();
    detail.steps = [
      traceStep({
        step: "plan",
        kind: "llm",
        args: {
          goal: "Junior QA job, remote",
          constraints: ["profile", "seniority"],
          budget: [],
          profile: {
            skills: 2,
            languages: 1,
            stage: "student",
            stage_source: "goal",
            education_level: "high_school",
            target_seniority: ["junior"],
          },
        },
        output: { variants: 3 },
      }),
    ];
    mockRunDetail.mockResolvedValue(detail);
    renderPage("/autopilot/runs/r1");
    const inputs = await screen.findByTestId("run-detail-inputs");
    await waitFor(() => {
      expect(inputs.textContent).toContain("2 skills");
      expect(inputs.textContent).toContain("1 languages");
      expect(inputs.textContent).toContain("stage student");
    });
  });
});
