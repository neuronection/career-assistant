import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { Interviews } from "@/pages/Interviews";
import {
  createInterviewSession,
  debriefInterviewSession,
  fetchInterviewSession,
  fetchInterviewSessions,
  patchInterviewPlan,
  retryInterviewWeakAreas,
  startInterviewSession,
} from "@/api/interview";
import type { InterviewSessionOut } from "@/types/interview";

vi.mock("@/api/interview", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/interview")>();
  return {
    ...mod,
    createInterviewSession: vi.fn(),
    fetchInterviewSessions: vi.fn(),
    fetchInterviewSession: vi.fn(),
    patchInterviewPlan: vi.fn(),
    startInterviewSession: vi.fn(),
    debriefInterviewSession: vi.fn(),
    retryInterviewWeakAreas: vi.fn(),
  };
});

vi.mock("@/api/jobs", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/jobs")>();
  return {
    ...mod,
    fetchJobs: vi.fn().mockResolvedValue([
      { code: "backend-eng", title: "Backend Engineer" },
    ]),
  };
});

vi.mock("@/api/universities", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/universities")>();
  return {
    ...mod,
    fetchChatSessions: vi.fn().mockResolvedValue([]),
    fetchMessages: vi.fn().mockResolvedValue([]),
    createChatSession: vi.fn(),
  };
});

const PLAN = [
  {
    id: "q1",
    kind: "technical",
    skill_key: "sql",
    skill_label: "SQL",
    target_level: 4,
    question: "Walk me through a query you optimized.",
    focus: "",
  },
  {
    id: "q2",
    kind: "behavioral",
    skill_key: null,
    skill_label: "",
    target_level: null,
    question: "Tell me about shipping under deadline pressure.",
    focus: "",
  },
];

function makeSession(
  overrides: Record<string, unknown> = {}
): InterviewSessionOut {
  return {
    id: "s1",
    kind: "mixed",
    status: "planned",
    role_label: "Backend Engineer",
    posting_ref: "a1b2c3d4",
    chat_session_id: null,
    plan: PLAN,
    rubric_scores: [],
    debrief: null,
    created_at: "2026-09-07T00:00:00Z",
    updated_at: "2026-09-07T00:00:00Z",
    ...overrides,
  } as InterviewSessionOut;
}

describe("Interview practice page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchInterviewSessions).mockResolvedValue([makeSession()]);
    vi.mocked(fetchInterviewSession).mockResolvedValue(makeSession());
  });

  function renderPage() {
    return render(
      <MemoryRouter>
        <Interviews />
      </MemoryRouter>
    );
  }

  it("renders the workspace shell with rail and plan detail", async () => {
    renderPage();
    expect(await screen.findByTestId("interviews-toolbar")).toBeInTheDocument();
    expect(
      screen.getByTestId(`interview-session-s1`)
    ).toHaveTextContent("Backend Engineer");
    expect(await screen.findByTestId("plan-item-q1")).toHaveTextContent(
      "Walk me through a query you optimized."
    );
    expect(screen.getByTestId("plan-item-q1")).toHaveTextContent(
      "SQL · level 4"
    );
  });

  it("edits the plan: remove a question and save", async () => {
    const user = userEvent.setup();
    vi.mocked(patchInterviewPlan).mockImplementation(async (_id, items) =>
      makeSession({ plan: items })
    );
    renderPage();
    await screen.findByTestId("plan-item-q1");
    await user.click(screen.getByTestId("plan-remove-q1"));
    await user.click(screen.getByTestId("save-plan"));
    await waitFor(() =>
      expect(patchInterviewPlan).toHaveBeenCalledWith("s1", [PLAN[1]])
    );
    await waitFor(() =>
      expect(screen.queryByTestId("plan-item-q1")).not.toBeInTheDocument()
    );
  });

  it("starts practice and hands the session to the chat", async () => {
    const user = userEvent.setup();
    vi.mocked(startInterviewSession).mockResolvedValue(
      makeSession({
        status: "active",
        chat_session_id: "chat-1",
      })
    );
    renderPage();
    await user.click(await screen.findByTestId("practice-interview"));
    await waitFor(() =>
      expect(startInterviewSession).toHaveBeenCalledWith("s1")
    );
  });

  it("renders the debrief with aggregate, resources and retry", async () => {
    const user = userEvent.setup();
    const debrief = {
      summary: "Solid structure; quantify outcomes.",
      strengths: ["Clear structure"],
      gaps: ["No metrics"],
      recommendations: ["Add numbers"],
      aggregate: { structure: 7, evidence: 5, clarity: 7, answered: 2 },
      per_question: PLAN.map((item) => ({
        question_id: item.id,
        kind: item.kind,
        skill_key: item.skill_key,
        skill_label: item.skill_label,
        question: item.question,
        structure: 7,
        evidence: 5,
        clarity: 7,
        average: 6.33,
        weak: true,
      })),
      weak_question_ids: ["q1", "q2"],
      resources: [
        {
          skill_key: "sql",
          title: "SQL for Interviewing",
          provider: "Example Academy",
          url: "https://example.com/sql",
          kind: "course",
        },
      ],
    };
    const completed = makeSession({
      status: "completed",
      rubric_scores: [
        { question_id: "q1", structure: 7, evidence: 5, clarity: 7 },
        { question_id: "q2", structure: 7, evidence: 5, clarity: 7 },
      ],
      debrief,
    });
    vi.mocked(fetchInterviewSessions).mockResolvedValue([completed]);
    vi.mocked(fetchInterviewSession).mockResolvedValue(completed);
    vi.mocked(retryInterviewWeakAreas).mockResolvedValue(makeSession());

    renderPage();
    expect(await screen.findByTestId("interview-debrief")).toHaveTextContent(
      "Solid structure; quantify outcomes."
    );
    expect(screen.getByTestId("debrief-aggregate")).toHaveTextContent(
      "structure 7"
    );
    expect(screen.getByTestId("debrief-resources")).toHaveTextContent(
      "SQL for Interviewing"
    );
    await user.click(screen.getByTestId("retry-weak"));
    await waitFor(() =>
      expect(retryInterviewWeakAreas).toHaveBeenCalledWith("s1")
    );
  });

  it("generates the debrief for a completed session without one", async () => {
    const user = userEvent.setup();
    const completed = makeSession({
      status: "completed",
      rubric_scores: [
        { question_id: "q1", structure: 7, evidence: 5, clarity: 7 },
      ],
    });
    vi.mocked(fetchInterviewSessions).mockResolvedValue([completed]);
    vi.mocked(fetchInterviewSession).mockResolvedValue(completed);
    vi.mocked(debriefInterviewSession).mockResolvedValue(
      makeSession({
        status: "completed",
        debrief: {
          summary: "Done.",
          strengths: [],
          gaps: [],
          recommendations: [],
          aggregate: { structure: 6, evidence: 5, clarity: 7, answered: 1 },
          per_question: [],
          weak_question_ids: [],
          resources: [],
        },
      })
    );
    renderPage();
    await user.click(await screen.findByTestId("generate-debrief"));
    await waitFor(() =>
      expect(debriefInterviewSession).toHaveBeenCalledWith("s1")
    );
  });

  it("creates a session from the catalog role picker", async () => {
    const user = userEvent.setup();
    vi.mocked(createInterviewSession).mockResolvedValue(makeSession());
    renderPage();
    await user.click(await screen.findByTestId("add-interview"));
    await user.click(
      await screen.findByRole("combobox", { name: "Catalog role" })
    );
    await user.click(
      await screen.findByRole("option", { name: "Backend Engineer" })
    );
    await user.click(screen.getByTestId("create-interview"));
    await waitFor(() =>
      expect(createInterviewSession).toHaveBeenCalledWith({
        job_code: "backend-eng",
        kind: "mixed",
      })
    );
  });
});
