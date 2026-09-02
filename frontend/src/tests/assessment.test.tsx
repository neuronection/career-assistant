import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Assessment } from "@/pages/Assessment";
import type { AssessmentState } from "@/api/assessments";

const createAssessment = vi.fn();
const fetchAssessment = vi.fn();
const submitAnswers = vi.fn();
const advanceAssessment = vi.fn();

vi.mock("@/api/assessments", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/assessments")>();
  return {
    ...mod,
    createAssessment: (...args: unknown[]) => createAssessment(...args),
    fetchAssessment: (...args: unknown[]) => fetchAssessment(...args),
    submitAnswers: (...args: unknown[]) => submitAnswers(...args),
    advanceAssessment: (...args: unknown[]) => advanceAssessment(...args),
    cancelAssessment: vi.fn(),
    fetchTemplates: vi.fn().mockResolvedValue([]),
    runTemplate: vi.fn(),
    importTemplate: vi.fn(),
    exportTemplate: vi.fn().mockResolvedValue(undefined),
    assistQuestion: vi.fn().mockResolvedValue({ answer: "Think about a week in the job." }),
    fetchAssessmentResults: vi.fn().mockResolvedValue({
      run_id: "r1",
      kind: "full",
      status: "completed",
      skill_levels: [{ key: "programming", level: 6 }],
      interest_keys: ["technology-software"],
      selection: { "software-developer": 7 },
      shortlist: [{ job_id: "j1", fit_score: 8.2 }],
    }),
  };
});

function phaseTwoState(): AssessmentState {
  return {
    id: "r1",
    kind: "full",
    status: "in_progress",
    phase_order: [1, 2, 3, 4],
    current_phase: 2,
    phase_title: "Standardized scenarios",
    progress: {
      "1": { answered: 1, total: 1, title: "Profile foundation" },
      "2": { answered: 0, total: 2, title: "Standardized scenarios" },
    },
    context: {},
    phase_one_form: false,
    questions: [
      {
        id: "q1",
        phase: 2,
        kind: "scenario_mcq",
        prompt: "A teammate freezes the build. What now?",
        help: "Pick the closest reflex.",
        options: [
          { id: "o1", label: "Debug it yourself", detail: "", scores: {} },
          { id: "o2", label: "Organize the response", detail: "", scores: {} },
          { id: "o3", label: "Inform stakeholders", detail: "", scores: {} },
        ],
        time_split: null,
        source: "bank",
      },
      {
        id: "q2",
        phase: 2,
        kind: "slider",
        prompt: "How drawn are you to logistics?",
        help: "",
        options: [],
        time_split: { job_code: "logistics-coordinator" },
        source: "bank",
      },
    ],
  };
}

describe("Assessment wizard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createAssessment.mockResolvedValue(phaseTwoState());
    fetchAssessment.mockResolvedValue(phaseTwoState());
    submitAnswers.mockResolvedValue({ saved: 2 });
  });

  it("renders phase rail and questions from a fresh run", async () => {
    render(
      <MemoryRouter>
        <Assessment />
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByTestId("assessment")).toBeInTheDocument()
    );
    expect(screen.getByText(/Standardized scenarios/)).toBeInTheDocument();
    expect(screen.getAllByTestId("question-card")).toHaveLength(2);
    expect(screen.getByText(/A teammate freezes the build/)).toBeInTheDocument();
  });

  it("submits drafted answers and advances", async () => {
    advanceAssessment.mockResolvedValue({
      status: "in_progress",
      current_phase: 3,
    });
    fetchAssessment.mockResolvedValue({
      ...phaseTwoState(),
      current_phase: 3,
      questions: [],
    });
    render(
      <MemoryRouter>
        <Assessment />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByTestId("assessment")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Debug it yourself"));
    fireEvent.click(screen.getByTestId("advance-phase"));
    await waitFor(() => expect(submitAnswers).toHaveBeenCalled());
    const [runId, payload] = vi.mocked(submitAnswers).mock.calls[0];
    expect(runId).toBe("r1");
    const answers = payload as { question_id: string; answer: Record<string, unknown> }[];
    expect(answers[0].answer).toEqual({ option_id: "o1" });
  });

  it("renders results after completion", async () => {
    advanceAssessment.mockResolvedValue({ status: "completed" });
    render(
      <MemoryRouter>
        <Assessment />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByTestId("assessment")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("advance-phase"));
    await waitFor(() =>
      expect(screen.getByTestId("assessment-results")).toBeInTheDocument()
    );
    expect(screen.getByText(/programming/)).toBeInTheDocument();
  });
});

describe("Assessment templates (plan 37)", () => {
  beforeEach(() => {
    createAssessment.mockResolvedValue(phaseTwoState());
  });

  it("lists templates and starts a template run", async () => {
    const { fetchTemplates, runTemplate } = await import("@/api/assessments");
    vi.mocked(fetchTemplates).mockResolvedValue([
      {
        id: "t1",
        key: "team-style",
        version: 1,
        title: "Team style",
        description: "",
        source: "bank",
        visibility: "private",
        status: "published",
        audience_stages: [],
        language: "en",
        ref: "ABCD1234",
        content_hash: "h",
        is_bank: true,
        created_at: "2026-09-02T00:00:00Z",
      },
    ]);
    const templateState: AssessmentState = {
      ...phaseTwoState(),
      kind: "template",
      phase_order: [5],
      current_phase: 5,
      phase_title: "Core",
    };
    vi.mocked(runTemplate).mockResolvedValue(templateState);
    render(
      <MemoryRouter>
        <Assessment />
      </MemoryRouter>
    );
    const chip = await screen.findByTestId("template-chip");
    fireEvent.click(chip.querySelector("button:not([aria-label])") as HTMLElement);
    await waitFor(() => expect(runTemplate).toHaveBeenCalledWith("t1"));
    expect(await screen.findByTestId("template-note")).toHaveTextContent(
      "Running template: Team style"
    );
  });
});
